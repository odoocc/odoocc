{
    "name": "OCC WeChat Login",
    "version": "19.0.4.0.4",
    "category": "Authentication",
    "summary": "Embedded WeChat login with verified-email credentials",
    "description": """
Authenticate Odoo users with an embedded WeChat QR Connect flow, bind their
UnionID, verify a unique community username and email login, and deliver the
first password while preserving the configured user type.
""",
    "author": "OCC",
    "website": "https://odoocc.com",
    "license": "LGPL-3",
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
