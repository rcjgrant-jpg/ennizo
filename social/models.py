# social/models.py
from django.conf import settings
from django.db import models
from django.db.models import Q
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

    def stale_drafts(self, older_than_days=7):
        cutoff = timezone.now() - timezone.timedelta(days=older_than_days)
        return self.filter(is_published=False, created_at__lt=cutoff)

    def discard(self):
        """Delete these drafts together with their samples and audio files.

        A draft Post and its Sample exist only so that analysis can run while
        the caption is being written. If the composer is abandoned, neither was
        ever filed deliberately, so both are removed. Post.sample is PROTECT,
        which is correct for published posts, so the post must go first.
        """
        count = 0
        for post in self.filter(is_published=False).select_related("sample"):
            sample = post.sample
            post.delete()
            if sample.audio_file:
                # Django does not remove the file when the row goes.
                sample.audio_file.delete(save=False)
            sample.delete()
            count += 1
        return count


class Post(models.Model):
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="posts",
    )
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