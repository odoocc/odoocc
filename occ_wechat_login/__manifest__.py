{
    "name": "OdooCC 微信扫码登录",
    "version": "19.0.4.0.5",
    "category": "Authentication",
    "summary": "微信扫码登录、社区用户名、邮箱验证与密码凭据",
    "description": """
通过内嵌微信 QRConnect 流程认证 Odoo 用户，以 UnionID 绑定账号，验证唯一的
社区用户名和邮箱登录名，并在保持所配置用户类型的前提下发送首次登录凭据。
""",
    "author": "Odoo老赵",
    "website": "https://odoocc.com",
    "support": "156277468@qq.com",
    "license": "AGPL-3",
    "depends": ["web", "mail", "base_setup"],
    "post_load": "post_load",
    "data": [
        "data/mail_template_data.xml",
        "views/res_config_settings_views.xml",
        "views/res_users_views.xml",
        "views/login_templates.xml",
        "views/email_verification_templates.xml",
        "data/res_lang_data.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "occ_wechat_login/static/src/scss/login.scss",
        ],
    },
    "application": False,
    "installable": True,
}
