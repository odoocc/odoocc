import copy
import hashlib
import json
import re
from collections import defaultdict, deque

from odoo import _, fields
from odoo.exceptions import ValidationError
from odoo.fields import Domain


SUPPORTED_SCHEMA_VERSION = 1
LEGACY_CHECKSUM_SCHEMA = 1
VERSION_SNAPSHOT_SCHEMA = 2
NODE_TYPES = {"start", "approval", "task", "copy", "end"}
ACTION_NODE_TYPES = {"approval", "task", "copy"}
ASSIGNEE_TYPES = {
    "users",
    "role",
    "manager",
    "manager_chain",
    "requester",
    "requester_choice",
}
ACTION_MODES = {"all", "any"}
TIMEOUT_ACTIONS = {"none", "approve", "reject"}
REJECT_MODES = {"direct", "sequential"}
NODE_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class ApprovalDefinitionService:
    """Validate and normalize an immutable approval graph definition.

    Conditions are JSON-native Odoo domains.  Python expressions and string
    evaluation are deliberately not supported.
    """

    def __init__(self, env, *, company, source_model):
        self.env = env
        self.company = company
        self.source_model_name = source_model
        if source_model not in env:
            raise ValidationError(_("Unsupported source model: %s", source_model))
        self.source_model = env[source_model]

    @staticmethod
    def default_definition():
        return {
            "schema_version": SUPPORTED_SCHEMA_VERSION,
            "nodes": [
                {"id": "start", "type": "start", "name": "Start"},
                {"id": "end", "type": "end", "name": "End"},
            ],
            "edges": [
                {
                    "source": "start",
                    "target": "end",
                    "sequence": 10,
                    "condition": [],
                }
            ],
        }

    @staticmethod
    def checksum(definition):
        canonical = json.dumps(
            definition,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    @classmethod
    def version_snapshot(
        cls,
        *,
        workflow_id,
        company_id,
        version,
        model_name,
        action_key,
        applicability_domain,
        auto_execute,
        definition,
        published_by_id,
        published_at,
    ):
        """Return the complete immutable payload protected by a version checksum."""
        return {
            "checksum_schema": VERSION_SNAPSHOT_SCHEMA,
            "workflow_id": int(workflow_id),
            "company_id": int(company_id),
            "version": int(version),
            "model_name": model_name,
            "action_key": action_key,
            "applicability_domain": applicability_domain or [],
            "auto_execute": bool(auto_execute),
            "definition": definition,
            "published_by_id": int(published_by_id),
            "published_at": fields.Datetime.to_string(published_at),
        }

    @classmethod
    def version_checksum(cls, **snapshot_values):
        return cls.checksum(cls.version_snapshot(**snapshot_values))

    @classmethod
    def checksum_for_version(cls, version):
        version.ensure_one()
        if version.checksum_schema == LEGACY_CHECKSUM_SCHEMA:
            return cls.checksum(version.definition)
        if version.checksum_schema != VERSION_SNAPSHOT_SCHEMA:
            raise ValidationError(
                _("The workflow version uses an unsupported checksum schema.")
            )
        return cls.version_checksum(
            workflow_id=version.workflow_id.id,
            company_id=version.company_id.id,
            version=version.version,
            model_name=version.model_name,
            action_key=version.action_key,
            applicability_domain=version.applicability_domain or [],
            auto_execute=version.auto_execute,
            definition=version.definition,
            published_by_id=version.published_by_id.id,
            published_at=version.published_at,
        )

    def validate(self, definition):
        if not isinstance(definition, dict):
            raise ValidationError(_("The workflow definition must be a JSON object."))

        normalized = copy.deepcopy(definition)
        if normalized.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
            raise ValidationError(
                _(
                    "Unsupported workflow schema version. Expected %s.",
                    SUPPORTED_SCHEMA_VERSION,
                )
            )

        nodes = normalized.get("nodes")
        edges = normalized.get("edges")
        if not isinstance(nodes, list) or not nodes:
            raise ValidationError(_("The workflow must contain nodes."))
        if not isinstance(edges, list):
            raise ValidationError(_("Workflow edges must be a JSON list."))

        node_by_key = {}
        start_keys = []
        end_keys = []
        for position, node in enumerate(nodes):
            self._validate_node(node, position)
            key = node["id"]
            if key in node_by_key:
                raise ValidationError(_("Duplicate node id: %s", key))
            node_by_key[key] = node
            if node["type"] == "start":
                start_keys.append(key)
            elif node["type"] == "end":
                end_keys.append(key)

        if len(start_keys) != 1:
            raise ValidationError(_("A workflow must have exactly one start node."))
        if len(end_keys) != 1:
            raise ValidationError(_("A workflow must have exactly one end node."))

        outgoing = defaultdict(list)
        incoming = defaultdict(list)
        seen_routes = set()
        seen_source_sequences = set()
        for position, edge in enumerate(edges):
            self._validate_edge(edge, position, node_by_key)
            route = (edge["source"], edge["target"])
            if route in seen_routes:
                raise ValidationError(
                    _("Duplicate edge from %(source)s to %(target)s.", **edge)
                )
            source_sequence = (edge["source"], edge["sequence"])
            if source_sequence in seen_source_sequences:
                raise ValidationError(
                    _(
                        "Outgoing edges from node %(source)s must have unique sequences.",
                        source=edge["source"],
                    )
                )
            seen_routes.add(route)
            seen_source_sequences.add(source_sequence)
            outgoing[edge["source"]].append(edge)
            incoming[edge["target"]].append(edge)

        start_key = start_keys[0]
        end_key = end_keys[0]
        if incoming[start_key]:
            raise ValidationError(_("The start node cannot have incoming edges."))
        if outgoing[end_key]:
            raise ValidationError(_("The end node cannot have outgoing edges."))

        for key, node in node_by_key.items():
            if key != start_key and not incoming[key]:
                raise ValidationError(_("Node %s has no incoming edge.", key))
            if key != end_key and not outgoing[key]:
                raise ValidationError(_("Node %s has no outgoing edge.", key))
            self._validate_outgoing_edges(key, outgoing[key])

        topological_keys = self._topological_sort(node_by_key, outgoing, incoming)
        reachable = self._reachable_from(start_key, outgoing)
        if reachable != set(node_by_key):
            missing = ", ".join(sorted(set(node_by_key) - reachable))
            raise ValidationError(_("Nodes are not reachable from start: %s", missing))

        can_reach_end = self._can_reach_end(end_key, incoming)
        if can_reach_end != set(node_by_key):
            missing = ", ".join(sorted(set(node_by_key) - can_reach_end))
            raise ValidationError(_("Nodes cannot reach the end node: %s", missing))

        order_by_key = {key: index + 1 for index, key in enumerate(topological_keys)}
        dominators = self._dominators(start_key, topological_keys, incoming)
        for node in nodes:
            if node.get("timeout_action") != "reject":
                continue
            node_key = node["id"]
            target_key = node["timeout_reject_node"]
            target = node_by_key.get(target_key)
            if not target:
                raise ValidationError(
                    _(
                        "Node %(node)s references an unknown timeout rejection target: %(target)s.",
                        node=node_key,
                        target=target_key,
                    )
                )
            if order_by_key[target_key] >= order_by_key[node_key]:
                raise ValidationError(
                    _(
                        "The timeout rejection target of node %(node)s must be an earlier node.",
                        node=node_key,
                    )
                )
            if target["type"] in {"copy", "end"}:
                raise ValidationError(
                    _(
                        "The timeout rejection target of node %(node)s cannot be a copy or end node.",
                        node=node_key,
                    )
                )
            if target_key not in dominators[node_key]:
                raise ValidationError(
                    _(
                        "The timeout rejection target of node %(node)s must occur on every path to that node.",
                        node=node_key,
                    )
                )
        for node in nodes:
            node["sequence"] = order_by_key[node["id"]] * 10
        for key in outgoing:
            outgoing[key].sort(key=lambda edge: (edge["sequence"], edge["target"]))

        normalized["nodes"] = sorted(nodes, key=lambda node: node["sequence"])
        normalized["edges"] = sorted(
            edges,
            key=lambda edge: (
                order_by_key[edge["source"]],
                edge["sequence"],
                edge["target"],
            ),
        )
        return normalized

    def _validate_node(self, node, position):
        if not isinstance(node, dict):
            raise ValidationError(_("Node %s must be a JSON object.", position + 1))
        key = node.get("id")
        if not isinstance(key, str) or not NODE_KEY_RE.fullmatch(key):
            raise ValidationError(_("Invalid node id at position %s.", position + 1))
        node_type = node.get("type")
        if node_type not in NODE_TYPES:
            raise ValidationError(_("Unsupported node type on %s: %s", key, node_type))
        name = node.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValidationError(_("Node %s must have a name.", key))
        node["name"] = name.strip()

        if node_type not in ACTION_NODE_TYPES:
            for forbidden in ("assignment", "mode", "deadline_hours", "timeout_action"):
                if node.get(forbidden) not in (None, False, "", [], {}):
                    raise ValidationError(
                        _("Node %(node)s cannot define %(field)s.", node=key, field=forbidden)
                    )
            return

        assignment = node.get("assignment")
        if not isinstance(assignment, dict):
            raise ValidationError(_("Node %s must define an assignment object.", key))
        self._validate_assignment(key, assignment)

        if node_type in {"approval", "task"}:
            mode = node.setdefault("mode", "all")
            if mode not in ACTION_MODES:
                raise ValidationError(_("Node %s has an invalid action mode.", key))
            deadline_hours = node.setdefault("deadline_hours", 0)
            reminder_before_hours = node.setdefault("reminder_before_hours", 0)
            if not isinstance(deadline_hours, (int, float)) or deadline_hours < 0:
                raise ValidationError(_("Node %s has an invalid deadline.", key))
            if (
                not isinstance(reminder_before_hours, (int, float))
                or reminder_before_hours < 0
                or (deadline_hours and reminder_before_hours > deadline_hours)
            ):
                raise ValidationError(_("Node %s has an invalid reminder window.", key))
            timeout_action = node.setdefault("timeout_action", "none")
            if timeout_action not in TIMEOUT_ACTIONS:
                raise ValidationError(_("Node %s has an invalid timeout action.", key))
            if timeout_action == "reject":
                target = node.get("timeout_reject_node")
                mode = node.setdefault("timeout_reject_mode", "sequential")
                if not isinstance(target, str) or not target:
                    raise ValidationError(
                        _("Node %s must define timeout_reject_node.", key)
                    )
                if mode not in REJECT_MODES:
                    raise ValidationError(
                        _("Node %s has an invalid timeout rejection mode.", key)
                    )
        else:
            node.pop("mode", None)
            node.pop("deadline_hours", None)
            node.pop("reminder_before_hours", None)
            node.pop("timeout_action", None)

    def _validate_assignment(self, node_key, assignment):
        assignee_type = assignment.get("type")
        if assignee_type not in ASSIGNEE_TYPES:
            raise ValidationError(_("Node %s has an invalid assignee type.", node_key))

        if assignee_type == "users":
            user_ids = assignment.get("user_ids")
            if not isinstance(user_ids, list) or not user_ids:
                raise ValidationError(_("Node %s must define assigned users.", node_key))
            self._validate_users(node_key, user_ids)
            assignment["user_ids"] = sorted(set(int(user_id) for user_id in user_ids))
        elif assignee_type == "role":
            role_id = assignment.get("role_id")
            if not isinstance(role_id, int) or role_id <= 0:
                raise ValidationError(_("Node %s must define an approval role.", node_key))
            role = self.env["occ.approval.role"].sudo().browse(role_id).exists()
            if not role or role.company_id != self.company or not role.active:
                raise ValidationError(_("Node %s uses an unavailable approval role.", node_key))
        elif assignee_type == "manager":
            level = assignment.setdefault("level", 1)
            if not isinstance(level, int) or level < 1 or level > 100:
                raise ValidationError(_("Node %s has an invalid manager level.", node_key))
        elif assignee_type == "manager_chain":
            levels = assignment.setdefault("levels", 0)
            if not isinstance(levels, int) or levels < 0 or levels > 100:
                raise ValidationError(_("Node %s has an invalid manager chain.", node_key))

    def _validate_users(self, node_key, user_ids):
        if any(not isinstance(user_id, int) or user_id <= 0 for user_id in user_ids):
            raise ValidationError(_("Node %s contains an invalid user id.", node_key))
        users = self.env["res.users"].sudo().browse(user_ids).exists()
        if set(users.ids) != set(user_ids):
            raise ValidationError(_("Node %s references a missing user.", node_key))
        invalid = users.filtered(
            lambda user: not user.active
            or user.share
            or self.company not in user.company_ids
        )
        if invalid:
            raise ValidationError(
                _("Node %(node)s contains unavailable users: %(users)s", node=node_key, users=", ".join(invalid.mapped("name")))
            )

    def _validate_edge(self, edge, position, node_by_key):
        if not isinstance(edge, dict):
            raise ValidationError(_("Edge %s must be a JSON object.", position + 1))
        source = edge.get("source")
        target = edge.get("target")
        if source not in node_by_key or target not in node_by_key:
            raise ValidationError(_("Edge %s references an unknown node.", position + 1))
        if source == target:
            raise ValidationError(_("A node cannot link to itself: %s", source))
        sequence = edge.setdefault("sequence", (position + 1) * 10)
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence <= 0:
            raise ValidationError(_("Edge %s has an invalid sequence.", position + 1))
        label = edge.get("label")
        if label is not None:
            if not isinstance(label, str):
                raise ValidationError(_("Edge %s label must be text.", position + 1))
            label = label.strip()
            if len(label) > 120:
                raise ValidationError(_("Edge %s label is too long.", position + 1))
            if label:
                edge["label"] = label
            else:
                edge.pop("label", None)
        condition = edge.setdefault("condition", [])
        if not isinstance(condition, list):
            raise ValidationError(_("Edge %s condition must be a native domain list.", position + 1))
        try:
            Domain(condition).validate(self.source_model)
        except Exception as error:
            raise ValidationError(
                _("Invalid condition on edge %(source)s -> %(target)s: %(error)s", source=source, target=target, error=error)
            ) from error

    def _validate_outgoing_edges(self, node_key, edges):
        if not edges:
            return
        unconditional = [edge for edge in edges if not edge["condition"]]
        if len(unconditional) != 1:
            raise ValidationError(
                _("Node %s must have exactly one fallback edge.", node_key)
            )
        fallback = unconditional[0]
        if fallback["sequence"] != max(edge["sequence"] for edge in edges):
            raise ValidationError(
                _("The fallback edge of node %s must have the highest sequence.", node_key)
            )

    def _topological_sort(self, node_by_key, outgoing, incoming):
        indegree = {key: len(incoming[key]) for key in node_by_key}
        queue = deque(sorted(key for key, degree in indegree.items() if degree == 0))
        ordered = []
        while queue:
            key = queue.popleft()
            ordered.append(key)
            for edge in sorted(outgoing[key], key=lambda item: (item["sequence"], item["target"])):
                target = edge["target"]
                indegree[target] -= 1
                if indegree[target] == 0:
                    queue.append(target)
        if len(ordered) != len(node_by_key):
            raise ValidationError(_("The workflow graph must be acyclic."))
        return ordered

    @staticmethod
    def _dominators(start_key, ordered_keys, incoming):
        """Compute graph dominators in topological order for the validated DAG."""
        all_keys = set(ordered_keys)
        dominators = {start_key: {start_key}}
        for key in ordered_keys:
            if key == start_key:
                continue
            predecessors = [edge["source"] for edge in incoming[key]]
            common = set(all_keys)
            for predecessor in predecessors:
                common.intersection_update(dominators[predecessor])
            dominators[key] = common | {key}
        return dominators

    @staticmethod
    def is_dominator(definition, dominator_key, node_key):
        """Check a published graph without trusting its stored node sequence."""
        nodes = definition.get("nodes") if isinstance(definition, dict) else None
        edges = definition.get("edges") if isinstance(definition, dict) else None
        if not isinstance(nodes, list) or not isinstance(edges, list):
            return False
        node_keys = {
            node.get("id")
            for node in nodes
            if isinstance(node, dict) and isinstance(node.get("id"), str)
        }
        starts = [
            node.get("id")
            for node in nodes
            if isinstance(node, dict) and node.get("type") == "start"
        ]
        if (
            len(starts) != 1
            or dominator_key not in node_keys
            or node_key not in node_keys
        ):
            return False
        start_key = starts[0]
        if dominator_key == start_key:
            return True
        outgoing = defaultdict(list)
        for edge in edges:
            if not isinstance(edge, dict):
                return False
            source = edge.get("source")
            target = edge.get("target")
            if source not in node_keys or target not in node_keys:
                return False
            outgoing[source].append(target)

        visited = set()
        stack = [start_key]
        while stack:
            key = stack.pop()
            if key == dominator_key or key in visited:
                continue
            if key == node_key:
                return False
            visited.add(key)
            stack.extend(outgoing[key])
        return True

    @staticmethod
    def _reachable_from(start_key, outgoing):
        reachable = set()
        stack = [start_key]
        while stack:
            key = stack.pop()
            if key in reachable:
                continue
            reachable.add(key)
            stack.extend(edge["target"] for edge in outgoing[key])
        return reachable

    @staticmethod
    def _can_reach_end(end_key, incoming):
        reachable = set()
        stack = [end_key]
        while stack:
            key = stack.pop()
            if key in reachable:
                continue
            reachable.add(key)
            stack.extend(edge["source"] for edge in incoming[key])
        return reachable
