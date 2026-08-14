from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("occ_markdown_test", "post_install", "-at_install")
class TestMarkdownDemo(TransactionCase):
    def test_fixed_demo_exercises_public_service(self):
        demo = self.env.ref("occ_markdown_test.markdown_demo_default")
        demo.action_generate_html()
        self.assertIn("<table", demo.generated_html)
        self.assertIn("occ_bilibili_embedded_video", demo.generated_html)
        self.assertEqual(demo.generated_by, self.env.user)
        self.assertTrue(demo.generated_at)

        business_flow = self.env.ref(
            "occ_markdown_test.markdown_demo_business_flow"
        )
        business_flow.action_generate_html()
        self.assertIn("<table", business_flow.generated_html)
        self.assertIn("o_occ_markdown_mermaid", business_flow.generated_html)
        self.assertIn("CRM线索管理", business_flow.generated_html)

    def test_empty_markdown_is_rejected(self):
        demo = self.env["occ.markdown.demo"].create({"name": "空正文"})
        with self.assertRaises(ValidationError):
            demo.action_generate_html()

    def test_internal_user_has_no_demo_access(self):
        user = self.env["res.users"].create(
            {
                "name": "Markdown 验收普通用户",
                "login": "occ_markdown_demo_user",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        with self.assertRaises(AccessError):
            self.env["occ.markdown.demo"].with_user(user).create({"name": "越权"})

    def test_widget_options_are_present_in_demo_view(self):
        view = self.env.ref("occ_markdown_test.view_markdown_demo_form")
        arch = view.arch_db
        self.assertIn('widget="occ_markdown"', arch)
        self.assertIn("markdown_strip_emoji", arch)
        self.assertIn("markdown_create_toc", arch)
        self.assertEqual(
            self.env.ref("occ_markdown_test.menu_markdown_demo").action.res_model,
            "occ.markdown.demo",
        )
