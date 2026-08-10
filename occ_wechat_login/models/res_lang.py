from odoo import api, models

from ..const import NEW_WECHAT_USER_LANGUAGE


class ResLang(models.Model):
    _inherit = "res.lang"

    @api.model
    def _occ_ensure_new_wechat_user_language(self):
        """Install the language required by newly created WeChat users."""
        languages = self.sudo().with_context(active_test=False)
        language = languages.search(
            [("code", "=", NEW_WECHAT_USER_LANGUAGE)],
            limit=1,
        )
        language_changed = False
        if not language:
            language = languages._create_lang(NEW_WECHAT_USER_LANGUAGE)
            language_changed = True
            installed_modules = (
                self.env["ir.module.module"]
                .sudo()
                .search([("state", "=", "installed")])
            )
            installed_modules._update_translations(
                [NEW_WECHAT_USER_LANGUAGE]
            )
        elif not language.active:
            language.action_unarchive()
            language_changed = True

        if language_changed:
            current_module = (
                self.env["ir.module.module"]
                .sudo()
                .search([("name", "=", "occ_wechat_login")], limit=1)
            )
            current_module._update_translations(
                [NEW_WECHAT_USER_LANGUAGE]
            )
        return language
