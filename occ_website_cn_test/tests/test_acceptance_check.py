from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools.safe_eval import safe_eval


SAMPLE_XMLIDS = (
    "check_installation",
    "check_bilibili_builder",
    "check_bilibili_rich_text",
    "check_bilibili_rejection",
    "check_bilibili_cookie",
    "check_native_video_regression",
    "check_share_platforms",
    "check_wechat_share_modes",
    "check_share_sensitive_url",
    "check_share_fallback_accessibility",
    "check_filing_multiwebsite",
    "check_filing_url_validation",
    "check_filing_footer",
    "check_no_sensitive_data",
)


@tagged("post_install", "-at_install")
class TestOccWebsiteCnAcceptanceCheck(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Check = cls.env["occ.website.cn.acceptance.check"]
        cls.regular_user = new_test_user(
            cls.env,
            login="occ_website_cn_acceptance_regular",
            groups="base.group_user",
        )
        cls.system_user = new_test_user(
            cls.env,
            login="occ_website_cn_acceptance_system",
            groups="base.group_system",
        )

    @staticmethod
    def _record_values(name):
        return {
            "name": name,
            "category": "sharing",
            "steps": "在隔离环境执行补充的脱敏验收步骤。",
            "expected_result": "得到符合公开契约且不含敏感数据的结果。",
        }

    def test_samples_cover_all_1_0_capabilities_and_security(self):
        samples = self.Check.browse(
            [
                self.env.ref(f"occ_website_cn_test.{xmlid}").id
                for xmlid in SAMPLE_XMLIDS
            ]
        )

        self.assertEqual(len(samples), len(SAMPLE_XMLIDS))
        self.assertEqual(len(samples.ids), len(set(samples.ids)))
        self.assertEqual(
            set(samples.mapped("category")),
            {"installation", "bilibili", "sharing", "filing", "security"},
        )
        self.assertTrue(
            self.env.ref("occ_website_cn_test.check_filing_footer")
        )
        self.assertTrue(
            self.env.ref("occ_website_cn_test.check_share_sensitive_url")
        )
        self.assertTrue(
            self.env.ref("occ_website_cn_test.check_bilibili_cookie")
        )

    def test_sample_xmlids_are_noupdate(self):
        metadata = self.env["ir.model.data"].search(
            [
                ("module", "=", "occ_website_cn_test"),
                ("name", "in", SAMPLE_XMLIDS),
            ]
        )

        self.assertEqual(set(metadata.mapped("name")), set(SAMPLE_XMLIDS))
        self.assertTrue(all(metadata.mapped("noupdate")))

    def test_statuses_and_sanitized_notes_are_writable(self):
        check = self.env.ref("occ_website_cn_test.check_filing_footer")
        expected_statuses = {
            "pending": "待验收",
            "passed": "通过",
            "failed": "失败",
            "blocked": "阻塞",
        }

        self.assertEqual(dict(self.Check._fields["status"].selection), expected_statuses)
        for status in expected_statuses:
            check.write({"status": status, "notes": f"脱敏测试结论：{status}"})
            self.assertEqual(check.status, status)
            self.assertEqual(check.notes, f"脱敏测试结论：{status}")

    def test_new_check_defaults_to_pending_without_notes(self):
        check = self.Check.create(self._record_values("自定义国内分享检查"))

        self.assertEqual(check.status, "pending")
        self.assertFalse(check.notes)

    def test_acceptance_model_has_no_sensitive_fields(self):
        sensitive_markers = {
            "app_id",
            "appid",
            "secret",
            "password",
            "credential",
            "token",
            "openid",
            "unionid",
            "email",
            "verification_link",
        }

        for field_name in self.Check._fields:
            self.assertFalse(
                any(marker in field_name.casefold() for marker in sensitive_markers),
                f"Sensitive field is not allowed: {field_name}",
            )

    def test_acl_is_granted_only_to_system_administrators(self):
        access = self.env.ref(
            "occ_website_cn_test.access_occ_website_cn_acceptance_check_system"
        )

        self.assertEqual(access.group_id, self.env.ref("base.group_system"))
        self.assertTrue(access.perm_read)
        self.assertTrue(access.perm_write)
        self.assertTrue(access.perm_create)
        self.assertTrue(access.perm_unlink)

    def test_system_administrator_can_crud_acceptance_records(self):
        checks = self.Check.with_user(self.system_user)
        check = checks.create(self._record_values("管理员 CRUD 验收"))

        self.assertEqual(check.read(["name"])[0]["name"], "管理员 CRUD 验收")
        check.write({"status": "passed", "notes": "脱敏通过"})
        self.assertEqual((check.status, check.notes), ("passed", "脱敏通过"))
        check.unlink()
        self.assertFalse(check.exists())

    def test_regular_internal_user_is_denied_every_crud_operation(self):
        check = self.env.ref("occ_website_cn_test.check_filing_footer")
        regular_check = check.with_user(self.regular_user)
        regular_model = self.Check.with_user(self.regular_user)
        operations = {
            "read": lambda: regular_check.read(["name"]),
            "create": lambda: regular_model.create(
                self._record_values("普通用户越权创建")
            ),
            "write": lambda: regular_check.write({"notes": "越权写入"}),
            "unlink": regular_check.unlink,
        }

        for operation_name, operation in operations.items():
            with self.subTest(operation=operation_name):
                with self.assertRaises(AccessError):
                    operation()

    def test_shortcuts_open_website_settings_and_current_site(self):
        settings_action = self.env.ref(
            "occ_website_cn_test.action_occ_website_cn_settings"
        )
        settings_menu = self.env.ref(
            "occ_website_cn_test.menu_occ_website_cn_settings"
        )
        homepage_action = self.env.ref(
            "occ_website_cn_test.action_occ_website_cn_homepage"
        )
        homepage_menu = self.env.ref(
            "occ_website_cn_test.menu_occ_website_cn_homepage"
        )
        demo_action = self.env.ref(
            "occ_website_cn_test.action_occ_website_cn_demo"
        )
        demo_menu = self.env.ref(
            "occ_website_cn_test.menu_occ_website_cn_demo"
        )
        context = safe_eval(settings_action.context)

        self.assertEqual(settings_action.res_model, "res.config.settings")
        self.assertEqual(settings_action.view_mode, "form")
        self.assertEqual(context["module"], "website")
        self.assertIs(context["bin_size"], False)
        self.assertEqual(settings_menu.action, settings_action)
        self.assertEqual(homepage_action.url, "/")
        self.assertEqual(homepage_action.target, "self")
        self.assertEqual(homepage_menu.action, homepage_action)
        self.assertEqual(demo_action.url, "/occ_website_cn_test/demo")
        self.assertEqual(demo_action.target, "self")
        self.assertEqual(demo_menu.action, demo_action)

    def test_menu_and_action_are_connected(self):
        root_menu = self.env.ref("occ_website_cn_test.menu_acceptance_root")
        menu = self.env.ref("occ_website_cn_test.menu_acceptance_check")
        action = self.env.ref("occ_website_cn_test.action_acceptance_check")

        self.assertEqual(root_menu.parent_id, self.env.ref("base.menu_administration"))
        self.assertEqual(root_menu.group_ids, self.env.ref("base.group_system"))
        self.assertEqual(menu.parent_id, root_menu)
        self.assertEqual(menu.action, action)
        self.assertEqual(action.res_model, "occ.website.cn.acceptance.check")
        self.assertEqual(action.view_mode, "list,form")
