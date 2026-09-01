"""
Test case IDs (TC-ATT-xxx) are referenced by the dissertation's
traceability matrix. Story IDs (Ux.x) reference the requirements document.

Run with:  python manage.py test attribution
"""

import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Library
from library.models import Folder, Sample
from social.models import Post

from .forms import CreditForm
from .models import CreditRecord, DownloadRecord

User = get_user_model()

TEMP_MEDIA = tempfile.mkdtemp(prefix="ennizo-test-media-")


def tearDownModule():
    shutil.rmtree(TEMP_MEDIA, ignore_errors=True)


def make_user(username):
    user = User.objects.create_user(username=username, password="pw")
    Library.objects.get_or_create(user=user)
    return user


def make_sample(folder, title="Kick", public=False, committed=True):
    sample = Sample(
        folder=folder, title=title, is_public=public, is_committed=committed
    )
    sample.audio_file.save(
        "test.wav", SimpleUploadedFile("test.wav", b"RIFFfakewavdata"), save=True
    )
    return sample


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class BaseAttributionTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("owner")
        cls.visitor = make_user("visitor")
        cls.folder = Folder.objects.create(
            library=cls.owner.library, name="Drums"
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.visitor)


class DownloadEligibilityTests(BaseAttributionTest):
    """TC-ATT-001..005 — who may fetch a sample (U2.7 private-by-default,
    U4.1 WAV download, register: eligibility = owner OR public OR posted)."""

    def test_private_sample_not_downloadable_by_others(self):
        """TC-ATT-001 (U2.7): a private, unposted sample is a 404 for anyone
        but the owner — existence is not confirmed."""
        sample = make_sample(self.folder, public=False)
        response = self.client.get(
            reverse("attribution:download_sample", args=[sample.pk])
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(DownloadRecord.objects.exists())

    def test_public_sample_downloadable(self):
        """TC-ATT-002 (U4.1): a public sample downloads as an attachment
        with a human-readable filename, not the stored UUID."""
        sample = make_sample(self.folder, title="Dusty Break", public=True)
        response = self.client.get(
            reverse("attribution:download_sample", args=[sample.pk])
        )
        self.assertEqual(response.status_code, 200)
        disposition = response.headers["Content-Disposition"]
        self.assertIn("attachment", disposition)
        self.assertIn("dusty-break.wav", disposition)

    def test_posted_sample_downloadable_even_if_private(self):
        """TC-ATT-003: a published post makes its sample fetchable —
        publishing already exposed the audio for streaming, so download
        widens nothing."""
        sample = make_sample(self.folder, public=False)
        post = Post.objects.create(author=self.owner, sample=sample)
        post.publish()
        response = self.client.get(
            reverse("attribution:download_sample", args=[sample.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_draft_post_does_not_expose_sample(self):
        """TC-ATT-004: a draft post is provisional and confers no access."""
        sample = make_sample(self.folder, public=False)
        Post.objects.create(author=self.owner, sample=sample)  # unpublished
        response = self.client.get(
            reverse("attribution:download_sample", args=[sample.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_anonymous_download_requires_login(self):
        """TC-ATT-005 (U8.3): downloading requires an account — anonymous
        requests are redirected to login."""
        sample = make_sample(self.folder, public=True)
        response = Client().get(
            reverse("attribution:download_sample", args=[sample.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])


class DownloadRecordTests(BaseAttributionTest):
    """TC-ATT-010..012 — the count means people, not clicks (U6.1;
    register: unique (downloader, sample), owner downloads unrecorded)."""

    def test_repeat_downloads_create_one_record(self):
        """TC-ATT-010 (U6.1): fetching a sample three times leaves one
        DownloadRecord — the count reads 'how many people have this'."""
        sample = make_sample(self.folder, public=True)
        url = reverse("attribution:download_sample", args=[sample.pk])
        for _ in range(3):
            self.client.get(url)
        self.assertEqual(
            DownloadRecord.objects.filter(sample=sample).count(), 1
        )

    def test_owner_download_is_not_recorded(self):
        """TC-ATT-011 (U6.1): the owner fetching their own file is allowed
        but counts for no one."""
        sample = make_sample(self.folder, public=True)
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("attribution:download_sample", args=[sample.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(DownloadRecord.objects.exists())

    def test_distinct_users_create_distinct_records(self):
        """TC-ATT-012 (U6.1): two different downloaders → two records."""
        sample = make_sample(self.folder, public=True)
        url = reverse("attribution:download_sample", args=[sample.pk])
        self.client.get(url)
        second = make_user("second")
        self.client.force_login(second)
        self.client.get(url)
        self.assertEqual(
            DownloadRecord.objects.filter(sample=sample).count(), 2
        )


class CreditFormTests(BaseAttributionTest):
    """TC-ATT-020..023 — platform/URL agreement (U6.3 credit a track back
    to its samples)."""

    def _form(self, platform, url):
        return CreditForm(
            data={
                "platform": platform,
                "track_title": "My Track",
                "track_url": url,
            }
        )

    def test_matching_platform_and_host_accepted(self):
        """TC-ATT-020 (U6.3): a Spotify link under the Spotify platform is
        valid."""
        form = self._form("spotify", "https://open.spotify.com/track/abc123")
        self.assertTrue(form.is_valid())

    def test_mismatched_platform_rejected(self):
        """TC-ATT-021 (U6.3): a SoundCloud link submitted as Spotify is
        refused with a field error."""
        form = self._form("spotify", "https://soundcloud.com/artist/track")
        self.assertFalse(form.is_valid())
        self.assertIn("track_url", form.errors)

    def test_lookalike_host_rejected(self):
        """TC-ATT-022: exact-host matching defeats suffix spoofing —
        evil-spotify.com is not open.spotify.com."""
        form = self._form("spotify", "https://evil-spotify.com/track/abc")
        self.assertFalse(form.is_valid())

    def test_www_prefix_normalised(self):
        """TC-ATT-023: www.soundcloud.com is treated as soundcloud.com."""
        form = self._form(
            "soundcloud", "https://www.soundcloud.com/artist/track"
        )
        self.assertTrue(form.is_valid())


class AddCreditViewTests(BaseAttributionTest):
    """TC-ATT-030..032 — crediting is tied to your own download
    (U6.3; register: credit keyed to creditor+sample, repeats allowed)."""

    def _download(self, sample, user):
        return DownloadRecord.objects.create(downloader=user, sample=sample)

    def test_credit_created_against_own_download(self):
        """TC-ATT-030 (U6.3): a valid submission creates the credit for the
        logged-in user against the record's sample."""
        sample = make_sample(self.folder, public=True)
        record = self._download(sample, self.visitor)
        response = self.client.post(
            reverse("attribution:add_credit", args=[record.pk]),
            {
                "platform": "spotify",
                "track_title": "My Track",
                "track_url": "https://open.spotify.com/track/abc",
            },
        )
        self.assertEqual(response.status_code, 200)
        credit = CreditRecord.objects.get()
        self.assertEqual(credit.creditor, self.visitor)
        self.assertEqual(credit.sample, sample)

    def test_cannot_credit_someone_elses_download(self):
        """TC-ATT-031: another user's DownloadRecord is a 404 — credits
        hang off your own download history only."""
        sample = make_sample(self.folder, public=True)
        other = make_user("other")
        record = self._download(sample, other)
        response = self.client.post(
            reverse("attribution:add_credit", args=[record.pk]),
            {
                "platform": "spotify",
                "track_title": "My Track",
                "track_url": "https://open.spotify.com/track/abc",
            },
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(CreditRecord.objects.exists())

    def test_multiple_credits_for_same_sample_allowed(self):
        """TC-ATT-032 (U6.3): one sample used in two tracks yields two
        credits — no uniqueness on (creditor, sample) by design."""
        sample = make_sample(self.folder, public=True)
        record = self._download(sample, self.visitor)
        url = reverse("attribution:add_credit", args=[record.pk])
        for title, link in [
            ("Track One", "https://open.spotify.com/track/one"),
            ("Track Two", "https://open.spotify.com/track/two"),
        ]:
            self.client.post(url, {
                "platform": "spotify",
                "track_title": title,
                "track_url": link,
            })
        self.assertEqual(
            CreditRecord.objects.filter(
                creditor=self.visitor, sample=sample
            ).count(),
            2,
        )