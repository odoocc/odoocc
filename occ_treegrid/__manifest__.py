{
    "name": "OCC 层级列表",
    "version": "19.0.1.0.0",
    "category": "Hidden",
    "summary": "支持同级拖拽排序的可复用层级列表视图",
    "description": """
OCC TreeGrid 为显式接入的层级模型扩展 Odoo 标准列表视图，在保留原生列表渲染的
同时提供树节点展开、包含祖先上下文的筛选展示和事务化同级排序。
    """,
    "author": "OCC",
    "license": "LGPL-3",
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
