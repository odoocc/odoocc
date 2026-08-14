from odoo import fields, models


class OccBaseBilibiliAcceptanceCheck(models.Model):
    _name = "occ.base.bilibili.acceptance.check"
    _description = "OdooCC B站基础能力验收项"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    name = fields.Char(string="验收项", required=True)
    category = fields.Selection(
        selection=[
            ("installation", "安装"),
            ("configuration", "配置"),
            ("core_flow", "核心流程"),
            ("security", "权限与安全"),
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
            "只记录脱敏结论。不要填写密码、AppSecret、Token、验证链接、"
            "完整个人身份标识或生产数据。"
        ),
    )
