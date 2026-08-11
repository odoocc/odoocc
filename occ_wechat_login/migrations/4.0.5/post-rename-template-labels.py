"""Migrate the built-in mail template labels to the OdooCC brand."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Rename untouched stock templates while preserving custom labels."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    template_names = {
        "occ_wechat_login.mail_template_email_verification": {
            "OCC: Email Verification": "OdooCC: Email Verification",
            "OCC：邮箱验证": "OdooCC：邮箱验证",
        },
        "occ_wechat_login.mail_template_initial_credentials": {
            "OCC: Initial Login Credentials": "OdooCC: Initial Login Credentials",
            "OCC：初始登录凭据": "OdooCC：初始登录凭据",
        },
    }
    for xmlid, legacy_names in template_names.items():
        template = env.ref(xmlid, raise_if_not_found=False)
        if not template:
            continue

        # Translatable fields are stored as a language-to-value JSON mapping in
        # Odoo 19.  A normal ``write`` only updates the current language and can
        # leave an old OCC label visible to users of another language.  Rename
        # every untouched stock value while preserving each customized value.
        translations = template._fields["name"]._get_stored_translations(template)
        replacements = {
            lang: legacy_names[value]
            for lang, value in (translations or {}).items()
            if value in legacy_names
        }
        if replacements:
            template.update_field_translations("name", replacements)
