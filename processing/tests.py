
"""
- The DSP chain (pedalboard, pyloudnorm, the biquad EQ) is covered
  by manual listening tests, and criteria for correctness
  is perceptual.


Test case IDs (TC-PRO-xxx) are referenced by the dissertation's
traceability matrix. Story IDs (Ux.x) reference the requirements document.

Run with:  python manage.py test processing
"""

import json
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Library
from library.models import Folder, Sample

User = get_user_model()

TEMP_MEDIA = tempfile.mkdtemp(prefix="ennizo-test-media-")


def tearDownModule():
    shutil.rmtree(TEMP_MEDIA, ignore_errors=True)


def make_user(username):
    user = User.objects.create_user(username=username, password="pw")
    Library.objects.get_or_create(user=user)
    return user


def make_sample(folder, title="Kick", committed=True, **kwargs):
    sample = Sample(folder=folder, title=title, is_committed=committed, **kwargs)
    sample.audio_file.save(
        "test.wav", SimpleUploadedFile("test.wav", b"RIFFfakewavdata"), save=True
    )
    return sample


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class BaseProcessingTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("owner")
        cls.stranger = make_user("stranger")
        cls.folder = Folder.objects.create(
            library=cls.owner.library, name="Drums"
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.owner)
        self.sample = make_sample(self.folder)

    def _render(self, payload, client=None):
        return (client or self.client).post(
            reverse("processing:render_sample", args=[self.sample.pk]),
            data=json.dumps(payload),
            content_type="application/json",
        )


class AccessControlTests(BaseProcessingTest):
    """TC-PRO-001..004 — the editor is owner-only (U8.3; finding F5)."""

    def test_edit_page_denied_for_non_owner(self):
        """TC-PRO-001: another user's sample cannot be opened in the
        editor — 404."""
        client = Client()
        client.force_login(self.stranger)
        response = client.get(
            reverse("processing:edit_sample", args=[self.sample.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_render_denied_for_non_owner(self):
        """TC-PRO-002: a render request against someone else's sample is a
        404 before any parameters are read."""
        client = Client()
        client.force_login(self.stranger)
        response = self._render({"normalise": True}, client=client)
        self.assertEqual(response.status_code, 404)

    def test_anonymous_user_redirected_to_login(self):
        """TC-PRO-003 (F5): unauthenticated requests to the editor redirect
        to login rather than erroring."""
        response = Client().get(
            reverse("processing:edit_sample", args=[self.sample.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_anonymous_render_redirected_to_login(self):
        """TC-PRO-004 (F5): the render endpoint likewise requires login."""
        response = Client().post(
            reverse("processing:render_sample", args=[self.sample.pk]),
            data=json.dumps({"normalise": True}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 302)


class RenderValidationTests(BaseProcessingTest):
    """TC-PRO-010..015 — server-side parameter validation (S4: the server
    re-checks everything the client sends; U7.1 previewable processing)."""

    def test_invalid_json_rejected(self):
        """TC-PRO-010: a malformed body is a 400, not an exception."""
        response = self.client.post(
            reverse("processing:render_sample", args=[self.sample.pk]),
            data="{not json",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_trim_must_be_ordered_and_non_negative(self):
        """TC-PRO-011: trim_end must exceed trim_start; negatives are
        refused."""
        self.assertEqual(
            self._render({"trim_start": 2.0, "trim_end": 1.0}).status_code, 400
        )
        self.assertEqual(
            self._render({"trim_start": -1.0, "trim_end": 1.0}).status_code, 400
        )

    def test_gains_must_be_eight_bands(self):
        """TC-PRO-012: the EQ contract is exactly eight bands."""
        self.assertEqual(self._render({"gains": [0.0] * 7}).status_code, 400)
        self.assertEqual(self._render({"gains": [0.0] * 9}).status_code, 400)

    def test_gains_bounded_to_plus_minus_twelve(self):
        """TC-PRO-013: a 13 dB boost is refused — limits enforced
        server-side, not just by the sliders."""
        gains = [0.0] * 7 + [13.0]
        self.assertEqual(self._render({"gains": gains}).status_code, 400)

    def test_boolean_flags_must_be_boolean(self):
        """TC-PRO-014: 'yes' is not True — type-checked flags."""
        self.assertEqual(
            self._render({"normalise": "yes"}).status_code, 400
        )

    def test_valid_request_accepted(self):
        """TC-PRO-015 (U7.1): a well-formed request is acknowledged with
        the polling cursor. (Dispatch rides on transaction.on_commit, which
        does not fire under TestCase — deliberately, so no broker or DSP is
        needed here.)"""
        response = self._render({
            "trim_start": 0.5,
            "trim_end": 2.0,
            "gains": [0.0, 1.5, -3.0, 0.0, 0.0, 2.0, 0.0, -1.0],
            "tame_peaks": True,
            "normalise": True,
            "preview": True,
        })
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertIn("after", body)


class RenderStatusTests(BaseProcessingTest):
    """TC-PRO-020..022 — the render poll and its cursor (U7.1 A/B
    preview; register: renders are uncommitted samples)."""

    def _make_render(self):
        return make_sample(
            self.folder,
            title="Render",
            committed=False,
            rendered_from=self.sample,
        )

    def test_no_renders_reports_not_done(self):
        """TC-PRO-020: polling before any render exists returns done:false."""
        response = self.client.get(
            reverse("processing:render_status", args=[self.sample.pk])
        )
        self.assertEqual(response.json(), {"done": False})

    def test_completed_render_reported_with_url(self):
        """TC-PRO-021: once a render exists the poll returns its pk and
        audio URL for the A/B player."""
        render = self._make_render()
        response = self.client.get(
            reverse("processing:render_status", args=[self.sample.pk])
        )
        body = response.json()
        self.assertTrue(body["done"])
        self.assertEqual(body["render_pk"], render.pk)
        self.assertIn("url", body)

    def test_after_cursor_ignores_stale_renders(self):
        """TC-PRO-022: passing ?after=<pk> hides renders up to that pk, so
        the client only ever hears about the render it asked for."""
        first = self._make_render()
        response = self.client.get(
            reverse("processing:render_status", args=[self.sample.pk]),
            {"after": str(first.pk)},
        )
        self.assertEqual(response.json(), {"done": False})
        second = self._make_render()
        response = self.client.get(
            reverse("processing:render_status", args=[self.sample.pk]),
            {"after": str(first.pk)},
        )
        self.assertEqual(response.json()["render_pk"], second.pk)



