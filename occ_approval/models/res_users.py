from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResUsers(models.Model):
    _inherit = "res.users"

    occ_approval_manager_id = fields.Many2one(
        "res.users",
        string="Approval Manager",
        domain="[('id', '!=', id), ('share', '=', False)]",
        ondelete="set null",
        index=True,
    )

    @api.constrains("occ_approval_manager_id")
    def _check_occ_approval_manager_chain(self):
        for user in self:
            seen = {user.id}
            manager = user.occ_approval_manager_id
            depth = 0
            while manager:
                if manager.id in seen:
                    raise ValidationError(_("The approval manager hierarchy cannot contain a cycle."))
                seen.add(manager.id)
                manager = manager.occ_approval_manager_id
                depth += 1
                if depth > 100:
                    raise ValidationError(_("The approval manager hierarchy is too deep."))

