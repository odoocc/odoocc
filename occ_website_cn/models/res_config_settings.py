from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    occ_icp_filing_text = fields.Char(
        related="website_id.occ_icp_filing_text",
        readonly=False,
        groups="base.group_system",
    )
    occ_icp_filing_url = fields.Char(
        related="website_id.occ_icp_filing_url",
        readonly=False,
        groups="base.group_system",
    )
    occ_public_security_filing_text = fields.Char(
        related="website_id.occ_public_security_filing_text",
        readonly=False,
        groups="base.group_system",
    )
    occ_public_security_filing_url = fields.Char(
        related="website_id.occ_public_security_filing_url",
        readonly=False,
        groups="base.group_system",
    )
