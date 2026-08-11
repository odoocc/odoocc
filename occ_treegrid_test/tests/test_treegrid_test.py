from lxml import etree

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools.safe_eval import safe_eval


@tagged("post_install", "-at_install")
class TestOccTreegridIntegration(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Node = cls.env["occ.treegrid.test.node"]
        cls.root = cls.env.ref("occ_treegrid_test.node_root")
        cls.child_a = cls.env.ref("occ_treegrid_test.node_child_a")
        cls.grandchild = cls.env.ref("occ_treegrid_test.node_grandchild_a1")
        cls.child_b = cls.env.ref("occ_treegrid_test.node_child_b")
        cls.archived_child = cls.env.ref("occ_treegrid_test.node_archived_child")
        cls.internal_user = new_test_user(
            cls.env,
            login="occ_treegrid_test_internal",
            groups="base.group_user",
        )
        cls.portal_user = new_test_user(
            cls.env,
            login="occ_treegrid_test_portal",
            groups="base.group_portal",
        )
        cls.public_user = cls.env.ref("base.public_user")

    @staticmethod
    def _specification():
        return {
            "name": {},
            "parent_id": {"fields": {"display_name": {}}},
            "sequence": {},
            "active": {},
        }

    def _read(self, domain, *, model=None):
        read_model = model if model is not None else self.Node
        return read_model.occ_treegrid_read(
            domain,
            self._specification(),
            "sequence, id",
        )

    def test_read_injects_ancestors_for_a_deep_match(self):
        result = self._read([("id", "=", self.grandchild.id)])

        self.assertEqual(result["matched_ids"], [self.grandchild.id])
        self.assertEqual(
            set(result["ancestor_ids"]),
            {self.root.id, self.child_a.id},
        )
        self.assertEqual(
            {values["id"] for values in result["records"]},
            {self.root.id, self.child_a.id, self.grandchild.id},
        )
        self.assertEqual(result["parent_field"], "parent_id")
        self.assertEqual(result["sequence_field"], "sequence")

    def test_sample_structure_and_expand_all_view_contract(self):
        self.assertEqual(self.child_a.parent_id, self.root)
        self.assertEqual(self.grandchild.parent_id, self.child_a)
        self.assertEqual(self.child_b.parent_id, self.root)
        self.assertEqual(self.archived_child.parent_id, self.root)
        self.assertFalse(self.archived_child.active)

        view = self.env.ref("occ_treegrid_test.view_occ_treegrid_test_node_list")
        arch = etree.fromstring(view.get_combined_arch())
        name_field = arch.xpath("./field[@name='name']")[0]
        options = safe_eval(name_field.get("options"))

        self.assertEqual(arch.tag, "list")
        self.assertEqual(arch.get("js_class"), "occ_treegrid")
        self.assertEqual(arch.get("default_order"), "sequence,id")
        self.assertEqual(options["occ_treegrid_default_expand"], "all")

    def test_resequence_orders_siblings_and_includes_archived(self):
        result = self.Node.occ_treegrid_resequence(
            self.child_b.id,
            self.child_a.id,
            "before",
        )

        expected_ids = [
            self.child_b.id,
            self.child_a.id,
            self.archived_child.id,
        ]
        self.assertEqual(result["ordered_ids"], expected_ids)
        siblings = self.Node.with_context(active_test=False).search(
            [("parent_id", "=", self.root.id)],
            order="sequence, id",
        )
        self.assertEqual(siblings.ids, expected_ids)
        self.assertEqual(siblings.mapped("sequence"), [10, 20, 30])

    def test_resequence_rejects_cross_parent_move(self):
        with self.assertRaisesRegex(
            UserError,
            "只能在同一个父节点下排序",
        ):
            self.Node.occ_treegrid_resequence(
                self.grandchild.id,
                self.child_b.id,
                "after",
            )

    def test_archive_filtering_and_explicit_archived_read(self):
        hidden = self._read([("id", "=", self.archived_child.id)])
        self.assertEqual(hidden["records"], [])
        self.assertEqual(hidden["matched_ids"], [])

        visible = self._read(
            [("id", "=", self.archived_child.id)],
            model=self.Node.with_context(active_test=False),
        )
        self.assertEqual(visible["matched_ids"], [self.archived_child.id])
        self.assertEqual(visible["ancestor_ids"], [self.root.id])
        self.assertEqual(
            {values["id"] for values in visible["records"]},
            {self.root.id, self.archived_child.id},
        )

    def test_acl_allows_internal_crud_and_rejects_portal_rpc(self):
        InternalNode = self.Node.with_user(self.internal_user)
        created = InternalNode.create(
            {
                "name": "内部用户创建的节点",
                "parent_id": self.root.id,
                "sequence": 90,
            }
        )
        created.write({"note": "ACL 写入验证"})
        self.assertEqual(created.note, "ACL 写入验证")
        created.unlink()
        self.assertFalse(created.exists())

        for user in (self.portal_user, self.public_user):
            RestrictedNode = self.Node.with_user(user)
            with self.assertRaises(AccessError):
                self._read([], model=RestrictedNode)
            with self.assertRaises(AccessError):
                RestrictedNode.create(
                    {
                        "name": f"越权创建 {user.id}",
                        "parent_id": self.root.id,
                        "sequence": 90,
                    }
                )
            with self.assertRaises(AccessError):
                RestrictedNode.browse(self.child_b.id).write(
                    {"name": "不应修改"}
                )
            with self.assertRaises(AccessError):
                RestrictedNode.browse(self.child_b.id).unlink()
            with self.assertRaises(AccessError):
                RestrictedNode.occ_treegrid_resequence(
                    self.child_b.id,
                    self.child_a.id,
                    "before",
                )

    def test_complete_view_action_menu_and_search_contract(self):
        list_view = self.env.ref(
            "occ_treegrid_test.view_occ_treegrid_test_node_list"
        )
        list_arch = etree.fromstring(list_view.get_combined_arch())
        tree_fields = [
            field
            for field in list_arch.xpath("./field")
            if safe_eval(field.get("options", "{}")).get("occ_treegrid_column")
        ]
        parent_fields = [
            field
            for field in list_arch.xpath("./field")
            if safe_eval(field.get("options", "{}")).get("occ_treegrid_parent")
        ]
        handle_fields = list_arch.xpath("./field[@widget='handle']")

        self.assertEqual([field.get("name") for field in tree_fields], ["name"])
        self.assertEqual(
            [field.get("name") for field in parent_fields],
            ["parent_id"],
        )
        self.assertEqual(
            [field.get("name") for field in handle_fields],
            ["sequence"],
        )
        self.assertIsNone(list_arch.get("editable"))
        self.assertIsNone(list_arch.get("multi_edit"))

        action = self.env.ref("occ_treegrid_test.action_occ_treegrid_test_node")
        menu = self.env.ref("occ_treegrid_test.menu_occ_treegrid_test_node")
        self.assertEqual(action.res_model, "occ.treegrid.test.node")
        self.assertEqual(action.view_mode, "list,form")
        self.assertEqual(action.view_id, list_view)
        self.assertEqual(menu.action, action)
        self.assertIn(self.env.ref("base.group_user"), menu.group_ids)

        search_view = self.env.ref(
            "occ_treegrid_test.view_occ_treegrid_test_node_search"
        )
        search_arch = etree.fromstring(search_view.get_combined_arch())
        archived_filter = search_arch.xpath("./filter[@name='archived']")
        self.assertEqual(len(archived_filter), 1)
        self.assertEqual(
            safe_eval(archived_filter[0].get("domain")),
            [("active", "=", False)],
        )

    def test_model_rejects_parent_cycles(self):
        with self.assertRaises(UserError), self.env.cr.savepoint():
            self.root.parent_id = self.grandchild
