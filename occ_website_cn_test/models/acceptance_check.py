from odoo import fields, models


class OccWebsiteCnAcceptanceCheck(models.Model):
    _name = "occ.website.cn.acceptance.check"
    _description = "OdooCC 网站中国生态增强验收项"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    name = fields.Char(string="验收项", required=True)
    category = fields.Selection(
        selection=[
            ("installation", "安装"),
            ("bilibili", "B站视频"),
            ("sharing", "国内分享"),
            ("filing", "网站备案"),
            ("security", "隐私与安全"),
        ],
        string="分类",
        required=True,
        index=True,
    )
    steps = fields.Text(string="验收步骤", required=True)
    expected_result = fields.Text(string="预期结果", required=True)
    status = fields.Selection(
        selection=[
            ("pending", "待验收"),
            ("passed", "通过"),
            ("failed", "失败"),
            ("blocked", "阻塞"),
        ],
        string="状态",
        required=True,
        default="pending",
        copy=False,
        index=True,
    )
    notes = fields.Text(
        string="脱敏备注",
        copy=False,
        help=(
            "只记录脱敏结论。不要填写密码、Token、"
            "带敏感查询参数的完整链接、"
            "客户数据、完整个人身份标识或生产环境截图。"
        ),
    )
