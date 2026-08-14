{
    "name": "OdooCC B站基础能力验收",
    "version": "19.0.1.0.0",
    "category": "Tools",
    "summary": "验收 OdooCC B站基础能力的公开业务契约",
    "description": (
        "为 occ_base_bilibili 提供交互式离线解析器和管理员脱敏验收清单，"
        "验证公开接口与权限边界。"
    ),
    "author": "Odoo老赵",
    "website": "https://odoocc.com",
    "support": "156277468@qq.com",
    "license": "AGPL-3",
    "depends": ["occ_base_bilibili"],
    "data": [
        "security/ir.model.access.csv",
        "data/acceptance_checklist_data.xml",
        "views/acceptance_check_views.xml",
        "views/bilibili_demo_views.xml",
    ],
    "odoocc_demo": {
        "schema_version": 1,
        "category": "developer_tools",
        "sequence": 70,
        "menu_xmlid": "occ_base_bilibili_test.menu_acceptance_root",
        "entry_menu_xmlid": "occ_base_bilibili_test.menu_bilibili_demo",
        "keywords": ["B站", "视频解析"],
    },
    "application": False,
    "installable": True,
    "auto_install": False,
}
