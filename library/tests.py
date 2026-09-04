# library/tests.py
"""
Test case IDs (TC-LIB-xxx) are referenced by the traceability matrix in the
dissertation's Evaluation chapter. Where a test verifies behaviour motivated
by a user story, the story ID (Ux.x) from the requirements document is named

Run with:  python manage.py test library
"""

import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import ProtectedError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Library
from analysis.models import DerivedMetadata
from social.models import Post

from .forms import SampleUploadForm
from .models import (
    Folder,
    Sample,
    SampleTag,
    Tag,
    TagSource,
    TagStatus,
)

User = get_user_model()

# All file writes in this module land in a throwaway directory, torn down in
# tearDownModule, so test runs never touch the real media root.
TEMP_MEDIA = tempfile.mkdtemp(prefix="ennizo-test-media-")


def tearDownModule():
    shutil.rmtree(TEMP_MEDIA, ignore_errors=True)


def make_user(username):
    user = User.objects.create_user(username=username, password="pw")
    # The accounts app creates the Library via a post_save signal; the
    # get_or_create keeps this helper correct even if that wiring changes.
    Library.objects.get_or_create(user=user)
    return user


def make_sample(folder, title="Kick", committed=True, public=False, **kwargs):
    sample = Sample(
        folder=folder,
        title=title,
        is_committed=committed,
        is_public=public,
        **kwargs,
    )
    sample.audio_file.save(
        "test.wav", SimpleUploadedFile("test.wav", b"RIFFfakewavdata"), save=True
    )
    return sample


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class BaseLibraryTest(TestCase):
    """Common fixture: two users, each with a library and one folder."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = make_user("alice")
        cls.bob = make_user("bob")
        cls.alice_folder = Folder.objects.create(
            library=cls.alice.library, name="Drums"
        )
        cls.bob_folder = Folder.objects.create(
            library=cls.bob.library, name="Synths"
        )


class SampleVisibilityTests(BaseLibraryTest):
    """TC-LIB-001..004 — visibility queryset (U2.7 private-by-default,
    U8.3 account boundaries)."""

    def test_private_sample_hidden_from_other_users(self):
        """TC-LIB-001 (U2.7): a non-public sample is invisible to others."""
        sample = make_sample(self.alice_folder, public=False)
        visible = Sample.objects.visible_to(self.bob)
        self.assertNotIn(sample, visible)

    def test_private_sample_visible_to_owner(self):
        """TC-LIB-002 (U2.7): the owner always sees their own samples."""
        sample = make_sample(self.alice_folder, public=False)
        self.assertIn(sample, Sample.objects.visible_to(self.alice))

    def test_public_sample_visible_to_everyone(self):
        """TC-LIB-003 (U2.7): marking public shares the sample."""
        sample = make_sample(self.alice_folder, public=True)
        self.assertIn(sample, Sample.objects.visible_to(self.bob))

    def test_anonymous_viewer_sees_only_public(self):
        """TC-LIB-004 (U8.2): unauthenticated visitors see public samples
        only."""
        from django.contrib.auth.models import AnonymousUser

        private = make_sample(self.alice_folder, public=False)
        public = make_sample(self.alice_folder, title="Snare", public=True)
        visible = Sample.objects.visible_to(AnonymousUser())
        self.assertIn(public, visible)
        self.assertNotIn(private, visible)


class MetadataFilterTests(BaseLibraryTest):
    """TC-LIB-010..012 — BPM/key filtering honours user overrides
    (U3.1 filter by BPM/key, U1.5 human override wins)."""

    def _sample_with_meta(self, title, **meta):
        # The analysis app creates the DerivedMetadata row via a post_save
        # signal on Sample, so the one-to-one already exists — update it
        # rather than inserting a duplicate.
        sample = make_sample(self.alice_folder, title=title)
        DerivedMetadata.objects.update_or_create(
            sample=sample, defaults={"status": "complete", **meta}
        )
        return sample


    def test_in_key_honours_tonic_override(self):
        """TC-LIB-012 (U1.5, U3.1): key filtering also coalesces overrides."""
        # tonic 6 = Gb in PITCH_CLASSES; override moved it to 0 = C.
        corrected = self._sample_with_meta(
            "D", tonic=6, mode="minor", tonic_override=0
        )
        self.assertIn(corrected, Sample.objects.in_key(0))
        self.assertNotIn(corrected, Sample.objects.in_key(6))


class TagQuerySetTests(BaseLibraryTest):
    """TC-LIB-020..021 — only human-accepted tags are searchable
    (S4 human authority; U1.4/U1.6 suggestions await a ruling)."""

    def test_suggested_tags_are_not_searchable(self):
        """TC-LIB-020 (S4): a machine suggestion must not surface the sample
        in tag search until the user accepts it."""
        sample = make_sample(self.alice_folder)
        tag = Tag.objects.create(name="breakbeat", kind=Tag.Kind.SUBJECTIVE)
        link = SampleTag.objects.create(
            sample=sample,
            tag=tag,
            source=TagSource.PREDICTED,
            status=TagStatus.SUGGESTED,
        )
        self.assertNotIn(sample, Sample.objects.tagged("breakbeat"))

        link.accept()
        self.assertIn(sample, Sample.objects.tagged("breakbeat"))

    def test_rejected_tags_are_not_searchable(self):
        """TC-LIB-021 (S4): rejecting a suggestion removes it from search
        while preserving the row as provenance."""
        sample = make_sample(self.alice_folder)
        tag = Tag.objects.create(name="lo-fi", kind=Tag.Kind.SUBJECTIVE)
        link = SampleTag.objects.create(
            sample=sample, tag=tag, source=TagSource.PREDICTED
        )
        link.reject()
        self.assertNotIn(sample, Sample.objects.tagged("lo-fi"))
        # Provenance survives the rejection.
        link.refresh_from_db()
        self.assertEqual(link.source, TagSource.PREDICTED)
        self.assertIsNotNone(link.resolved_at)


class SampleLifecycleTests(BaseLibraryTest):
    """TC-LIB-030..034 — the single teardown path and post protection
    (U7.2 originals preserved; register: provisional state lives on the
    sample, not the post)."""

    def test_delete_removes_audio_file_from_storage(self):
        """TC-LIB-030: deleting the row deletes the file (post_delete
        signal)."""
        sample = make_sample(self.alice_folder)
        storage, name = sample.audio_file.storage, sample.audio_file.name
        self.assertTrue(storage.exists(name))
        sample.delete()
        self.assertFalse(storage.exists(name))

    def test_delete_tears_down_draft_post(self):
        """TC-LIB-031: a draft post is provisional state riding on the sample
        and goes with it."""
        sample = make_sample(self.alice_folder, committed=False)
        Post.objects.create(author=self.alice, sample=sample)
        sample.delete()
        self.assertFalse(Post.objects.filter(author=self.alice).exists())

    def test_published_post_blocks_sample_delete(self):
        """TC-LIB-032: PROTECT fires for published posts — audio in the feed
        cannot be deleted out from under readers."""
        sample = make_sample(self.alice_folder)
        post = Post.objects.create(author=self.alice, sample=sample)
        post.publish()
        with self.assertRaises(ProtectedError):
            sample.delete()

    def test_post_delete_leaves_sample_intact(self):
        """TC-LIB-033: removing a post never removes the audio — the sample
        belongs to the library, the post merely presents it."""
        sample = make_sample(self.alice_folder)
        post = Post.objects.create(author=self.alice, sample=sample)
        post.delete()
        self.assertTrue(Sample.objects.filter(pk=sample.pk).exists())

    def test_discard_never_deletes_committed_samples(self):
        """TC-LIB-034: discard() is safety-netted on is_committed — whatever
        queryset the caller passes, committed samples survive."""
        committed = make_sample(self.alice_folder, title="Keep")
        uncommitted = make_sample(
            self.alice_folder, title="Toss", committed=False
        )
        count = Sample.objects.all().discard()
        self.assertEqual(count, 1)
        self.assertTrue(Sample.objects.filter(pk=committed.pk).exists())
        self.assertFalse(Sample.objects.filter(pk=uncommitted.pk).exists())


class ReaperTests(BaseLibraryTest):
    """TC-LIB-040..042 — the abandoned-sample reaper and its activity lease
    (register: reap on last_active_at, not created_at)."""

    def _age(self, sample, minutes):
        Sample.objects.filter(pk=sample.pk).update(
            last_active_at=timezone.now() - timedelta(minutes=minutes)
        )

    def test_stale_uncommitted_sample_is_reaped(self):
        """TC-LIB-040: uncommitted and inactive past the lease → deleted."""
        sample = make_sample(self.alice_folder, committed=False)
        self._age(sample, minutes=45)
        reaped = Sample.objects.reap_uncommitted(older_than_minutes=30)
        self.assertEqual(reaped, 1)
        self.assertFalse(Sample.objects.filter(pk=sample.pk).exists())

    def test_active_uncommitted_sample_survives(self):
        """TC-LIB-041: recent activity renews the lease — a long editing
        session must not have its sample expire underneath it."""
        sample = make_sample(self.alice_folder, committed=False)
        self._age(sample, minutes=10)
        reaped = Sample.objects.reap_uncommitted(older_than_minutes=30)
        self.assertEqual(reaped, 0)
        self.assertTrue(Sample.objects.filter(pk=sample.pk).exists())

    def test_stale_committed_sample_is_never_reaped(self):
        """TC-LIB-042: committed samples are permanent regardless of age."""
        sample = make_sample(self.alice_folder, committed=True)
        self._age(sample, minutes=10_000)
        reaped = Sample.objects.reap_uncommitted(older_than_minutes=30)
        self.assertEqual(reaped, 0)
        self.assertTrue(Sample.objects.filter(pk=sample.pk).exists())


class FolderViewTests(BaseLibraryTest):
    """TC-LIB-050..052 — folder listing counts and ownership (U2.5)."""

    def test_folder_counts_exclude_uncommitted(self):
        """TC-LIB-050: the library page counts committed samples only —
        in-flight renders and drafts don't inflate folder badges."""
        make_sample(self.alice_folder, committed=True)
        make_sample(self.alice_folder, title="Draft", committed=False)
        client = Client()
        client.force_login(self.alice)
        response = client.get(reverse("library:index"))
        folder = next(
            f for f in response.context["folders"] if f.pk == self.alice_folder.pk
        )
        self.assertEqual(folder.sample_count, 1)

    def test_folder_samples_hides_uncommitted(self):
        """TC-LIB-051: the folder contents partial lists committed samples
        only."""
        shown = make_sample(self.alice_folder)
        hidden = make_sample(self.alice_folder, title="Draft", committed=False)
        client = Client()
        client.force_login(self.alice)
        response = client.get(
            reverse("library:folder_samples", args=[self.alice_folder.pk])
        )
        samples = list(response.context["samples"])
        self.assertIn(shown, samples)
        self.assertNotIn(hidden, samples)

    def test_folder_samples_denies_other_users(self):
        """TC-LIB-052 (U8.3): another user's folder is a 404, not a 403 —
        its existence is not confirmed."""
        client = Client()
        client.force_login(self.bob)
        response = client.get(
            reverse("library:folder_samples", args=[self.alice_folder.pk])
        )
        self.assertEqual(response.status_code, 404)


class SampleActionViewTests(BaseLibraryTest):
    """TC-LIB-060..065 — commit, discard, delete: ownership and state
    guards (S4; register: is_committed drives the action bar)."""

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.alice)

    def test_commit_sets_flag(self):
        """TC-LIB-060: Save-to-library marks the sample permanent."""
        sample = make_sample(self.alice_folder, committed=False)
        self.client.post(reverse("library:commit_sample", args=[sample.pk]))
        sample.refresh_from_db()
        self.assertTrue(sample.is_committed)

    def test_commit_denied_for_other_users(self):
        """TC-LIB-061: only the owner can commit — 404 for anyone else."""
        sample = make_sample(self.bob_folder, committed=False)
        response = self.client.post(
            reverse("library:commit_sample", args=[sample.pk])
        )
        self.assertEqual(response.status_code, 404)
        sample.refresh_from_db()
        self.assertFalse(sample.is_committed)

    def test_discard_deletes_uncommitted_sample(self):
        """TC-LIB-062: discard removes the sample and its file."""
        sample = make_sample(self.alice_folder, committed=False)
        response = self.client.post(
            reverse("library:discard_sample", args=[sample.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Sample.objects.filter(pk=sample.pk).exists())

    def test_discard_refuses_committed_sample(self):
        """TC-LIB-063: a committed sample cannot be discarded through the
        provisional-state route — the guard is in the URL lookup itself."""
        sample = make_sample(self.alice_folder, committed=True)
        response = self.client.post(
            reverse("library:discard_sample", args=[sample.pk])
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Sample.objects.filter(pk=sample.pk).exists())

    def test_discard_denied_for_other_users(self):
        """TC-LIB-064: discarding someone else's draft is a 404."""
        sample = make_sample(self.bob_folder, committed=False)
        response = self.client.post(
            reverse("library:discard_sample", args=[sample.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_delete_of_posted_sample_shows_friendly_error(self):
        """TC-LIB-065: the ProtectedError from a published post surfaces as
        a message, not a 500."""
        sample = make_sample(self.alice_folder)
        post = Post.objects.create(author=self.alice, sample=sample)
        post.publish()
        response = self.client.post(
            reverse("library:delete_sample", args=[sample.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Sample.objects.filter(pk=sample.pk).exists())


class DraftTagViewTests(BaseLibraryTest):
    """TC-LIB-070..073 — the tag review panel (U2.2 subjective tags,
    U2.3 tag cap, S4 accept/reject)."""

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.alice)
        self.sample = make_sample(self.alice_folder)
        self.url = reverse("library:draft_tags", args=[self.sample.pk])

    def test_add_creates_accepted_user_tag(self):
        """TC-LIB-070 (U2.2): a typed tag is stored lowercased, sourced to
        the user, and immediately accepted."""
        self.client.post(self.url, {"action": "add", "tag_name": "  DUSTY  "})
        link = SampleTag.objects.get(sample=self.sample)
        self.assertEqual(link.tag.name, "dusty")
        self.assertEqual(link.source, TagSource.USER)
        self.assertEqual(link.status, TagStatus.ACCEPTED)

    def test_tag_cap_enforced_at_ten(self):
        """TC-LIB-071 (U2.3): the eleventh accepted tag is refused."""
        for i in range(10):
            tag = Tag.objects.create(name=f"tag{i}", kind=Tag.Kind.SUBJECTIVE)
            SampleTag.objects.create(
                sample=self.sample, tag=tag, source=TagSource.USER
            )
        self.client.post(self.url, {"action": "add", "tag_name": "eleventh"})
        self.assertEqual(
            SampleTag.objects.filter(sample=self.sample).count(), 10
        )

    def test_keep_accepts_a_suggestion(self):
        """TC-LIB-072 (S4, U1.6): 'keep' promotes a machine suggestion."""
        tag = Tag.objects.create(name="vinyl", kind=Tag.Kind.SUBJECTIVE)
        link = SampleTag.objects.create(
            sample=self.sample,
            tag=tag,
            source=TagSource.PREDICTED,
            status=TagStatus.SUGGESTED,
        )
        self.client.post(self.url, {"action": "keep", "tag_pk": str(link.pk)})
        link.refresh_from_db()
        self.assertEqual(link.status, TagStatus.ACCEPTED)

    def test_panel_denied_for_other_users(self):
        """TC-LIB-073: tag review is owner-only — 404 for anyone else."""
        self.client.force_login(self.bob)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)


class UploadFormTests(BaseLibraryTest):
    """TC-LIB-080..083 — upload validation (U1.8 formats, U2.3 tag cap)."""

    def _form(self, filename="loop.wav", tags="", title=""):
        return SampleUploadForm(
            data={
                "title": title,
                "tags": tags,
                "folder": self.alice_folder.pk,
                "note": "",
            },
            files={
                "audio_file": SimpleUploadedFile(filename, b"RIFFfakewavdata")
            },
            user=self.alice,
        )

    def test_disallowed_extension_rejected(self):
        """TC-LIB-080 (U1.8): non-audio uploads are refused at the form."""
        form = self._form(filename="malware.exe")
        self.assertFalse(form.is_valid())
        self.assertIn("audio_file", form.errors)

    def test_wav_accepted(self):
        """TC-LIB-081 (U1.8): a WAV passes validation."""
        self.assertTrue(self._form().is_valid())

    def test_title_defaults_to_filename_stem(self):
        """TC-LIB-082: an empty title falls back to the filename."""
        form = self._form(filename="amen_break.wav", title="")
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["title"], "amen_break")

    def test_tags_parsed_deduplicated_and_capped(self):
        """TC-LIB-083 (U2.3): tags are split, lowercased, deduplicated, and
        capped at ten."""
        form = self._form(tags="Drums, drums , lo-fi")
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["tags"], ["drums", "lo-fi"])

        eleven = ", ".join(f"t{i}" for i in range(11))
        form = self._form(tags=eleven)
        self.assertFalse(form.is_valid())


class SearchTests(BaseLibraryTest):
    """TC-LIB-090 — full-text search (U3.8). Requires PostgreSQL, which is
    the project's only supported database."""

    def test_search_matches_title_and_not_unrelated(self):
        """TC-LIB-090 (U3.8): a title term finds the sample; an unrelated
        sample does not appear."""
        hit = make_sample(self.alice_folder, title="dusty amen break")
        miss = make_sample(self.alice_folder, title="clean synth stab")
        results = list(Sample.objects.search("amen"))
        self.assertIn(hit, results)
        self.assertNotIn(miss, results)
