{
    "name": "OdooCC Markdown 编辑器",
    "version": "19.0.1.0.0",
    "category": "Tools",
    "summary": "提供Markdown转换、所见即所得编辑和富文本插入能力",
    "description": (
        "为 Odoo 业务模块提供安全的Markdown转换服务、单窗口编辑组件和"
        "后台富文本插入入口。"
    ),
    "author": "Odoo老赵",
    "website": "https://odoocc.com",
    "support": "156277468@qq.com",
    "license": "AGPL-3",
    "depends": ["html_editor", "occ_base_bilibili"],
    "external_dependencies": {"python": ["markdown"]},
    "assets": {
        "web.assets_backend": [
            "occ_markdown/static/lib/vditor/index.css",
            "occ_markdown/static/lib/vditor/index.min.js",
            "occ_markdown/static/src/js/bilibili_preview_dialog.js",
            "occ_markdown/static/src/js/markdown_editor.js",
            "occ_markdown/static/src/js/markdown_field.js",
            "occ_markdown/static/src/js/markdown_dialog.js",
            "occ_markdown/static/src/js/markdown_plugin.js",
            "occ_markdown/static/src/js/html_field_patch.js",
            "occ_markdown/static/src/js/mermaid_renderer.js",
            "occ_markdown/static/src/xml/markdown_editor.xml",
            "occ_markdown/static/src/scss/markdown_editor.scss",
        ],
        "web.assets_unit_tests": [
            "occ_markdown/static/lib/vditor/index.min.js",
            "occ_markdown/static/tests/**/*.js",
        ],
        "web.assets_frontend": [
            "occ_markdown/static/src/js/mermaid_renderer.js",
            "occ_markdown/static/src/scss/markdown_editor.scss",
        ],
    },
    "application": False,
    "installable": True,
}
