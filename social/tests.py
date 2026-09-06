"""
Test case IDs (TC-SOC-xxx) are referenced by the dissertation's
traceability matrix. Story IDs (Ux.x) reference the requirements document.

Run with:  python manage.py test social
"""

import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Library
from library.models import (
    Folder,
    Sample,
    SampleTag,
    Tag,
    TagSource,
    TagStatus,
)

from .models import Comment, Like, Post

User = get_user_model()

TEMP_MEDIA = tempfile.mkdtemp(prefix="ennizo-test-media-")


def tearDownModule():
    shutil.rmtree(TEMP_MEDIA, ignore_errors=True)


def make_user(username):
    user = User.objects.create_user(username=username, password="pw")
    Library.objects.get_or_create(user=user)
    return user


def make_sample(folder, title="Kick", committed=True, public=True):
    sample = Sample(
        folder=folder, title=title, is_committed=committed, is_public=public
    )
    sample.audio_file.save(
        "test.wav", SimpleUploadedFile("test.wav", b"RIFFfakewavdata"), save=True
    )
    return sample


def make_published_post(author, folder, title="Kick", tags=()):
    sample = make_sample(folder, title=title)
    for name in tags:
        tag, _ = Tag.objects.get_or_create(
            name=name, defaults={"kind": Tag.Kind.SUBJECTIVE}
        )
        SampleTag.objects.create(
            sample=sample, tag=tag, source=TagSource.USER
        )
    post = Post.objects.create(author=author, sample=sample)
    post.publish()
    return post


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class BaseSocialTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = make_user("author")
        cls.reader = make_user("reader")
        cls.folder = Folder.objects.create(
            library=cls.author.library, name="Drums"
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.reader)


class FeedVisibilityTests(BaseSocialTest):
    """TC-SOC-001..002 — drafts stay private to their author."""

    def test_feed_shows_published_posts_only(self):
        """TC-SOC-001: a draft post never appears in another user's feed."""
        published = make_published_post(self.author, self.folder, "Pub")
        draft_sample = make_sample(self.folder, title="Draft")
        Post.objects.create(author=self.author, sample=draft_sample)
        response = self.client.get(reverse("social:index"))
        posts = list(response.context["posts"])
        self.assertIn(published, posts)
        self.assertEqual(len(posts), 1)

    def test_visible_to_includes_own_drafts(self):
        """TC-SOC-002: the queryset shows an author their own drafts."""
        sample = make_sample(self.folder)
        draft = Post.objects.create(author=self.author, sample=sample)
        self.assertIn(draft, Post.objects.visible_to(self.author))
        self.assertNotIn(draft, Post.objects.visible_to(self.reader))


class PublishFlowTests(BaseSocialTest):
    """TC-SOC-010..012 — publishing commits the sample and settles tags
    (S4; register: publish accepts unruled suggestions; provisional state
    lives on the sample)."""

    def _draft(self):
        sample = make_sample(self.folder, committed=False)
        post = Post.objects.create(author=self.author, sample=sample)
        return post, sample

    def test_publish_commits_sample_and_publishes_post(self):
        """TC-SOC-010: publishing marks the post published and the sample
        committed in one transaction."""
        post, sample = self._draft()
        self.client.force_login(self.author)
        response = self.client.post(
            reverse("social:publish_draft"),
            {"draft_pk": str(post.pk), "body": "First post",
             "origin": "self_recorded", "licence": "cc_by"},
        )
        self.assertIn(response.status_code, (204, 302))
        post.refresh_from_db()
        sample.refresh_from_db()
        self.assertTrue(post.is_published)
        self.assertTrue(sample.is_committed)
        self.assertEqual(post.body, "First post")

    def test_publish_accepts_unruled_suggestions(self):
        """TC-SOC-011 (S4): suggestions the user neither kept nor removed
        are accepted at publication; explicitly rejected ones stay
        rejected."""
        post, sample = self._draft()
        pending = Tag.objects.create(name="vinyl", kind=Tag.Kind.SUBJECTIVE)
        refused = Tag.objects.create(name="noise", kind=Tag.Kind.SUBJECTIVE)
        keep = SampleTag.objects.create(
            sample=sample, tag=pending,
            source=TagSource.PREDICTED, status=TagStatus.SUGGESTED,
        )
        rejected = SampleTag.objects.create(
            sample=sample, tag=refused,
            source=TagSource.PREDICTED, status=TagStatus.REJECTED,
        )
        self.client.force_login(self.author)
        self.client.post(
            reverse("social:publish_draft"),
            {"draft_pk": str(post.pk), "body": "",
             "origin": "self_recorded", "licence": "cc_by"},
        )
        keep.refresh_from_db()
        rejected.refresh_from_db()
        self.assertEqual(keep.status, TagStatus.ACCEPTED)
        self.assertEqual(rejected.status, TagStatus.REJECTED)

    def test_publish_writes_provenance_onto_sample(self):
        """TC-SOC-013 (U5.1, U5.2): the origin and licence declared in the
        composer are stored on the sample, not the post — they describe the
        recording."""
        post, sample = self._draft()
        self.client.force_login(self.author)
        self.client.post(
            reverse("social:publish_draft"),
            {"draft_pk": str(post.pk), "body": "",
             "origin": "licensed_pack", "licence": "cc_by_nc"},
        )
        sample.refresh_from_db()
        self.assertEqual(sample.origin, Sample.Origin.LICENSED_PACK)
        self.assertEqual(sample.licence, Sample.Licence.CC_BY_NC)

    def test_unknown_origin_is_refused_at_publish(self):
        """TC-SOC-014 (U5.4): a sample declared as unknown or third-party
        origin cannot be posted. The draft and sample survive, so the user
        can still keep it privately."""
        post, sample = self._draft()
        self.client.force_login(self.author)
        response = self.client.post(
            reverse("social:publish_draft"),
            {"draft_pk": str(post.pk), "body": "",
             "origin": "unknown", "licence": "cc_by"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["HX-Retarget"], "#composer-attach")
        self.assertContains(response, "can&#x27;t be posted")
        post.refresh_from_db()
        sample.refresh_from_db()
        self.assertFalse(post.is_published)
        self.assertFalse(sample.is_committed)
        self.assertTrue(Sample.objects.filter(pk=sample.pk).exists())

    def test_publish_without_declaration_is_refused(self):
        """TC-SOC-015 (U5.1): omitting the declaration entirely is a
        validation failure, not a silent default."""
        post, sample = self._draft()
        self.client.force_login(self.author)
        response = self.client.post(
            reverse("social:publish_draft"),
            {"draft_pk": str(post.pk), "body": "no declaration"},
        )
        self.assertEqual(response.status_code, 200)
        post.refresh_from_db()
        self.assertFalse(post.is_published)

    def test_cannot_publish_someone_elses_draft(self):
        """TC-SOC-012: the draft lookup is author-scoped — a 404 for anyone
        else."""
        post, sample = self._draft()
        response = self.client.post(  # logged in as reader
            reverse("social:publish_draft"),
            {"draft_pk": str(post.pk), "body": "hijack"},
        )
        self.assertEqual(response.status_code, 404)
        post.refresh_from_db()
        self.assertFalse(post.is_published)


class DiscardDraftTests(BaseSocialTest):
    """TC-SOC-020..021 — discarding a draft respects sample permanence
    (register: dual-mechanism rationale)."""

    def test_discard_deletes_uncommitted_sample(self):
        """TC-SOC-020: an uncommitted upload dies with its draft."""
        sample = make_sample(self.folder, committed=False)
        Post.objects.create(author=self.author, sample=sample)
        self.client.force_login(self.author)
        self.client.post(reverse("social:discard_draft"))
        self.assertFalse(Sample.objects.filter(pk=sample.pk).exists())
        self.assertFalse(Post.objects.exists())

    def test_discard_keeps_committed_sample(self):
        """TC-SOC-021: a library sample attached to a draft loses only the
        draft — the audio stays committed."""
        sample = make_sample(self.folder, committed=True)
        Post.objects.create(author=self.author, sample=sample)
        self.client.force_login(self.author)
        self.client.post(reverse("social:discard_draft"))
        self.assertTrue(Sample.objects.filter(pk=sample.pk).exists())
        self.assertFalse(Post.objects.exists())


class DeletePostTests(BaseSocialTest):
    """TC-SOC-030..031 — deleting a post never deletes audio."""

    def test_delete_post_leaves_sample(self):
        """TC-SOC-030: removing a published post keeps the sample in the
        library — posts present samples, they don't own them."""
        post = make_published_post(self.author, self.folder)
        sample_pk = post.sample_id
        self.client.force_login(self.author)
        response = self.client.post(
            reverse("social:delete_post", args=[post.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Post.objects.filter(pk=post.pk).exists())
        self.assertTrue(Sample.objects.filter(pk=sample_pk).exists())

    def test_delete_denied_for_non_author(self):
        """TC-SOC-031: only the author can delete their post."""
        post = make_published_post(self.author, self.folder)
        response = self.client.post(  # logged in as reader
            reverse("social:delete_post", args=[post.pk])
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Post.objects.filter(pk=post.pk).exists())


class LikeTests(BaseSocialTest):
    """TC-SOC-040..041 — the like toggle and its uniqueness (U6.7
    reactions)."""

    def test_toggle_creates_then_removes(self):
        """TC-SOC-040: first POST likes, second POST unlikes."""
        post = make_published_post(self.author, self.folder)
        url = reverse("social:toggle_like", args=[post.pk])
        self.client.post(url)
        self.assertEqual(Like.objects.filter(post=post).count(), 1)
        self.client.post(url)
        self.assertEqual(Like.objects.filter(post=post).count(), 0)

    def test_two_users_like_independently(self):
        """TC-SOC-041: likes are per-user; one user's toggle doesn't touch
        another's."""
        post = make_published_post(self.author, self.folder)
        url = reverse("social:toggle_like", args=[post.pk])
        self.client.post(url)
        self.client.force_login(self.author)
        self.client.post(url)
        self.assertEqual(Like.objects.filter(post=post).count(), 2)


class CommentTests(BaseSocialTest):
    """TC-SOC-050..052 — one-level comment threading (U6.7)."""

    def test_add_top_level_comment(self):
        """TC-SOC-050: a comment posts against the post with the author
        set server-side."""
        post = make_published_post(self.author, self.folder)
        self.client.post(
            reverse("social:add_comment", args=[post.pk]),
            {"body": "great break"},
        )
        comment = Comment.objects.get()
        self.assertEqual(comment.author, self.reader)
        self.assertIsNone(comment.parent)

    def test_reply_attaches_to_parent(self):
        """TC-SOC-051: a reply to a top-level comment nests one level."""
        post = make_published_post(self.author, self.folder)
        top = Comment.objects.create(
            post=post, author=self.author, body="nice"
        )
        self.client.post(
            reverse("social:add_comment", args=[post.pk]),
            {"body": "agreed", "parent": str(top.pk)},
        )
        reply = Comment.objects.exclude(pk=top.pk).get()
        self.assertEqual(reply.parent, top)

    def test_reply_to_reply_is_flattened(self):
        """TC-SOC-052: replying to a reply re-attaches to the top-level
        comment — the thread never nests past one level."""
        post = make_published_post(self.author, self.folder)
        top = Comment.objects.create(
            post=post, author=self.author, body="nice"
        )
        reply = Comment.objects.create(
            post=post, author=self.reader, body="agreed", parent=top
        )
        self.client.post(
            reverse("social:add_comment", args=[post.pk]),
            {"body": "same", "parent": str(reply.pk)},
        )
        deepest = Comment.objects.exclude(pk__in=[top.pk, reply.pk]).get()
        self.assertEqual(deepest.parent, top)


class TagFilterTests(BaseSocialTest):
    """TC-SOC-060..061 — repeated ?tag= params narrow with AND semantics
    (U3.1; register: filter state lives in the URL)."""

    def test_single_tag_filters_feed(self):
        """TC-SOC-060: ?tag=drums shows only posts carrying that tag."""
        drums = make_published_post(
            self.author, self.folder, "A", tags=["drums"]
        )
        make_published_post(self.author, self.folder, "B", tags=["synth"])
        response = self.client.get(reverse("social:index"), {"tag": "drums"})
        posts = list(response.context["posts"])
        self.assertEqual(posts, [drums])

    def test_multiple_tags_use_and_semantics(self):
        """TC-SOC-061: two ?tag= params require both tags on one sample —
        co-occurrence narrowing, not union."""
        both = make_published_post(
            self.author, self.folder, "A", tags=["drums", "lo-fi"]
        )
        make_published_post(
            self.author, self.folder, "B", tags=["drums"]
        )
        response = self.client.get(
            reverse("social:index") + "?tag=drums&tag=lo-fi"
        )
        posts = list(response.context["posts"])
        self.assertEqual(posts, [both])