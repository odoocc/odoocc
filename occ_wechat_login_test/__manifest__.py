{
    "name": "OdooCC 微信登录验收清单",
    "version": "19.0.1.0.1",
    "category": "Tools",
    "summary": "使用真实微信流程验收 OdooCC 微信登录",
    "description": """
为 occ_wechat_login 提供管理员可维护的人工验收清单，覆盖配置、扫码、首次开户、
邮箱验证、再次登录、账号绑定和用户类型。模块只记录验收状态与脱敏备注，不保存
微信、邮箱或 Odoo 登录凭据，也不提供模拟登录入口或认证后门。
""",
    "author": "Odoo老赵",
    "website": "https://odoocc.com",
    "support": "156277468@qq.com",
    "license": "AGPL-3",
    "depends": ["occ_wechat_login"],
    "data": [
        "security/ir.model.access.csv",
        "data/acceptance_checklist_data.xml",
        "views/acceptance_check_views.xml",
    ],
    "odoocc_demo": {
        "schema_version": 1,
        "category": "collaboration_integration",
        "sequence": 100,
        "menu_xmlid": "occ_wechat_login_test.menu_occ_wechat_login_acceptance_root",
        "entry_menu_xmlid": "occ_wechat_login_test.menu_occ_wechat_login_acceptance_check",
        "keywords": ["微信登录", "扫码登录", "QRConnect", "账号绑定", "邮箱验证"],
    },
    "application": False,
    "installable": True,
    "auto_install": False,
}
