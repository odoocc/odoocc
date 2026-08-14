from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged("occ_base_bilibili_test", "post_install", "-at_install")
class TestBilibiliDemo(TransactionCase):
    def test_admin_can_parse_without_loading_video(self):
        demo = self.env["occ.base.bilibili.demo"].create(
            {
                "name": "分P示例",
                "video_input": "https://m.bilibili.com/video/av170001?p=3",
            }
        )
        demo.action_parse()
        self.assertEqual(demo.parse_status, "valid")
        self.assertEqual(demo.canonical_video_id, "170001")
        self.assertEqual(demo.page, 3)
        self.assertEqual(
            demo.player_url,
            "https://player.bilibili.com/player.html?aid=170001&page=3&autoplay=0",
        )

    def test_invalid_input_is_visible_but_not_interpreted(self):
        demo = self.env["occ.base.bilibili.demo"].create(
            {"name": "短链接", "video_input": "https://b23.tv/example"}
        )
        demo.action_parse()
        self.assertEqual(demo.parse_status, "invalid")
        self.assertTrue(demo.is_bilibili_input)
        self.assertFalse(demo.player_url)

    def test_internal_user_has_no_demo_access(self):
        user = self.env["res.users"].create(
            {
                "name": "B站验收普通用户",
                "login": "occ_bilibili_demo_user",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        with self.assertRaises(AccessError):
            self.env["occ.base.bilibili.demo"].with_user(user).create(
                {"name": "越权", "video_input": "av170001"}
            )

    def test_demo_menu_contract(self):
        self.assertTrue(
            self.env.ref("occ_base_bilibili_test.menu_acceptance_root").exists()
        )
        menu = self.env.ref("occ_base_bilibili_test.menu_bilibili_demo")
        self.assertEqual(menu.action.res_model, "occ.base.bilibili.demo")
