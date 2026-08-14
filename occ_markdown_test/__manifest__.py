{
    "name": "OdooCC Markdown 编辑器验收",
    "version": "19.0.1.0.0",
    "category": "Tools",
    "summary": "验收 OdooCC Markdown 编辑器的公开业务契约",
    "description": (
        "为 occ_markdown 提供综合写作工作台和管理员脱敏验收清单，"
        "验证字段组件、转换服务与权限边界。"
    ),
    "author": "Odoo老赵",
    "website": "https://odoocc.com",
    "support": "156277468@qq.com",
    "license": "AGPL-3",
    "depends": ["occ_markdown"],
    "data": [
        "security/ir.model.access.csv",
        "data/acceptance_checklist_data.xml",
        "data/markdown_demo_data.xml",
        "views/acceptance_check_views.xml",
        "views/markdown_demo_views.xml",
    ],
    "odoocc_demo": {
        "schema_version": 1,
        "category": "developer_tools",
        "sequence": 80,
        "menu_xmlid": "occ_markdown_test.menu_acceptance_root",
        "entry_menu_xmlid": "occ_markdown_test.menu_markdown_demo",
        "keywords": ["Markdown", "所见即所得"],
    },
    "application": False,
    "installable": True,
    "auto_install": False,
}
