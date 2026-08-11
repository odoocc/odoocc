{
    "name": "OdooCC 层级列表（TreeGrid）",
    "version": "19.0.1.0.1",
    "category": "Hidden",
    "summary": "支持层级展开、祖先上下文和同级拖拽排序的列表视图",
    "description": """
OdooCC TreeGrid 为显式接入的层级模型扩展 Odoo 标准列表视图，在保留原生列表渲染的
同时提供树节点展开、包含祖先上下文的筛选展示和事务化同级排序。
    """,
    "author": "Odoo老赵",
    "website": "https://odoocc.com",
    "support": "156277468@qq.com",
    "license": "AGPL-3",
    "depends": ["web"],
    "assets": {
        "web.assets_backend": [
            "occ_treegrid/static/src/**/*.js",
            "occ_treegrid/static/src/**/*.xml",
            "occ_treegrid/static/src/**/*.scss",
        ],
        "web.assets_unit_tests": [
            "occ_treegrid/static/tests/**/*.js",
        ],
    },
    "application": False,
    "installable": True,
}
