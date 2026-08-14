{
    "name": "OdooCC B站基础能力",
    "version": "19.0.1.0.0",
    "category": "Hidden",
    "summary": "提供安全、离线且可复用的B站视频地址解析能力",
    "description": (
        "为 Odoo 模块提供严格白名单的B站视频地址解析和规范播放器地址生成能力，"
        "不请求B站接口。"
    ),
    "author": "Odoo老赵",
    "website": "https://odoocc.com",
    "support": "156277468@qq.com",
    "license": "AGPL-3",
    "depends": ["web"],
    "assets": {
        "web.assets_backend": [
            "occ_base_bilibili/static/src/bilibili_parser.js",
        ],
        "web.assets_frontend": [
            "occ_base_bilibili/static/src/bilibili_parser.js",
        ],
        "web.assets_unit_tests": [
            "occ_base_bilibili/static/tests/**/*.js",
        ],
    },
    "application": False,
    "installable": True,
}
