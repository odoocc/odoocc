{
    "name": "OdooCC TreeGrid 演示与集成测试",
    "version": "19.0.1.0.1",
    "category": "Technical",
    "summary": "演示并验证 OdooCC TreeGrid 的完整模型与视图接入契约",
    "description": """
OdooCC TreeGrid 演示与集成测试提供一棵可直接操作的三级样例树，用于验证祖先上下文、
结构展开、同级排序、归档节点与访问权限等 occ_treegrid 集成行为。
    """,
    "author": "Odoo老赵",
    "website": "https://odoocc.com",
    "support": "156277468@qq.com",
    "license": "AGPL-3",
    "depends": ["occ_treegrid"],
    "data": [
        "security/ir.model.access.csv",
        "data/treegrid_test_data.xml",
        "views/treegrid_test_views.xml",
    ],
    "odoocc_demo": {
        "schema_version": 1,
        "category": "developer_tools",
        "sequence": 100,
        "menu_xmlid": "occ_treegrid_test.menu_occ_treegrid_test_root",
        "entry_menu_xmlid": "occ_treegrid_test.menu_occ_treegrid_test_node",
        "keywords": ["TreeGrid", "层级列表", "树形表格", "拖拽排序"],
    },
    "application": False,
    "installable": True,
    "auto_install": False,
}
