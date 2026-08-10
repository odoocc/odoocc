import copy

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, new_test_user

from ..services.definition import ApprovalDefinitionService


class TestApprovalDefinitionValidation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.assignee = new_test_user(
            cls.env,
            login="occ_definition_assignee",
            groups="occ_approval.group_approval_user",
            company_id=cls.company.id,
            company_ids=[Command.set(cls.company.ids)],
        )
        cls.validator = ApprovalDefinitionService(
            cls.env,
            company=cls.company,
            source_model="res.partner",
        )

    def _action_node(self, key, node_type="approval", **values):
        node = {
            "id": key,
            "type": node_type,
            "name": key.replace("_", " ").title(),
            "assignment": {
                "type": "users",
                "user_ids": [self.assignee.id],
            },
        }
        node.update(values)
        return node

    def _diamond_definition(self, timeout_target="gate"):
        join = self._action_node("join")
        if timeout_target:
            join.update(
                {
                    "deadline_hours": 8,
                    "timeout_action": "reject",
                    "timeout_reject_node": timeout_target,
                }
            )
        return {
            "schema_version": 1,
            "nodes": [
                {"id": "end", "type": "end", "name": "End"},
                self._action_node("right", "task"),
                {"id": "start", "type": "start", "name": "Start"},
                join,
                self._action_node("gate"),
                self._action_node("left", "task"),
            ],
            "edges": [
                {
                    "source": "gate",
                    "target": "right",
                    "sequence": 20,
                    "condition": [],
                },
                {
                    "source": "right",
                    "target": "join",
                    "sequence": 10,
                    "condition": [],
                },
                {
                    "source": "start",
                    "target": "gate",
                    "sequence": 10,
                    "condition": [],
                },
                {
                    "source": "gate",
                    "target": "left",
                    "sequence": 10,
                    "condition": [["name", "ilike", "priority"]],
                },
                {
                    "source": "join",
                    "target": "end",
                    "sequence": 10,
                    "condition": [],
                },
                {
                    "source": "left",
                    "target": "join",
                    "sequence": 10,
                    "condition": [],
                },
            ],
        }

    def test_valid_dag_is_normalized_and_routes_condition_before_fallback(self):
        normalized = self.validator.validate(self._diamond_definition())

        self.assertEqual(
            [node["id"] for node in normalized["nodes"]],
            ["start", "gate", "left", "right", "join", "end"],
        )
        self.assertEqual(
            [node["sequence"] for node in normalized["nodes"]],
            [10, 20, 30, 40, 50, 60],
        )
        gate_edges = [
            edge for edge in normalized["edges"] if edge["source"] == "gate"
        ]
        self.assertEqual(
            [(edge["target"], edge["sequence"]) for edge in gate_edges],
            [("left", 10), ("right", 20)],
        )
        self.assertTrue(gate_edges[0]["condition"])
        self.assertFalse(gate_edges[1]["condition"])
        self.assertTrue(
            ApprovalDefinitionService.is_dominator(normalized, "gate", "join")
        )
        self.assertFalse(
            ApprovalDefinitionService.is_dominator(normalized, "left", "join")
        )

    def test_outgoing_routes_require_exactly_one_last_fallback(self):
        no_fallback = self._diamond_definition()
        no_fallback["edges"][0]["condition"] = [["name", "=", "standard"]]

        two_fallbacks = self._diamond_definition()
        two_fallbacks["edges"][3]["condition"] = []

        fallback_not_last = self._diamond_definition()
        fallback_not_last["edges"][0]["sequence"] = 10
        fallback_not_last["edges"][3]["sequence"] = 20

        for label, definition in (
            ("missing fallback", no_fallback),
            ("multiple fallbacks", two_fallbacks),
            ("fallback is not last", fallback_not_last),
        ):
            with self.subTest(label=label), self.assertRaises(ValidationError):
                self.validator.validate(definition)

    def test_duplicate_route_and_duplicate_source_sequence_are_rejected(self):
        duplicate_route = self._diamond_definition()
        duplicate_route["edges"].append(
            {
                "source": "gate",
                "target": "left",
                "sequence": 15,
                "condition": [["name", "ilike", "urgent"]],
            }
        )

        duplicate_sequence = self._diamond_definition()
        duplicate_sequence["edges"][0]["sequence"] = 10

        for label, definition in (
            ("duplicate route", duplicate_route),
            ("duplicate source sequence", duplicate_sequence),
        ):
            with self.subTest(label=label), self.assertRaises(ValidationError):
                self.validator.validate(definition)

    def test_edge_sequence_must_be_a_positive_integer_but_not_boolean(self):
        for sequence in (True, False, 0, -1, 1.5, "10"):
            definition = ApprovalDefinitionService.default_definition()
            definition["edges"][0]["sequence"] = sequence
            with self.subTest(sequence=sequence), self.assertRaises(ValidationError):
                self.validator.validate(definition)

    def test_cycle_is_rejected_even_when_every_route_has_a_fallback(self):
        definition = {
            "schema_version": 1,
            "nodes": [
                {"id": "start", "type": "start", "name": "Start"},
                self._action_node("first"),
                self._action_node("second"),
                {"id": "end", "type": "end", "name": "End"},
            ],
            "edges": [
                {
                    "source": "start",
                    "target": "first",
                    "sequence": 10,
                    "condition": [],
                },
                {
                    "source": "first",
                    "target": "second",
                    "sequence": 10,
                    "condition": [],
                },
                {
                    "source": "second",
                    "target": "first",
                    "sequence": 10,
                    "condition": [["name", "ilike", "repeat"]],
                },
                {
                    "source": "second",
                    "target": "end",
                    "sequence": 20,
                    "condition": [],
                },
            ],
        }

        with self.assertRaises(ValidationError):
            self.validator.validate(definition)

    def test_timeout_reject_target_must_dominate_the_current_node(self):
        normalized = self.validator.validate(self._diamond_definition("gate"))
        self.assertTrue(
            ApprovalDefinitionService.is_dominator(normalized, "gate", "join")
        )

        branch_only_target = self._diamond_definition("left")
        with self.assertRaises(ValidationError):
            self.validator.validate(branch_only_target)

    def test_timeout_reject_rejects_future_copy_and_end_targets(self):
        future_target = self._diamond_definition()
        gate = next(
            node for node in future_target["nodes"] if node["id"] == "gate"
        )
        gate.update(
            {
                "timeout_action": "reject",
                "timeout_reject_node": "join",
            }
        )

        end_target = self._diamond_definition("end")

        copy_target = {
            "schema_version": 1,
            "nodes": [
                {"id": "start", "type": "start", "name": "Start"},
                self._action_node("notice", "copy"),
                self._action_node(
                    "decision",
                    deadline_hours=4,
                    timeout_action="reject",
                    timeout_reject_node="notice",
                ),
                {"id": "end", "type": "end", "name": "End"},
            ],
            "edges": [
                {
                    "source": "start",
                    "target": "notice",
                    "sequence": 10,
                    "condition": [],
                },
                {
                    "source": "notice",
                    "target": "decision",
                    "sequence": 10,
                    "condition": [],
                },
                {
                    "source": "decision",
                    "target": "end",
                    "sequence": 10,
                    "condition": [],
                },
            ],
        }

        for label, definition in (
            ("future", future_target),
            ("copy", copy_target),
            ("end", end_target),
        ):
            with self.subTest(label=label), self.assertRaises(ValidationError):
                self.validator.validate(copy.deepcopy(definition))
