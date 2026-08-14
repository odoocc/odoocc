from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("occ_markdown", "post_install", "-at_install")
class TestMarkdownService(TransactionCase):
    def setUp(self):
        super().setUp()
        self.service = self.env["occ.markdown.service"]

    def test_common_markdown_and_semantic_classes(self):
        result = self.service.convert_markdown(
            """# 标题

- 列表

| 名称 | 数量 |
| --- | ---: |
| 示例 | 2 |

> 引用

```python
print("你好")
```

![图片](https://example.com/image.png)

[链接](https://odoocc.com)
""",
            {},
        )
        self.assertIn("<h1", result)
        self.assertIn("table table-bordered table-hover o_table", result)
        self.assertIn("border-start border-4 ps-3 text-muted", result)
        self.assertIn("bg-light border rounded p-3 overflow-auto", result)
        self.assertIn('class="img-fluid"', result)
        self.assertIn('rel="noopener noreferrer"', result)

    def test_emoji_toc_and_strikethrough(self):
        result = self.service.convert_markdown(
            "# 一级😀\n\n## 二级\n\n~~已删除~~",
            {"strip_emoji": True, "create_toc": True},
        )
        self.assertNotIn("😀", result)
        self.assertIn('<nav class="o_occ_markdown_toc"><h2>目录</h2>', result)
        self.assertIn("<del>已删除</del>", result)

    def test_end_to_end_business_process_table(self):
        result = self.service.convert_markdown(
            """| 端到端流程 | 英文缩写 | 起点 | 终点 | 贯穿的核心模块 |
| --- | --- | --- | --- | --- |
| **线索到回款** | LTC（Lead to Cash） | 获取销售线索 | 收回客户款项 | CRM → 销售 → 库存 → 会计 |
| **寻源到付款** | STP（Source to Pay） | 识别采购需求 | 支付供应商款项 | 采购 → 库存 → 会计 |
| **计划到生产** | PTP（Plan to Produce） | 需求产生（订单/预测） | 成品完工入库 | 销售/预测 → 生产 → 库存 → 质量 |
| **订单到收款** | OTC（Order to Cash） | 客户下订单 | 收回客户款项 | 销售 → 库存 → 会计 |
| **采购到付款** | PTP（Procure to Pay） | 创建采购订单 | 支付供应商款项 | 采购 → 库存 → 会计 |
""",
            {},
        )
        self.assertIn("table table-bordered table-hover o_table", result)
        self.assertIn("端到端流程", result)
        self.assertIn("<strong>线索到回款</strong>", result)
        self.assertIn("CRM → 销售 → 库存 → 会计", result)
        self.assertIn("PTP（Plan to Produce）", result)
        self.assertIn("PTP（Procure to Pay）", result)

    def test_safe_mermaid_flowchart(self):
        source = """```mermaid
flowchart TD
    A[CRM线索管理] --> B[生成报价单]
    B --> C{报价审核}
    C -- 未通过 --> B
    C -- 通过 --> D[确认销售订单]
    D --> E{检查库存}
    E -- 库存充足 --> F[预留库存]
    E -- 库存不足 --> G[触发补货/采购流程]
    F --> H[发货配送]
    G --> H
    H --> I[生成发票]
    I --> J[收款与对账]
    J --> K[订单闭环完成]
```
"""
        result = self.service.convert_markdown(source, {})
        self.assertIn("mermaid o_occ_markdown_mermaid", result)
        self.assertIn("CRM线索管理", result)
        self.assertIn("C -- 未通过 --&gt; B", result)
        self.assertNotIn("<code", result)

    def test_unsafe_or_non_flowchart_mermaid_is_rejected(self):
        for source in (
            "```mermaid\nsequenceDiagram\nA->>B: 你好\n```",
            "```mermaid\nflowchart TD\nclick A javascript:alert(1)\n```",
            "```mermaid\nflowchart TD\n%%{init: {}}%%\nA-->B\n```",
        ):
            with self.subTest(source=source), self.assertRaises(ValidationError):
                self.service.convert_markdown(source, {})

    def test_raw_html_and_dangerous_links_are_sanitized(self):
        result = self.service.convert_markdown(
            '<script>alert(1)</script>\n\n[危险](javascript:alert(1))\n\n'
            '~~<img src=x onerror=alert(1)>~~',
            {},
        )
        self.assertNotIn("script", result.lower())
        self.assertNotIn("javascript:", result.lower())
        self.assertNotIn("<img", result.lower())
        self.assertIn("&lt;img", result)

    def test_bilibili_marker_and_url_are_canonical(self):
        cases = (
            "{{bilibili:BV1xx411c7mD|page=2}}",
            "https://www.bilibili.com/video/BV1xx411c7mD?p=2",
        )
        for source in cases:
            with self.subTest(source=source):
                result = self.service.convert_markdown(source, {})
                self.assertIn("occ_bilibili_embedded_video", result)
                self.assertIn(
                    "https://player.bilibili.com/player.html?bvid=BV1xx411c7mD&amp;page=2&amp;autoplay=0",
                    result,
                )

        maximum_page = self.service.convert_markdown(
            "{{bilibili:BV1xx411c7mD|page=10000}}", {}
        )
        self.assertIn("page=10000", maximum_page)

    def test_bilibili_can_be_disabled(self):
        result = self.service.convert_markdown(
            "{{bilibili:BV1xx411c7mD}}", {"allow_bilibili": False}
        )
        self.assertNotIn("iframe", result)
        self.assertIn("bilibili", result)

    def test_invalid_contract_values_are_rejected(self):
        for source, options in (
            (False, {}),
            ("正文", []),
            ("正文", {"unknown": True}),
            ("正文", {"strip_emoji": 1}),
        ):
            with self.subTest(source=source, options=options), self.assertRaises(
                ValidationError
            ):
                self.service.convert_markdown(source, options)

    def test_regular_internal_user_can_call_stateless_service(self):
        user = self.env["res.users"].create(
            {
                "name": "Markdown 服务调用用户",
                "login": "occ_markdown_service_user",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        result = self.service.with_user(user).convert_markdown("# 可调用", {})
        self.assertIn("可调用", result)
