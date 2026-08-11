from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools.safe_eval import safe_eval


SAMPLE_XMLIDS = (
    "check_configuration_https_callback",
    "check_configuration_wechat_settings",
    "check_configuration_outgoing_mail",
    "check_qr_scan_real_wechat",
    "check_qr_scan_cancel_retry",
    "check_first_account_onboarding",
    "check_email_verification_request",
    "check_email_verification_confirm",
    "check_repeated_wechat_login",
    "check_repeated_password_login",
    "check_account_binding_reuse",
    "check_account_binding_duplicate_email",
    "check_user_type_portal",
    "check_user_type_internal",
)


@tagged("post_install", "-at_install")
class TestOccWechatLoginAcceptanceCheck(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Check = cls.env["occ.wechat.login.acceptance.check"]
        cls.regular_user = new_test_user(
            cls.env,
            login="occ_wechat_login_acceptance_regular",
            groups="base.group_user",
        )

    def test_samples_cover_approved_acceptance_scope(self):
        expected_categories = {
            "configuration",
            "qr_scan",
            "first_account",
            "email_verification",
            "repeated_login",
            "account_binding",
            "user_type",
        }
        samples = self.Check.browse(
            [
                self.env.ref(f"occ_wechat_login_test.{xmlid}").id
                for xmlid in SAMPLE_XMLIDS
            ]
        )

        self.assertEqual(len(samples), len(SAMPLE_XMLIDS))
        self.assertEqual(len(samples.ids), len(set(samples.ids)))
        self.assertEqual(set(samples.mapped("category")), expected_categories)

    def test_statuses_and_notes_are_writable(self):
        check = self.env.ref(
            "occ_wechat_login_test.check_qr_scan_real_wechat"
        )
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

    def test_new_check_defaults_to_pending(self):
        check = self.Check.create(
            {
                "name": "自定义真实流程检查",
                "category": "qr_scan",
                "steps": "使用真实微信执行管理员定义的补充步骤。",
                "expected_result": "得到可人工验收且不含敏感数据的结果。",
            }
        )

        self.assertEqual(check.status, "pending")
        self.assertFalse(check.notes)

    def test_model_has_no_credential_or_identity_fields(self):
        sensitive_markers = {
            "app_id",
            "appid",
            "secret",
            "password",
            "credential",
            "token",
            "authorization_code",
            "openid",
            "unionid",
            "email",
            "verification_link",
        }

        for field_name in self.Check._fields:
            self.assertFalse(
                any(marker in field_name.casefold() for marker in sensitive_markers),
                f"Sensitive field is not allowed on the acceptance model: {field_name}",
            )

    def test_only_system_administrators_receive_model_access(self):
        access = self.env.ref(
            "occ_wechat_login_test.access_occ_wechat_login_acceptance_check_system"
        )

        self.assertEqual(access.group_id, self.env.ref("base.group_system"))
        self.assertTrue(access.perm_read)
        self.assertTrue(access.perm_write)
        self.assertTrue(access.perm_create)
        self.assertTrue(access.perm_unlink)
        with self.assertRaises(AccessError):
            self.Check.with_user(self.regular_user).check_access("read")
        with self.assertRaises(AccessError):
            self.Check.with_user(self.regular_user).create(
                {
                    "name": "越权检查",
                    "category": "configuration",
                    "steps": "不应创建。",
                    "expected_result": "不应创建。",
                }
            )

    def test_settings_shortcut_opens_formal_general_settings(self):
        action = self.env.ref(
            "occ_wechat_login_test.action_occ_wechat_login_settings"
        )
        settings_menu = self.env.ref(
            "occ_wechat_login_test.menu_occ_wechat_login_settings"
        )
        formal_settings_view = self.env.ref(
            "occ_wechat_login.view_res_config_settings_occ_wechat"
        )
        context = safe_eval(action.context)

        self.assertEqual(action.res_model, "res.config.settings")
        self.assertEqual(action.view_mode, "form")
        self.assertEqual(context["module"], "general_settings")
        self.assertIs(context["bin_size"], False)
        self.assertEqual(settings_menu.action, action)
        self.assertEqual(formal_settings_view.model, "res.config.settings")
        self.assertEqual(
            formal_settings_view.inherit_id,
            self.env.ref("base_setup.res_config_settings_view_form"),
        )

    def test_main_menu_and_checklist_action_are_connected(self):
        root_menu = self.env.ref(
            "occ_wechat_login_test.menu_occ_wechat_login_acceptance_root"
        )
        checklist_menu = self.env.ref(
            "occ_wechat_login_test.menu_occ_wechat_login_acceptance_check"
        )
        checklist_action = self.env.ref(
            "occ_wechat_login_test.action_occ_wechat_login_acceptance_check"
        )

        self.assertEqual(root_menu.parent_id, self.env.ref("base.menu_administration"))
        self.assertEqual(root_menu.group_ids, self.env.ref("base.group_system"))
        self.assertEqual(checklist_menu.parent_id, root_menu)
        self.assertEqual(checklist_menu.action, checklist_action)
        self.assertEqual(
            checklist_action.res_model,
            "occ.wechat.login.acceptance.check",
        )
        self.assertEqual(checklist_action.view_mode, "list,form")
