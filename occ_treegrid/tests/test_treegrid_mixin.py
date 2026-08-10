from contextlib import contextmanager
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from ..models.treegrid_mixin import OccTreegridMixin


@tagged("post_install", "-at_install")
class TestOccTreegridMixin(TransactionCase):
    """使用 res.partner 原生层级结构验证通用实现。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env["res.partner"]
        cls.readonly_user = new_test_user(
            cls.env,
            login="occ_treegrid_readonly",
            groups="base.group_user",
        )

    @contextmanager
    def _configured_partner(
        self,
        max_nodes=2000,
        parent_field="parent_id",
        sequence_field="color",
    ):
        model_class = type(self.Partner)
        with (
            patch.object(
                model_class,
                "_occ_treegrid_parent_field",
                parent_field,
                create=True,
            ),
            patch.object(
                model_class,
                "_occ_treegrid_sequence_field",
                sequence_field,
                create=True,
            ),
            patch.object(
                model_class,
                "_occ_treegrid_max_nodes",
                max_nodes,
                create=True,
            ),
        ):
            yield self.Partner

    def _read(self, model, domain, order="color, id"):
        return OccTreegridMixin.occ_treegrid_read(
            model,
            domain,
            {
                "name": {},
                "parent_id": {"fields": {"display_name": {}}},
                "color": {},
            },
            order,
        )

    def _resequence(self, model, moved, target, position):
        return OccTreegridMixin.occ_treegrid_resequence(
            model, moved.id, target.id, position
        )

    def test_read_adds_readable_ancestors_and_marks_matches(self):
        root = self.Partner.create({"name": "TreeGrid root", "color": 30})
        branch = self.Partner.create(
            {"name": "TreeGrid branch", "parent_id": root.id, "color": 20}
        )
        leaf = self.Partner.create(
            {"name": "TreeGrid leaf", "parent_id": branch.id, "color": 10}
        )

        with self._configured_partner() as model:
            result = self._read(model, [("id", "=", leaf.id)])

        self.assertEqual(result["matched_ids"], [leaf.id])
        self.assertEqual(set(result["ancestor_ids"]), {root.id, branch.id})
        self.assertEqual(
            {record["id"] for record in result["records"]},
            {root.id, branch.id, leaf.id},
        )
        leaf_values = next(
            record for record in result["records"] if record["id"] == leaf.id
        )
        self.assertEqual(leaf_values["parent_id"]["id"], branch.id)
        self.assertEqual(result["parent_field"], "parent_id")
        self.assertEqual(result["sequence_field"], "color")
        self.assertEqual(result["length"], 3)

    def test_read_does_not_force_an_inactive_ancestor(self):
        archived_root = self.Partner.create(
            {"name": "Archived TreeGrid root", "color": 10, "active": False}
        )
        leaf = self.Partner.create(
            {
                "name": "Visible TreeGrid leaf",
                "parent_id": archived_root.id,
                "color": 20,
            }
        )

        with self._configured_partner() as model:
            result = self._read(model, [("id", "=", leaf.id)])

        self.assertEqual(result["matched_ids"], [leaf.id])
        self.assertEqual(result["ancestor_ids"], [])
        self.assertEqual(result["orphan_ids"], [leaf.id])
        self.assertEqual([record["id"] for record in result["records"]], [leaf.id])
        self.assertFalse(result["records"][0]["parent_id"])
        self.assertNotIn(archived_root.name, str(result["records"]))

    def test_read_limit_counts_injected_ancestors(self):
        root = self.Partner.create({"name": "Limited root", "color": 10})
        leaves = self.Partner.create(
            [
                {"name": "Limited leaf A", "parent_id": root.id, "color": 20},
                {"name": "Limited leaf B", "parent_id": root.id, "color": 30},
            ]
        )

        with self._configured_partner(max_nodes=2) as model, self.assertRaises(
            UserError
        ):
            self._read(model, [("id", "in", leaves.ids)])

    def test_invalid_model_configuration_is_rejected(self):
        with self._configured_partner(
            parent_field="company_id"
        ) as model, self.assertRaises(UserError):
            self._read(model, [])
        with self._configured_partner(
            sequence_field="name"
        ) as model, self.assertRaises(UserError):
            self._read(model, [])
        with self._configured_partner(max_nodes=0) as model, self.assertRaises(
            UserError
        ):
            self._read(model, [])
        with patch.object(
            self.Partner._fields["color"], "store", False
        ), self._configured_partner() as model, self.assertRaises(UserError):
            self._read(model, [])

    def test_resequence_normalises_active_and_inactive_siblings(self):
        parent = self.Partner.create({"name": "Resequence parent"})
        first = self.Partner.create(
            {"name": "First", "parent_id": parent.id, "color": 10}
        )
        archived = self.Partner.create(
            {
                "name": "Archived",
                "parent_id": parent.id,
                "color": 20,
                "active": False,
            }
        )
        last = self.Partner.create(
            {"name": "Last", "parent_id": parent.id, "color": 30}
        )

        with self._configured_partner() as model:
            result = self._resequence(model, last, first, "before")

        all_children = self.Partner.with_context(active_test=False).browse(
            [last.id, first.id, archived.id]
        )
        all_children.invalidate_recordset(["color"])
        self.assertEqual(result["ordered_ids"], [last.id, first.id, archived.id])
        self.assertEqual(last.color, 10)
        self.assertEqual(first.color, 20)
        self.assertEqual(archived.color, 30)

    def test_resequence_rejects_a_sibling_set_over_the_node_limit(self):
        parent = self.Partner.create({"name": "Oversized parent"})
        first, second, third = self.Partner.create(
            [
                {"name": "Oversized first", "parent_id": parent.id, "color": 10},
                {"name": "Oversized second", "parent_id": parent.id, "color": 20},
                {"name": "Oversized third", "parent_id": parent.id, "color": 30},
            ]
        )

        with self._configured_partner(max_nodes=2) as model, self.assertRaises(
            UserError
        ):
            self._resequence(model, third, first, "before")

        (first | second | third).invalidate_recordset(["color"])
        self.assertEqual((first.color, second.color, third.color), (10, 20, 30))

    def test_resequence_rejects_cross_parent_and_readonly_access(self):
        parent_a, parent_b = self.Partner.create(
            [{"name": "Parent A"}, {"name": "Parent B"}]
        )
        child_a = self.Partner.create(
            {"name": "Child A", "parent_id": parent_a.id, "color": 10}
        )
        child_b = self.Partner.create(
            {"name": "Child B", "parent_id": parent_b.id, "color": 10}
        )

        with self._configured_partner() as model:
            with self.assertRaises(UserError):
                self._resequence(model, child_a, child_b, "after")
            with self.assertRaises(AccessError):
                self._resequence(
                    model.with_user(self.readonly_user), child_a, child_b, "after"
                )
            with self.assertRaises(AccessError):
                OccTreegridMixin.occ_treegrid_resequence(
                    model, float("inf"), child_a.id, "after"
                )

    def test_resequence_rolls_back_all_writes_on_failure(self):
        parent = self.Partner.create({"name": "Atomic parent"})
        first, second, third = self.Partner.create(
            [
                {"name": "Atomic first", "parent_id": parent.id, "color": 10},
                {"name": "Atomic second", "parent_id": parent.id, "color": 20},
                {"name": "Atomic third", "parent_id": parent.id, "color": 30},
            ]
        )
        model_class = type(self.Partner)
        original_write = model_class.write
        write_count = 0

        def failing_write(records, values):
            nonlocal write_count
            write_count += 1
            if write_count == 2:
                raise UserError("模拟写入失败")
            return original_write(records, values)

        with self._configured_partner() as model, patch.object(
            model_class, "write", failing_write
        ), self.assertRaises(UserError):
            self._resequence(model, third, first, "before")

        (first | second | third).invalidate_recordset(["color"])
        self.assertEqual((first.color, second.color, third.color), (10, 20, 30))
