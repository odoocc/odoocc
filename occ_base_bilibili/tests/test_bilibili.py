from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from ..services import (
    BilibiliVideo,
    get_bilibili_video_url_data,
    is_bilibili_video_input,
    parse_bilibili_video,
)


@tagged("occ_base_bilibili", "post_install", "-at_install")
class TestBilibiliParser(TransactionCase):
    def test_supported_inputs_are_canonical(self):
        cases = {
            "https://www.bilibili.com/video/BV1xx411c7mD": ("BV1xx411c7mD", 1),
            "https://m.bilibili.com/video/av170001?page=3": ("170001", 3),
            "av170001": ("170001", 1),
            "//player.bilibili.com/player.html?bvid=BV1xx411c7mD&page=4": (
                "BV1xx411c7mD",
                4,
            ),
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                video = parse_bilibili_video(value)
                self.assertEqual((video.video_id, video.page), expected)
                self.assertEqual(
                    video.as_video_url_data()["params"],
                    {"page": expected[1], "autoplay": 0},
                )

    def test_bare_bv_requires_explicit_permission(self):
        self.assertIsNone(parse_bilibili_video("BV1xx411c7mD"))
        self.assertFalse(is_bilibili_video_input("BV1xx411c7mD"))
        self.assertTrue(
            is_bilibili_video_input("BV1xx411c7mD", allow_bare_bvid=True)
        )
        video = parse_bilibili_video("BV1xx411c7mD", allow_bare_bvid=True)
        self.assertEqual(video.video_id, "BV1xx411c7mD")

    def test_video_value_object_rejects_invalid_data(self):
        for values in (
            {"video_id": "javascript:alert(1)"},
            {"video_id": "170001", "page": 0},
            {"video_id": "170001", "page": True},
            {"video_id": "170001", "page": 10001},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                BilibiliVideo(**values)

    def test_unsafe_inputs_are_rejected_and_claimed(self):
        values = (
            "https://b23.tv/abc123",
            "https://live.bilibili.com/123",
            "https://player.bilibili.com.evil.example/player.html?aid=1",
            "javascript://player.bilibili.com/player.html?aid=1",
            "https://player.bilibili.com/player.html?bvid=BV1xx411c7mD&autoplay=1",
            '<iframe src="https://player.bilibili.com/player.html?aid=1" '
            'onload="alert(1)"></iframe>',
        )
        for value in values:
            with self.subTest(value=value):
                self.assertIsNone(parse_bilibili_video(value))
                self.assertTrue(is_bilibili_video_input(value))

    def test_non_bilibili_values_are_not_claimed(self):
        values = (
            "https://www.youtube.com/watch?v=xCvFZrrQq7k&utm_campaign=bilibili",
            '<iframe src="https://player.vimeo.com/video/123"></iframe>',
        )
        for value in values:
            with self.subTest(value=value):
                self.assertIsNone(parse_bilibili_video(value))
                self.assertFalse(is_bilibili_video_input(value))

    def test_parser_never_uses_the_network(self):
        with patch("requests.sessions.Session.request") as request_mock:
            data = get_bilibili_video_url_data(
                "https://www.bilibili.com/video/BV1xx411c7mD?p=2"
            )
        self.assertEqual(data["video_id"], "BV1xx411c7mD")
        self.assertEqual(data["params"], {"page": 2, "autoplay": 0})
        request_mock.assert_not_called()
