from odoo import _, fields, models
from odoo.exceptions import ValidationError


class OccMarkdownDemo(models.Model):
    _name = "occ.markdown.demo"
    _description = "Markdown 编辑器验收"

    name = fields.Char(string="名称", required=True)
    markdown_source = fields.Text(string="Markdown 正文")
    markdown_strip_emoji = fields.Boolean(string="清除表情符号")
    markdown_create_toc = fields.Boolean(string="生成目录")
    generated_html = fields.Html(
        string="服务端生成内容",
        readonly=True,
        sanitize=False,
        help="仅保存 occ.markdown.service 已完成白名单清理的 HTML。",
    )
    generated_at = fields.Datetime(string="最近生成时间", readonly=True)
    generated_by = fields.Many2one("res.users", string="最近生成人", readonly=True)
    rich_text = fields.Html(
        string="HTML 富文本验收区",
        help="在编辑器中输入 /Markdown，验收全局 Markdown 插入入口。",
    )

    def action_generate_html(self):
        service = self.env["occ.markdown.service"]
        for record in self:
            if not (record.markdown_source or "").strip():
                raise ValidationError(_("请先填写 Markdown 正文。"))
            record.write(
                {
                    "generated_html": service.convert_markdown(
                        record.markdown_source,
                        {
                            "strip_emoji": record.markdown_strip_emoji,
                            "create_toc": record.markdown_create_toc,
                            "allow_bilibili": True,
                        },
                    ),
                    "generated_at": fields.Datetime.now(),
                    "generated_by": self.env.user.id,
                }
            )
        return True
