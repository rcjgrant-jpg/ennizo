# social/views.py
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Exists, OuterRef
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from library.models import Sample, SampleTag, TagStatus

from .forms import CommentForm, DraftForm, PublishForm
from .models import Comment, Like, Post


# --- helpers -----------------------------------------------------------------

def _discard_drafts(drafts):
    """Remove draft posts. Uncommitted samples go with them (all sample
    deletion flows through Sample.delete); committed samples keep their
    audio and merely lose the draft riding on them."""
    Sample.objects.filter(post__in=drafts).discard()
    drafts.delete()



def _selected_tags(request):
    """Normalised, de-duplicated list of tag names from the query string."""
    names = []
    for raw in request.GET.getlist("tag"):
        name = raw.strip().lower()
        if name and name not in names:
            names.append(name)
    return names


def _tag_url(selected, add=None, remove=None):
    """Build a feed URL representing the tag set after adding or removing one."""
    names = list(selected)
    if remove and remove in names:
        names.remove(remove)
    if add and add not in names:
        names.append(add)
    query = urlencode([("tag", name) for name in names])
    base = reverse("social:index")
    return f"{base}?{query}" if query else base


def _feed_queryset(request, selected):
    posts = (
        Post.objects.published()
        .select_related("author", "sample")
        .prefetch_related("sample__sample_tags__tag")
        .annotate(
            like_count=Count("likes", distinct=True),
            comment_count=Count("comments", distinct=True),
            liked_by_user=Exists(
                Like.objects.filter(post=OuterRef("pk"), user=request.user)
            ),
        )
    )

    # One filter() call per tag = AND semantics: a post must carry every
    # selected tag, not any of them.
    for name in selected:
        posts = posts.filter(sample__tags__name=name)

    return posts.order_by("-created_at").distinct()


def _visible_post_ids(selected):
    """Post ids under the current tag filter, with no annotations or ordering.

    Kept deliberately plain so it can be used as a subquery without tripping
    PostgreSQL's SELECT DISTINCT / ORDER BY restriction.
    """
    qs = Post.objects.published()
    for name in selected:
        qs = qs.filter(sample__tags__name=name)
    return qs.values_list("id", flat=True).distinct()


def _feed_context(request):
    selected = _selected_tags(request)
    return {
        "posts": _feed_queryset(request, selected),
        "selected_tags": [
            {"name": name, "remove_url": _tag_url(selected, remove=name)}
            for name in selected
        ],
        "clear_url": reverse("social:index"),
        "active_page": "feed",
    }


def _client_redirect(request, url_name):
    """Redirect in a way htmx honours.

    An ordinary 302 is followed transparently by the XHR, so htmx receives the
    whole feed page and swaps it into the composer, nesting a second copy of
    every post inside the first. HX-Redirect instructs htmx to perform a real
    browser navigation instead. Non-htmx submissions still get a plain 302.
    """
    url = reverse(url_name)
    if request.headers.get("HX-Request"):
        response = HttpResponse(status=204)
        response["HX-Redirect"] = url
        return response
    return redirect(url)


def _comments_context(post, form):
    thread = (
        Comment.objects
        .filter(post=post, parent__isnull=True)
        .select_related("author")
        .prefetch_related("replies__author")
    )
    return {
        "post": post,
        "comments": thread,
        "comment_form": form,
        "comment_count": Comment.objects.filter(post=post).count(),
    }

# --- views -------------------------------------------------------------------

@login_required
def index(request):
    context = _feed_context(request)
    context["form"] = DraftForm(user=request.user) if "compose" in request.GET else None
    context["publish_form"] = PublishForm() if "compose" in request.GET else None
    draft = Post.objects.drafts_for(request.user).select_related("sample__metadata").first()
    context["draft"] = draft

    if request.headers.get("HX-Request"):
        return render(request, "social/partials/feed_root.html", context)

    return render(request, "social/feed.html", context)

@login_required
@require_POST
def create_draft(request):
    """Phase one. Creates Sample (if uploading) and a draft Post, then returns
    the analysis panel. Fired by htmx as soon as a file is chosen."""
    form = DraftForm(request.POST, request.FILES, user=request.user)

    if not form.is_valid():
        return render(request, "social/partials/composer_attach.html", {"form": form})

    with transaction.atomic():
        # Resolve the sample first: if it already carries a draft, that
        # draft must survive the supersede below.
        sample = form.cleaned_data.get("sample") or form.build_sample()

        # Attaching a second file supersedes the first; other drafts go.
        _discard_drafts(Post.objects.drafts_for(request.user).exclude(sample=sample))

        # Post↔Sample is one-to-one: re-open an existing draft over creating
        # a duplicate, which would raise IntegrityError.
        post = getattr(sample, "post", None)
        if post is None:
            post = Post.objects.create(author=request.user, sample=sample, body="")

    if not request.headers.get("HX-Request"):
        return redirect(f"{reverse('social:index')}?compose=1")

    return render(request, "social/partials/composer_draft.html", {
        "post": post,
        "sample": sample,
        "metadata": getattr(sample, "metadata", None),
    })


@login_required
def draft_state(request, pk):
    """Polled fragment for the composer's analysis panel."""
    post = get_object_or_404(
        Post.objects.select_related("sample__metadata"), pk=pk, author=request.user
    )
    return render(request, "social/partials/composer_draft.html", {
        "post": post,
        "sample": post.sample,
        "metadata": getattr(post.sample, "metadata", None),
    })


@login_required
@require_POST
def publish_draft(request):
    """Phase two. Writes the caption onto the draft, then publishes.

    The draft's pk arrives in the POST body rather than the URL, because the
    form's action is rendered before any draft exists — the hidden draft_pk
    input is injected into the form when the attach area is swapped.
    """
    draft_pk = request.POST.get("draft_pk", "")
    if not draft_pk.isdigit():
        messages.error(request, "Attach a sample before posting.")
        return _client_redirect(request, "social:index")

    post = get_object_or_404(
        Post.objects.select_related("sample"), pk=int(draft_pk), author=request.user
    )
    form = PublishForm(request.POST, instance=post)

    if not form.is_valid():
        return render(request, "social/partials/composer_draft.html", {
            "post": post,
            "sample": post.sample,
            "metadata": getattr(post.sample, "metadata", None),
            "form": form,
        })

    with transaction.atomic():
        post = form.save()
        # Suggestions the user neither kept nor removed are accepted on
        # publication. Discarding them instead would mean the classifier
        # contributes nothing unless every chip is clicked, which penalises
        # the common case. Rejection remains an explicit act.
        
        
        SampleTag.objects.filter(
            sample=post.sample, status=TagStatus.SUGGESTED
        ).update(status=TagStatus.ACCEPTED)
        if not post.is_published:
            post.publish()
            
        post.sample.is_committed = True
        post.sample.save(update_fields=["is_committed"])

    messages.success(request, "Posted.")
    return _client_redirect(request, "social:index")





@login_required
@require_POST
def discard_draft(request):
    """Throw away the current draft and return the empty attach control."""
    _discard_drafts(Post.objects.drafts_for(request.user))
    return render(request, "social/partials/composer_attach.html", {
        "form": DraftForm(user=request.user),
    })





@login_required
@require_POST
def toggle_like(request, pk):
    post = get_object_or_404(Post, pk=pk)

    like, created = Like.objects.get_or_create(post=post, user=request.user)
    if not created:
        like.delete()

    return render(request, "social/partials/like_button.html", {
        "post": post,
        "liked": created,
        "like_count": post.likes.count(),
    })


@login_required
def post_comments(request, pk):
    post = get_object_or_404(Post, pk=pk)
    return render(
        request,
        "social/partials/comments.html",
        _comments_context(post, CommentForm()),
    )


@login_required
@require_POST
def add_comment(request, pk):
    post = get_object_or_404(Post, pk=pk)
    form = CommentForm(request.POST)

    if form.is_valid():
        comment = form.save(commit=False)
        comment.post = post
        comment.author = request.user

        parent = form.cleaned_data.get("parent")
        if parent and parent.post_id == post.pk:
            # Flatten: a reply to a reply attaches to the top-level comment,
            # so the thread never nests deeper than one level.
            comment.parent = parent.parent or parent

        comment.save()
        form = CommentForm()

    return render(request, "social/partials/comments.html", _comments_context(post, form))


@login_required
def tag_suggest(request):
    query = request.GET.get("q", "").strip().lower()
    selected = _selected_tags(request)
    suggestions = []

    if query:
        rows = (
            Post.objects.published()
            .filter(id__in=_visible_post_ids(selected), sample__tags__name__icontains=query)
            .values("sample__tags__name")
            .annotate(post_count=Count("id", distinct=True))
            .order_by("-post_count", "sample__tags__name")
        )

        for row in rows:
            name = row["sample__tags__name"]
            if name in selected:
                continue
            suggestions.append({
                "name": name,
                "post_count": row["post_count"],
                "add_url": _tag_url(selected, add=name),
            })
            if len(suggestions) == 8:
                break

    return render(request, "social/partials/tag_suggestions.html", {
        "suggestions": suggestions,
        "query": query,
    })