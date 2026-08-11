from odoo import fields, models


class OccWechatLoginAcceptanceCheck(models.Model):
    _name = "occ.wechat.login.acceptance.check"
    _description = "OdooCC WeChat Login Acceptance Check"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    name = fields.Char(string="验收项", required=True)
    category = fields.Selection(
        selection=[
            ("configuration", "配置"),
            ("qr_scan", "扫码"),
            ("first_account", "首次开户"),
            ("email_verification", "邮箱验证"),
            ("repeated_login", "再次登录"),
            ("account_binding", "账号绑定"),
            ("user_type", "用户类型"),
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
            "只记录脱敏结论。不要填写 AppSecret、密码、Token、微信授权码、"
            "邮箱验证链接或完整个人身份标识。"
        ),
    )
