from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.misc import str2bool

from ..const import (
    NEW_USER_TYPE_INTERNAL,
    NEW_USER_TYPE_PORTAL,
    NEW_USER_TYPES,
)


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    occ_wechat_enabled = fields.Boolean(
        string="Enable WeChat Login",
        config_parameter="occ_wechat_login.enabled",
        groups="base.group_system",
    )
    occ_wechat_app_id = fields.Char(
        string="WeChat AppID",
        config_parameter="occ_wechat_login.app_id",
        groups="base.group_system",
    )
    occ_wechat_app_secret = fields.Char(
        string="WeChat AppSecret",
        config_parameter="occ_wechat_login.app_secret",
        groups="base.group_system",
    )
    occ_wechat_new_user_type = fields.Selection(
        selection=[
            (NEW_USER_TYPE_INTERNAL, "Internal User"),
            (NEW_USER_TYPE_PORTAL, "Portal User"),
        ],
        string="New WeChat User Type",
        default=NEW_USER_TYPE_INTERNAL,
        required=True,
        config_parameter="occ_wechat_login.new_user_type",
        groups="base.group_system",
    )
    occ_wechat_callback_url = fields.Char(
        string="WeChat Callback URL",
        compute="_compute_occ_wechat_callback_url",
        groups="base.group_system",
    )

    @api.depends("occ_wechat_enabled", "occ_wechat_app_id")
    def _compute_occ_wechat_callback_url(self):
        callback_url = self._occ_wechat_get_callback_url()
        for settings in self:
            settings.occ_wechat_callback_url = callback_url

    @api.model
    def _occ_wechat_get_callback_url(self):
        base_url = self.env["ir.config_parameter"].sudo().get_base_url().rstrip("/")
        return f"{base_url}/occ/wechat/callback"

    @api.model
    def _occ_wechat_get_new_user_type(self):
        new_user_type = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param(
                "occ_wechat_login.new_user_type",
                NEW_USER_TYPE_INTERNAL,
            )
        )
        if new_user_type not in NEW_USER_TYPES:
            return NEW_USER_TYPE_INTERNAL
        return new_user_type

    @api.model
    def _occ_wechat_get_config(self):
        parameters = self.env["ir.config_parameter"].sudo()
        return {
            "enabled": str2bool(
                parameters.get_param("occ_wechat_login.enabled", "False"),
                default=False,
            ),
            "app_id": parameters.get_param("occ_wechat_login.app_id", "").strip(),
            "app_secret": parameters.get_param("occ_wechat_login.app_secret", "").strip(),
            "new_user_type": self._occ_wechat_get_new_user_type(),
            "callback_url": self._occ_wechat_get_callback_url(),
        }

    def set_values(self):
        for settings in self:
            if settings.occ_wechat_enabled and not (
                settings.occ_wechat_app_id and settings.occ_wechat_app_secret
            ):
                raise ValidationError(
                    _("AppID and AppSecret are required before enabling WeChat login.")
                )
        return super().set_values()
