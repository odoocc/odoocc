"""Upgrade regression tests for OdooCC WeChat authentication."""

from odoo.modules.module import load_script
from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import file_path


@tagged("post_install", "-at_install")
class TestWechatMigrations(TransactionCase):
    """Verify that upgrades preserve administrator template customizations."""

    def test_template_brand_migration_updates_only_legacy_default_labels(self):
        verification = self.env.ref(
            "occ_wechat_login.mail_template_email_verification"
        )
        credentials = self.env.ref(
            "occ_wechat_login.mail_template_initial_credentials"
        )
        verification.update_field_translations(
            "name",
            {
                "en_US": "OCC: Email Verification",
                "zh_CN": "OCC：邮箱验证",
            },
        )
        credentials.update_field_translations(
            "name",
            {
                "en_US": "Custom credentials label",
                "zh_CN": "OCC：初始登录凭据",
            },
        )

        migration = load_script(
            file_path(
                "occ_wechat_login/migrations/4.0.5/"
                "post-rename-template-labels.py"
            ),
            "odoo.addons.occ_wechat_login.tests.migration_4_0_5",
        )
        migration.migrate(self.env.cr, "19.0.4.0.4")

        verification_names = verification._fields["name"]._get_stored_translations(
            verification
        )
        credentials_names = credentials._fields["name"]._get_stored_translations(
            credentials
        )
        self.assertEqual(
            verification_names,
            {
                "en_US": "OdooCC: Email Verification",
                "zh_CN": "OdooCC：邮箱验证",
            },
        )
        self.assertEqual(
            credentials_names,
            {
                "en_US": "Custom credentials label",
                "zh_CN": "OdooCC：初始登录凭据",
            },
        )
