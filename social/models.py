from django.conf import settings
from django.db import models
from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone


class PostQuerySet(models.QuerySet):

    def published(self):
        return self.filter(is_published=True)

    def drafts_for(self, user):
        return self.filter(is_published=False, author=user)

    def visible_to(self, user):
        """Published posts, plus the viewer's own drafts."""
        if not user.is_authenticated:
            return self.published()
        return self.filter(Q(is_published=True) | Q(author=user))

    def for_cards(self, viewer):
        """Everything post_card.html needs, in one query: author, sample,
        tags, counts, and whether the viewer has liked it. Shared by the feed
        and the profile so the card renders identically in both."""
        return (
            self.select_related("author", "sample__metadata")
            .prefetch_related("sample__sample_tags__tag")
            .annotate(
                # distinct on every Count: the three joins would otherwise
                # multiply each other's rows.
                like_count=Count("likes", distinct=True),
                comment_count=Count("comments", distinct=True),
                download_count=Count("sample__downloads", distinct=True),
                liked_by_user=Exists(
                    Like.objects.filter(post=OuterRef("pk"), user=viewer)
                ),
            )
        )


class Post(models.Model):
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="posts",
    )
    # PROTECT so a published post guards its audio: delete_sample surfaces
    # this as a friendly error. Draft posts do not shield their samples —
    # Sample.delete() removes the draft before the row goes.
    sample = models.OneToOneField(
        "library.Sample",
        on_delete=models.PROTECT,
        related_name="post",
    )
    body = models.CharField(max_length=250, blank=True)

    # A post is created as a draft at upload and published only once the
    # user has confirmed the analysis output (S4: human authority).
    is_published = models.BooleanField(default=False, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    objects = PostQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        state = "" if self.is_published else " [draft]"
        return f"{self.author}: {self.body[:40]}{state}"

    def publish(self):
        self.is_published = True
        self.published_at = timezone.now()
        self.save(update_fields=["is_published", "published_at"])


class Comment(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="comments"
    )
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE,
        null=True, blank=True, related_name="replies",
    )
    body = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.author} on {self.post_id}"


class Like(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="likes")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="likes"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["post", "user"], name="unique_like_per_user_post"
            ),
        ]

    def __str__(self):
        return f"{self.user} liked {self.post_id}"