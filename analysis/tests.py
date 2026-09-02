"""
Test case IDs (TC-ANA-xxx) are referenced by the dissertation's
traceability matrix. Story IDs (Ux.x) reference the requirements document.

Run with:  python manage.py test analysis
"""

import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Library
from library.models import Folder, Sample

from .models import AnalysisStatus, DerivedMetadata, PITCH_CLASSES
from .pipeline import (
    ENHARMONIC,
    KEY_TAG_THRESHOLD,
    estimated_tag_names,
    measured_tag_names,
)

User = get_user_model()

TEMP_MEDIA = tempfile.mkdtemp(prefix="ennizo-test-media-")


def tearDownModule():
    shutil.rmtree(TEMP_MEDIA, ignore_errors=True)


def make_user(username):
    user = User.objects.create_user(username=username, password="pw")
    Library.objects.get_or_create(user=user)
    return user


def make_sample(folder, title="Kick", committed=True, public=False):
    sample = Sample(
        folder=folder, title=title, is_committed=committed, is_public=public
    )
    sample.audio_file.save(
        "test.wav", SimpleUploadedFile("test.wav", b"RIFFfakewavdata"), save=True
    )
    return sample


class EnharmonicTests(TestCase):
    """TC-ANA-001..002 — pipeline-boundary normalisation (U1.2 key
    detection; register: sharps normalised to the flat canonical set)."""

    def test_every_sharp_maps_to_canonical_flat(self):
        """TC-ANA-001: all five sharp spellings Essentia can emit map into
        PITCH_CLASSES — no sharp survives the boundary."""
        expected = {"C#": "Db", "D#": "Eb", "F#": "Gb", "G#": "Ab", "A#": "Bb"}
        self.assertEqual(ENHARMONIC, expected)
        for flat in ENHARMONIC.values():
            self.assertIn(flat, PITCH_CLASSES)

    def test_pitch_classes_are_flat_only(self):
        """TC-ANA-002: the canonical set contains no sharp spellings."""
        self.assertEqual(len(PITCH_CLASSES), 12)
        self.assertFalse(any("#" in name for name in PITCH_CLASSES))


class TagNamingTests(TestCase):
    """TC-ANA-010..014 — deterministic tag naming from a result dict
    (U1.1 BPM, U1.2 key, U1.4 confidence gating)."""

    def test_bpm_tag_rounded_and_gated(self):
        """TC-ANA-010 (U1.1, U1.4): a confident BPM becomes '120bpm'; an
        unconfident one produces no tag."""
        confident = {"bpm": 119.7, "bpm_confidence": 0.8}
        self.assertEqual(estimated_tag_names(confident), [("120bpm", 0.8)])
        unsure = {"bpm": 119.7, "bpm_confidence": 0.2}
        self.assertEqual(estimated_tag_names(unsure), [])

    def test_key_tag_formats_flat_before_lowercasing(self):
        """TC-ANA-011 (U1.2): tonic 10 (Bb) minor renders as 'bflat-minor'.
        The replace('b','flat') must run before .lower(): lowercasing first
        would turn 'Bb' into 'bb' and the tag into 'flatflat'."""
        result = {"tonic": 10, "mode": "minor", "key_confidence": 0.9}
        self.assertEqual(estimated_tag_names(result), [("bflat-minor", 0.9)])

    def test_natural_key_tag_has_no_flat(self):
        """TC-ANA-012 (U1.2): tonic 0 (C) major renders as 'c-major'."""
        result = {"tonic": 0, "mode": "major", "key_confidence": 0.9}
        self.assertEqual(estimated_tag_names(result), [("c-major", 0.9)])

    def test_key_tag_gated_by_threshold(self):
        """TC-ANA-013 (U1.4): a key below KEY_TAG_THRESHOLD yields no tag —
        unreliable estimates are suggestions withheld, not asserted."""
        result = {
            "tonic": 10, "mode": "minor",
            "key_confidence": KEY_TAG_THRESHOLD - 0.01,
        }
        self.assertEqual(estimated_tag_names(result), [])

    def test_measured_tags_from_container_facts(self):
        """TC-ANA-014: duration and channel count are facts, not estimates
        — one-shot (<2s), loop (≤30s), mono."""
        self.assertEqual(
            measured_tag_names({"duration_seconds": 1.5, "channels": 1}),
            ["one-shot", "mono"],
        )
        self.assertEqual(
            measured_tag_names({"duration_seconds": 8.0, "channels": 2}),
            ["loop"],
        )
        self.assertEqual(
            measured_tag_names({"duration_seconds": 120.0, "channels": 2}),
            [],
        )


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class MetadataModelTests(TestCase):
    """TC-ANA-020..026 — DerivedMetadata semantics (U1.5 overrides,
    U3.3/U3.4 audition helpers)."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("owner")
        cls.folder = Folder.objects.create(
            library=cls.owner.library, name="Drums"
        )

    def _meta(self, **fields):
        sample = make_sample(self.folder, title=f"S{DerivedMetadata.objects.count()}")
        DerivedMetadata.objects.filter(sample=sample).update(
            status=AnalysisStatus.COMPLETE, **fields
        )
        return DerivedMetadata.objects.get(sample=sample)

    def test_effective_values_prefer_overrides(self):
        """TC-ANA-020 (U1.5): overrides win; pipeline output survives
        underneath them."""
        meta = self._meta(bpm=90.0, bpm_override=124.0, tonic=6, tonic_override=0)
        self.assertEqual(meta.effective_bpm, 124.0)
        self.assertEqual(meta.effective_tonic, 0)
        self.assertEqual(meta.bpm, 90.0)  # pipeline value preserved
        self.assertTrue(meta.is_corrected)

    def test_key_display_uses_effective_values(self):
        """TC-ANA-021 (U1.2): tonic 10 minor displays as 'Bb minor'."""
        meta = self._meta(tonic=10, mode="minor")
        self.assertEqual(meta.key_display, "Bb minor")

    def test_quality_warnings_are_labelled(self):
        """TC-ANA-025 (U3.9): raised flags map to human-readable labels;
        unraised and unknown flags are dropped."""
        meta = self._meta(
            quality_flags={"clipping": True, "dc_offset": False, "novel": True}
        )
        self.assertEqual(meta.quality_warnings, ["Clipping detected"])

    def test_tonic_range_enforced_by_database(self):
        """TC-ANA-026: the CHECK constraint refuses tonic 12 — pitch classes
        are 0..11 at the database level, not just in Python."""
        sample = make_sample(self.folder, title="Bad")
        with self.assertRaises(IntegrityError), transaction.atomic():
            DerivedMetadata.objects.filter(sample=sample).update(tonic=12)


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class AnalysisWiringTests(TestCase):
    """TC-ANA-030 — the signal-driven invariant surfaced by the library
    suite (finding F2), now encoded."""

    def test_sample_creation_creates_pending_metadata(self):
        """TC-ANA-030: saving a Sample creates its DerivedMetadata row in
        the pending state via the post_save signal."""
        owner = make_user("owner")
        folder = Folder.objects.create(library=owner.library, name="Drums")
        sample = make_sample(folder)
        meta = DerivedMetadata.objects.get(sample=sample)
        self.assertEqual(meta.status, AnalysisStatus.PENDING)


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class AnalysisViewTests(TestCase):
    """TC-ANA-040..044 — visibility and the activity lease
    (U2.7; register: lease touched by page views, never by polls)."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("owner")
        cls.stranger = make_user("stranger")
        cls.folder = Folder.objects.create(
            library=cls.owner.library, name="Drums"
        )

    def test_private_sample_analysis_hidden_from_strangers(self):
        """TC-ANA-040 (U2.7): the analysis page of a private sample is a
        404 for another user — the historical privacy gap, pinned."""
        sample = make_sample(self.folder, public=False)
        client = Client()
        client.force_login(self.stranger)
        response = client.get(
            reverse("analysis:sample_analysis", args=[sample.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_public_sample_analysis_visible_anonymously(self):
        """TC-ANA-041 (U8.2): a public sample's analysis page renders for
        an anonymous visitor."""
        sample = make_sample(self.folder, public=True)
        response = Client().get(
            reverse("analysis:sample_analysis", args=[sample.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_page_view_renews_lease_on_uncommitted_sample(self):
        """TC-ANA-042: opening the analysis page touches last_active_at on
        an uncommitted sample, keeping the reaper at bay."""
        sample = make_sample(self.folder, committed=False)
        old = sample.last_active_at
        client = Client()
        client.force_login(self.owner)
        client.get(reverse("analysis:sample_analysis", args=[sample.pk]))
        sample.refresh_from_db()
        self.assertGreater(sample.last_active_at, old)

    def test_state_poll_does_not_renew_lease(self):
        """TC-ANA-043: the polled fragment never touches the lease — an
        abandoned tab polling forever must not keep its sample alive."""
        sample = make_sample(self.folder, committed=False)
        old = sample.last_active_at
        client = Client()
        client.force_login(self.owner)
        client.get(reverse("analysis:sample_analysis_state", args=[sample.pk]))
        sample.refresh_from_db()
        self.assertEqual(sample.last_active_at, old)

    def test_retry_denied_for_non_owner(self):
        """TC-ANA-044: retrying analysis is owner-only — the ownership
        lookup 404s before any task could be dispatched."""
        sample = make_sample(self.folder)
        client = Client()
        client.force_login(self.stranger)
        response = client.post(
            reverse("analysis:retry_analysis", args=[sample.pk])
        )
        self.assertEqual(response.status_code, 404)