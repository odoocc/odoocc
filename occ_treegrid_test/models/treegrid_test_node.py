from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class OccTreegridTestNode(models.Model):
    _name = "occ.treegrid.test.node"
    _description = "OdooCC TreeGrid 演示节点"
    _inherit = ["occ.treegrid.mixin"]
    _order = "sequence, id"
    _parent_name = "parent_id"
    _parent_store = True

    _occ_treegrid_parent_field = "parent_id"
    _occ_treegrid_sequence_field = "sequence"
    _occ_treegrid_max_nodes = 2000

    name = fields.Char(string="名称", required=True, index="trigram")
    parent_id = fields.Many2one(
        "occ.treegrid.test.node",
        string="父节点",
        index=True,
        ondelete="restrict",
    )
    child_ids = fields.One2many(
        "occ.treegrid.test.node",
        "parent_id",
        string="子节点",
    )
    parent_path = fields.Char(index=True)
    sequence = fields.Integer(string="排序", default=10, required=True, index=True)
    active = fields.Boolean(string="启用", default=True)
    note = fields.Text(string="说明")

    @api.constrains("parent_id")
    def _check_parent_recursion(self):
        if self._has_cycle():
            raise ValidationError(_("TreeGrid 节点不能形成父子循环。"))
