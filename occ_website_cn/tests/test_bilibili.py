from unittest.mock import patch

from markupsafe import Markup

from odoo.addons.html_editor.controllers.main import HTML_Editor
from odoo.addons.http_routing.tests.common import MockRequest
from odoo.addons.html_editor.tools import get_video_url_data
from odoo.tests import TransactionCase, tagged

from ..controllers.html_editor import OccWebsiteCnHtmlEditor
from ..services import (
    get_bilibili_video_url_data,
    is_bilibili_video_input,
    parse_bilibili_video,
)


@tagged("post_install", "-at_install")
class TestBilibiliParser(TransactionCase):
    VALID_INPUTS = {
        "https://www.bilibili.com/video/BV1xx411c7mD": (
            "BV1xx411c7mD",
            1,
        ),
        "https://bilibili.com/video/BV1xx411c7mD?p=2": (
            "BV1xx411c7mD",
            2,
        ),
        "https://m.bilibili.com/video/av170001?page=3": ("170001", 3),
        "av170001": ("170001", 1),
        "av900719925474099312345": ("900719925474099312345", 1),
        "//player.bilibili.com/player.html?bvid=BV1xx411c7mD&page=4": (
            "BV1xx411c7mD",
            4,
        ),
        "https://player.bilibili.com/player.html?aid=170001&p=5": ("170001", 5),
        (
            '<iframe src="https://player.bilibili.com/player.html?'
            'bvid=BV1xx411c7mD&amp;cid=123&amp;page=6&amp;isOutside=true" '
            'scrolling="no" frameborder="0" allowfullscreen></iframe>'
        ): ("BV1xx411c7mD", 6),
        (
            '<iframe src="https://player.bilibili.com/player.html?'
            'aid=170001&amp;bvid=BV1xx411c7mD&amp;cid=123&amp;p=7&amp;isOutside=true" '
            'frameborder="0" allowfullscreen></iframe>'
        ): ("BV1xx411c7mD", 7),
    }

    INVALID_INPUTS = (
        "https://b23.tv/abc123",
        "https://live.bilibili.com/123",
        "https://www.bilibili.com/bangumi/play/ep123",
        "https://www.bilibili.com/cheese/play/ep123",
        "https://player.bilibili.com/player.html?cid=123",
        "https://player.bilibili.com/player.html?bvid=BV1xx411c7mD&autoplay=1",
        "https://player.bilibili.com/player.html?bvid=BV1xx411c7mD&danmaku=0",
        "https://player.bilibili.com/player.html?bvid=BV1xx411c7mD&page=0",
        "https://player.bilibili.com/player.html?bvid=BV1xx411c7mD&page=10001",
        "https://player.bilibili.com/player.html?bvid=BV1xx411c7mD&page=1&p=2",
        "https://player.bilibili.com.evil.example/player.html?bvid=BV1xx411c7mD",
        "https://user@player.bilibili.com/player.html?bvid=BV1xx411c7mD",
        "https://player.bilibili.com:443/player.html?bvid=BV1xx411c7mD",
        "javascript://player.bilibili.com/player.html?bvid=BV1xx411c7mD",
        "https://player.bilibili.com/player.html?bvid=BV1xx411c7mD&",
        "https://www.bilibili.com/video/BV1xx411c7mD?share_source=copy_web",
        '<iframe src="https://player.bilibili.com/player.html?aid=170001" '
        'onload="alert(1)"></iframe>',
        '<iframe src="https://player.bilibili.com/player.html?aid=170001">',
        '<iframe src="https://player.bilibili.com/player.html?aid=170001" '
        'src="https://example.test"></iframe>',
        '<iframe src="https://player.bilibili.com/player.html?aid=170001"></iframe><script>x</script>',
    )

    def test_supported_inputs_are_canonical(self):
        for value, expected in self.VALID_INPUTS.items():
            with self.subTest(value=value):
                video = parse_bilibili_video(value)
                self.assertIsNotNone(video)
                self.assertEqual((video.video_id, video.page), expected)
                self.assertEqual(
                    video.embed_url,
                    "https://player.bilibili.com/player.html?"
                    f"{'bvid' if expected[0].startswith('BV') else 'aid'}={expected[0]}"
                    f"&page={expected[1]}&autoplay=0",
                )

    def test_unsupported_or_unsafe_inputs_are_rejected(self):
        for value in self.INVALID_INPUTS:
            with self.subTest(value=value):
                self.assertIsNone(parse_bilibili_video(value))
                self.assertTrue(is_bilibili_video_input(value))

    def test_url_data_contract_contains_no_arbitrary_parameters(self):
        data = get_bilibili_video_url_data(
            "https://player.bilibili.com/player.html?"
            "bvid=BV1xx411c7mD&cid=123&isOutside=true&page=2"
        )
        self.assertEqual(data["platform"], "bilibili")
        self.assertEqual(data["video_id"], "BV1xx411c7mD")
        self.assertEqual(data["params"], {"page": 2, "autoplay": 0})
        self.assertNotIn("cid", data["embed_url"])
        self.assertNotIn("isOutside", data["embed_url"])

    def test_non_bilibili_iframe_is_not_claimed(self):
        value = '<iframe src="https://player.vimeo.com/video/123"></iframe>'
        self.assertFalse(is_bilibili_video_input(value))
        self.assertIsNone(parse_bilibili_video(value))

    def test_non_bilibili_provider_mentions_are_not_claimed(self):
        values = (
            "https://vimeo.com/123456789?utm_source=bilibili",
            "https://www.youtube.com/watch?v=xCvFZrrQq7k&utm_campaign=bilibili",
            "https://vimeo.com/channels/bilibili/123456789",
        )
        for value in values:
            with self.subTest(value=value):
                self.assertFalse(is_bilibili_video_input(value))
                self.assertIsNone(parse_bilibili_video(value))

    def test_bare_bv_is_rejected_without_claiming_an_upstream_provider(self):
        value = "BV1xx411c7mD"
        self.assertIsNone(parse_bilibili_video(value))
        self.assertFalse(is_bilibili_video_input(value))

    def test_bilibili_does_not_make_remote_requests(self):
        with patch("requests.sessions.Session.request") as request_mock:
            data = get_bilibili_video_url_data(
                "https://www.bilibili.com/video/BV1xx411c7mD"
            )
        self.assertEqual(data["platform"], "bilibili")
        request_mock.assert_not_called()

    def test_default_cookie_watchlist_contains_bilibili(self):
        website = self.env["website"].create({"name": "Bilibili cookie test"})
        domains = website._get_blocked_third_party_domains_list()
        self.assertIn("bilibili.com", domains)
        self.assertIn("media_iframe_video", website._get_blocked_iframe_containers_classes())

    def test_cookie_watchlist_respects_odoo_ignore_default_override(self):
        website = self.env["website"].create(
            {
                "name": "Bilibili cookie override test",
                "custom_blocked_third_party_domains": "#ignore_default\nexample.test",
            }
        )

        self.assertEqual(
            website._get_blocked_third_party_domains_list(),
            ["example.test"],
        )

    def test_html_field_rendering_marks_bilibili_for_optional_consent(self):
        website = self.env["website"].create(
            {
                "name": "Bilibili HTML field cookie test",
                "cookies_bar": True,
                "block_third_party_domains": True,
            }
        )
        html_value = Markup(
            '<div class="occ_bilibili_embedded_video" '
            'data-embedded="video"></div>'
        )
        public_website = website.with_user(website.user_id)
        with MockRequest(
            public_website.env,
            website=public_website,
        ) as request:
            request.is_frontend = True
            request.is_frontend_multilang = True
            rendered = str(
                request.env["ir.qweb.field.html"].value_to_html(html_value, {})
            )
        self.assertIn('data-need-cookies-approval="true"', rendered)

        website.block_third_party_domains = False
        public_website = website.with_user(website.user_id)
        with MockRequest(
            public_website.env,
            website=public_website,
        ) as request:
            request.is_frontend = True
            request.is_frontend_multilang = True
            rendered = str(
                request.env["ir.qweb.field.html"].value_to_html(html_value, {})
            )
        self.assertNotIn("data-need-cookies-approval", rendered)


@tagged("post_install", "-at_install")
class TestBilibiliController(TransactionCase):
    def setUp(self):
        super().setUp()
        self.controller = OccWebsiteCnHtmlEditor()

    def _video_url_data(self, *args, **kwargs):
        """Call the undecorated endpoint outside Odoo's HTTP dispatcher."""
        endpoint = type(self.controller).video_url_data.original_endpoint
        return endpoint(self.controller, *args, **kwargs)

    def test_bilibili_route_result(self):
        data = self._video_url_data(
            "https://www.bilibili.com/video/BV1xx411c7mD?p=2"
        )
        self.assertEqual(data["platform"], "bilibili")
        self.assertEqual(data["params"], {"page": 2, "autoplay": 0})

    def test_bilibili_options_and_background_use_are_rejected(self):
        for option in ("autoplay", "loop", "hide_controls", "hide_fullscreen", "start_from"):
            with self.subTest(option=option):
                data = self._video_url_data(
                    "https://www.bilibili.com/video/BV1xx411c7mD",
                    **{option: True},
                )
                self.assertTrue(data["error"])

    def test_non_bilibili_provider_delegates_to_upstream(self):
        expected = {"platform": "youtube", "embed_url": "upstream"}
        with patch.object(HTML_Editor, "video_url_data", return_value=expected) as upstream:
            result = self._video_url_data(
                "https://www.youtube.com/watch?v=xCvFZrrQq7k",
                autoplay=True,
            )
        self.assertEqual(result, expected)
        upstream.assert_called_once()

    def test_non_bilibili_provider_mentions_delegate_to_upstream(self):
        values = (
            "https://vimeo.com/123456789?utm_source=bilibili",
            "https://www.youtube.com/watch?v=xCvFZrrQq7k&utm_campaign=bilibili",
            "https://vimeo.com/channels/bilibili/123456789",
        )
        expected = {"platform": "upstream", "embed_url": "unchanged"}
        for value in values:
            with self.subTest(value=value), patch.object(
                HTML_Editor,
                "video_url_data",
                return_value=expected,
            ) as upstream:
                self.assertEqual(self._video_url_data(value), expected)
                upstream.assert_called_once()

    def test_upstream_youtube_and_vimeo_results_are_unchanged(self):
        cases = (
            "https://www.youtube.com/watch?v=xCvFZrrQq7k",
            "https://vimeo.com/123456789",
        )
        for video_url in cases:
            with self.subTest(video_url=video_url):
                result = self._video_url_data(video_url)
                self.assertEqual(result, get_video_url_data(video_url))

    def test_vimeo_iframe_delegates_to_upstream(self):
        iframe = '<iframe src="https://player.vimeo.com/video/123"></iframe>'
        expected = {"platform": "vimeo", "embed_url": "upstream"}
        with patch.object(HTML_Editor, "video_url_data", return_value=expected) as upstream:
            result = self._video_url_data(iframe)
        self.assertEqual(result, expected)
        upstream.assert_called_once_with(
            iframe,
            autoplay=False,
            loop=False,
            hide_controls=False,
            hide_fullscreen=False,
            hide_dm_logo=False,
            hide_dm_share=False,
            start_from=False,
        )

    def test_claimed_bilibili_invalid_input_does_not_fall_through(self):
        with patch.object(HTML_Editor, "video_url_data") as upstream:
            result = self._video_url_data("https://b23.tv/not-supported")
        self.assertTrue(result["error"])
        upstream.assert_not_called()
