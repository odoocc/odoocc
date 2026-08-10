/** @odoo-module **/

import { Component, onMounted, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { useSetupAction } from "@web/search/action_hook";

import { approvalErrorMessage } from "../../api";

const SCHEMA_VERSION = 1;
const NODE_WIDTH = 208;
const NODE_HEIGHT = 104;
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 1.75;

const NODE_TYPES = Object.freeze({
    start: { label: _t("Start"), icon: "fa-play", color: "success" },
    approval: { label: _t("Approval"), icon: "fa-check", color: "primary" },
    task: { label: _t("Task"), icon: "fa-briefcase", color: "warning" },
    copy: { label: _t("Copy"), icon: "fa-paper-plane", color: "info" },
    end: { label: _t("End"), icon: "fa-stop", color: "secondary" },
});

let sequence = 0;

function uniqueId(prefix) {
    sequence += 1;
    return `${prefix}_${Date.now().toString(36)}_${sequence.toString(36)}`;
}

function copy(value) {
    return JSON.parse(JSON.stringify(value));
}

function defaultConfig(type) {
    if (type === "start") {
        return {};
    }
    if (type === "approval") {
        return {
            assignee_mode: "users",
            user_ids: [],
            role_id: 0,
            role_ids: [],
            manager_level: 1,
            manager_chain_levels: 0,
            approval_mode: "all",
            deadline_hours: 0,
            reminder_before_hours: 0,
            timeout_action: "none",
            timeout_reject_node: "",
            timeout_reject_mode: "sequential",
        };
    }
    if (type === "task") {
        return {
            assignee_mode: "users",
            user_ids: [],
            role_id: 0,
            role_ids: [],
            manager_level: 1,
            manager_chain_levels: 0,
            completion_mode: "all",
            deadline_hours: 0,
            reminder_before_hours: 0,
            timeout_action: "none",
            timeout_reject_node: "",
            timeout_reject_mode: "sequential",
        };
    }
    if (type === "copy") {
        return {
            assignee_mode: "users",
            user_ids: [],
            role_id: 0,
            role_ids: [],
            manager_level: 1,
            manager_chain_levels: 0,
        };
    }
    return {};
}

function defaultNode(type, index = 0) {
    return {
        id: uniqueId(type),
        type,
        label: NODE_TYPES[type].label,
        description: "",
        position: { x: 120 + index * 280, y: 160 },
        config: defaultConfig(type),
    };
}

function initialGraph() {
    const start = defaultNode("start", 0);
    const end = defaultNode("end", 1);
    return {
        schema_version: SCHEMA_VERSION,
        nodes: [start, end],
        edges: [
            {
                id: uniqueId("edge"),
                source: start.id,
                target: end.id,
                sequence: 10,
                condition: {
                    label: "",
                    custom_label: false,
                    field: "",
                    operator: "=",
                    value: "",
                    value_type: "string",
                },
            },
        ],
    };
}

function normalizeGraph(graph) {
    if (!graph?.nodes?.length) {
        return initialGraph();
    }
    const nodes = graph.nodes.map((node, index) => ({
        id: node.id || uniqueId(node.type || "node"),
        type: NODE_TYPES[node.type] ? node.type : "task",
        label: node.label || NODE_TYPES[node.type]?.label || _t("Task"),
        description: node.description || "",
        position: {
            x: Number(node.position?.x ?? 120 + index * 280),
            y: Number(node.position?.y ?? 160),
        },
        config: { ...defaultConfig(node.type), ...(node.config || {}) },
    }));
    const nodeIds = new Set(nodes.map((node) => node.id));
    const edges = (graph.edges || [])
        .filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))
        .map((edge, index) => ({
            id: edge.id || uniqueId("edge"),
            source: edge.source,
            target: edge.target,
            sequence: Number(edge.sequence || (index + 1) * 10),
            condition: {
                label: edge.condition?.label || "",
                custom_label: Boolean(edge.condition?.custom_label),
                field: edge.condition?.field || "",
                operator: edge.condition?.operator || "=",
                value: edge.condition?.value ?? "",
                value_type:
                    edge.condition?.value_type ||
                    (edge.condition?.advanced ? "json" : "string"),
                advanced: Boolean(edge.condition?.advanced),
            },
        }));
    return { schema_version: Number(graph.schema_version || SCHEMA_VERSION), nodes, edges };
}

export class ApprovalDesigner extends Component {
    static template = "occ_approval.ApprovalDesigner";
    static props = {
        action: Object,
        actionId: { type: Number, optional: true },
        className: { type: String, optional: true },
        globalState: { type: Object, optional: true },
        state: { type: Object, optional: true },
        resId: { type: [Number, Boolean], optional: true },
        updateActionState: { type: Function, optional: true },
    };

    setup() {
        this.api = useService("occ_approval_api");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.canvasRef = useRef("canvas");
        const context = this.props.action?.context || {};
        this.workflowId =
            context.active_id || context.workflow_id || this.props.action?.params?.workflow_id || false;
        this.nodeTypes = NODE_TYPES;
        this.nodeTypeOrder = ["start", "approval", "task", "copy", "end"];
        this.state = useState({
            loading: true,
            saving: false,
            publishing: false,
            dirty: false,
            workflowName: _t("Approval workflow"),
            workflowState: "draft",
            revision: 0,
            companyId: 0,
            graph: initialGraph(),
            selectedNodeId: null,
            selectedEdgeId: null,
            linkSourceId: null,
            zoom: 1,
            panX: 0,
            panY: 0,
            validationErrors: [],
            assignmentUserQuery: "",
            assignmentUsers: [],
            assignmentRoles: [],
            assignmentOptionsLoading: false,
        });
        this.pointerGesture = null;
        this.beforeUnload = (ev) => {
            if (!this.state.dirty) {
                return;
            }
            ev.preventDefault();
            ev.returnValue = "";
        };

        useSetupAction({ beforeLeave: (options) => this.beforeLeave(options) });
        onWillStart(() => this.load());
        onMounted(() => browser.addEventListener("beforeunload", this.beforeUnload));
        onWillUnmount(() => browser.removeEventListener("beforeunload", this.beforeUnload));
    }

    async load() {
        this.state.loading = true;
        try {
            if (!this.workflowId) {
                this.state.graph = initialGraph();
                this.state.workflowName = _t("New approval workflow");
                return;
            }
            const payload = await this.api.getDesignerData(this.workflowId);
            this.state.workflowName = payload.name;
            this.state.workflowState = payload.state;
            this.state.revision = payload.revision;
            this.state.companyId = payload.companyId;
            this.state.graph = normalizeGraph(payload.graph);
            await this.loadAssignmentOptions();
            this.state.dirty = false;
        } catch (error) {
            this.notifyError(error);
        } finally {
            this.state.loading = false;
        }
    }

    get selectedNode() {
        return this.state.graph.nodes.find((node) => node.id === this.state.selectedNodeId) || null;
    }

    get selectedEdge() {
        return this.state.graph.edges.find((edge) => edge.id === this.state.selectedEdgeId) || null;
    }

    get selectedAssignmentUsers() {
        const selectedIds = this.selectedNode?.config?.user_ids || [];
        return selectedIds.map((id) => {
            return (
                this.state.assignmentUsers.find((user) => Number(user.id) === Number(id)) || {
                    id,
                    name: _t("Unavailable user"),
                }
            );
        });
    }

    get assignmentUserResults() {
        const query = this.state.assignmentUserQuery.trim().toLocaleLowerCase();
        if (!query) {
            return this.state.assignmentUsers.slice(0, 50);
        }
        return this.state.assignmentUsers
            .filter((user) =>
                [user.name, user.login, user.email].some((value) =>
                    String(value || "").toLocaleLowerCase().includes(query)
                )
            )
            .slice(0, 50);
    }

    mergeAssignmentUsers(...groups) {
        const byId = new Map(this.state.assignmentUsers.map((user) => [Number(user.id), user]));
        for (const group of groups) {
            for (const user of group || []) {
                if (user?.id) {
                    byId.set(Number(user.id), user);
                }
            }
        }
        this.state.assignmentUsers = [...byId.values()].sort((a, b) =>
            String(a.name || "").localeCompare(String(b.name || ""))
        );
    }

    async loadAssignmentOptions() {
        if (!this.state.companyId) {
            return;
        }
        this.state.assignmentOptionsLoading = true;
        const selectedIds = this.state.graph.nodes.flatMap((node) => node.config?.user_ids || []);
        try {
            const [roles, users, selectedUsers] = await Promise.all([
                this.api.getDesignerRoles(this.state.companyId),
                this.api.searchDesignerUsers(this.state.companyId, "", 50),
                this.api.getDesignerUsersByIds(this.state.companyId, selectedIds),
            ]);
            this.state.assignmentRoles = roles;
            this.mergeAssignmentUsers(users, selectedUsers);
        } catch (error) {
            this.notifyError(error);
        } finally {
            this.state.assignmentOptionsLoading = false;
        }
    }

    updateAssignmentUserQuery(ev) {
        this.state.assignmentUserQuery = ev.target.value;
    }

    async searchAssignmentUsers(ev) {
        ev?.preventDefault();
        if (!this.state.companyId || this.state.assignmentOptionsLoading) {
            return;
        }
        this.state.assignmentOptionsLoading = true;
        try {
            const users = await this.api.searchDesignerUsers(
                this.state.companyId,
                this.state.assignmentUserQuery,
                50
            );
            this.mergeAssignmentUsers(users);
        } catch (error) {
            this.notifyError(error);
        } finally {
            this.state.assignmentOptionsLoading = false;
        }
    }

    isAssignmentUserSelected(userId) {
        return (this.selectedNode?.config?.user_ids || []).includes(Number(userId));
    }

    toggleAssignmentUser(userId) {
        if (!this.selectedNode) {
            return;
        }
        const id = Number(userId);
        const current = this.selectedNode.config.user_ids || [];
        this.selectedNode.config.user_ids = current.includes(id)
            ? current.filter((item) => item !== id)
            : [...current, id];
        this.markDirty();
    }

    removeAssignmentUser(userId) {
        if (!this.selectedNode) {
            return;
        }
        const id = Number(userId);
        this.selectedNode.config.user_ids = (this.selectedNode.config.user_ids || []).filter(
            (item) => Number(item) !== id
        );
        this.markDirty();
    }

    selectAssignmentRole(ev) {
        if (!this.selectedNode) {
            return;
        }
        const roleId = Number(ev.target.value || 0);
        this.selectedNode.config.role_id = roleId;
        this.selectedNode.config.role_ids = roleId ? [roleId] : [];
        this.markDirty();
    }

    isAssignmentRoleSelected(roleId) {
        return (
            Number(this.selectedNode?.config?.role_id || this.selectedNode?.config?.role_ids?.[0]) ===
            Number(roleId)
        );
    }

    get canvasSize() {
        const bounds = this.graphBounds();
        return {
            width: Math.max(1400, bounds.maxX + 360),
            height: Math.max(800, bounds.maxY + 260),
        };
    }

    get sceneStyle() {
        const size = this.canvasSize;
        return [
            `width:${size.width}px`,
            `height:${size.height}px`,
            `transform:translate(${this.state.panX}px, ${this.state.panY}px) scale(${this.state.zoom})`,
        ].join(";");
    }

    get zoomLabel() {
        return `${Math.round(this.state.zoom * 100)}%`;
    }

    graphBounds() {
        if (!this.state.graph.nodes.length) {
            return { minX: 0, minY: 0, maxX: 1000, maxY: 600 };
        }
        const xs = this.state.graph.nodes.map((node) => node.position.x);
        const ys = this.state.graph.nodes.map((node) => node.position.y);
        return {
            minX: Math.min(...xs),
            minY: Math.min(...ys),
            maxX: Math.max(...xs) + NODE_WIDTH,
            maxY: Math.max(...ys) + NODE_HEIGHT,
        };
    }

    nodeStyle(node) {
        return `transform:translate(${node.position.x}px, ${node.position.y}px)`;
    }

    edgePath(edge) {
        const source = this.state.graph.nodes.find((node) => node.id === edge.source);
        const target = this.state.graph.nodes.find((node) => node.id === edge.target);
        if (!source || !target) {
            return "";
        }
        const sx = source.position.x + NODE_WIDTH;
        const sy = source.position.y + NODE_HEIGHT / 2;
        const tx = target.position.x;
        const ty = target.position.y + NODE_HEIGHT / 2;
        const bend = Math.max(80, Math.abs(tx - sx) * 0.45);
        const direction = tx >= sx ? 1 : -1;
        return `M ${sx} ${sy} C ${sx + bend * direction} ${sy}, ${tx - bend * direction} ${ty}, ${tx} ${ty}`;
    }

    edgeLabelPosition(edge) {
        const source = this.state.graph.nodes.find((node) => node.id === edge.source);
        const target = this.state.graph.nodes.find((node) => node.id === edge.target);
        if (!source || !target) {
            return { x: 0, y: 0 };
        }
        return {
            x: (source.position.x + NODE_WIDTH + target.position.x) / 2,
            y: (source.position.y + target.position.y + NODE_HEIGHT) / 2 - 8,
        };
    }

    nodeTypeLabel(type) {
        return NODE_TYPES[type]?.label || type;
    }

    canAddType(type) {
        return !["start", "end"].includes(type) || !this.state.graph.nodes.some((node) => node.type === type);
    }

    nodeName(nodeId) {
        return this.state.graph.nodes.find((node) => node.id === nodeId)?.label || nodeId;
    }

    edgeSummary(edge) {
        if (edge.condition?.custom_label && edge.condition.label) {
            return edge.condition.label;
        }
        if (edge.condition?.advanced) {
            return _t("Advanced condition");
        }
        if (!edge.condition?.field) {
            return _t("Fallback");
        }
        return `${edge.condition.field} ${edge.condition.operator} ${edge.condition.value}`;
    }

    markDirty() {
        this.state.dirty = true;
        this.state.validationErrors = [];
    }

    selectNode(node) {
        if (this.state.linkSourceId && this.state.linkSourceId !== node.id) {
            this.addEdge(this.state.linkSourceId, node.id);
            this.state.linkSourceId = null;
            return;
        }
        this.state.selectedNodeId = node.id;
        this.state.selectedEdgeId = null;
    }

    selectEdge(edge, ev) {
        ev.stopPropagation();
        this.state.selectedEdgeId = edge.id;
        this.state.selectedNodeId = null;
        this.state.linkSourceId = null;
    }

    clearSelection() {
        this.state.selectedNodeId = null;
        this.state.selectedEdgeId = null;
        this.state.linkSourceId = null;
    }

    addNode(type) {
        if ((type === "start" || type === "end") && this.state.graph.nodes.some((n) => n.type === type)) {
            this.notification.add(_t("A workflow can only contain one start and one end node."), {
                type: "warning",
            });
            return;
        }
        const bounds = this.graphBounds();
        const node = defaultNode(type);
        node.position = { x: bounds.maxX + 140, y: Math.max(120, bounds.minY) };
        this.state.graph.nodes.push(node);
        this.state.selectedNodeId = node.id;
        this.state.selectedEdgeId = null;
        this.markDirty();
    }

    requestDeleteSelection() {
        const node = this.selectedNode;
        const edge = this.selectedEdge;
        if (!node && !edge) {
            return;
        }
        if (node && ["start", "end"].includes(node.type)) {
            this.notification.add(_t("Start and end nodes cannot be deleted."), { type: "warning" });
            return;
        }
        this.dialog.add(ConfirmationDialog, {
            title: _t("Delete selection"),
            body: node
                ? _t("Delete this node and all of its connections?")
                : _t("Delete this connection?"),
            confirmLabel: _t("Delete"),
            confirmClass: "btn-danger",
            confirm: () => this.deleteSelection(),
        });
    }

    deleteSelection() {
        if (this.selectedNode) {
            const nodeId = this.selectedNode.id;
            this.state.graph.nodes = this.state.graph.nodes.filter((node) => node.id !== nodeId);
            this.state.graph.edges = this.state.graph.edges.filter(
                (edge) => edge.source !== nodeId && edge.target !== nodeId
            );
        } else if (this.selectedEdge) {
            const edgeId = this.selectedEdge.id;
            this.state.graph.edges = this.state.graph.edges.filter((edge) => edge.id !== edgeId);
        }
        this.clearSelection();
        this.markDirty();
    }

    startLink(node, ev) {
        ev.stopPropagation();
        if (node.type === "end") {
            return;
        }
        this.state.linkSourceId = node.id;
        this.state.selectedNodeId = node.id;
        this.state.selectedEdgeId = null;
        this.notification.add(_t("Select the destination node."), { type: "info" });
    }

    addEdge(sourceId, targetId) {
        if (sourceId === targetId) {
            return;
        }
        if (this.state.graph.edges.some((edge) => edge.source === sourceId && edge.target === targetId)) {
            this.notification.add(_t("This connection already exists."), { type: "warning" });
            return;
        }
        const edge = {
            id: uniqueId("edge"),
            source: sourceId,
            target: targetId,
            sequence:
                Math.max(
                    0,
                    ...this.state.graph.edges
                        .filter((item) => item.source === sourceId)
                        .map((item) => Number(item.sequence || 0))
                ) + 10,
            condition: {
                label: "",
                custom_label: false,
                field: "id",
                operator: "!=",
                value: "0",
                value_type: "number",
            },
        };
        this.state.graph.edges.push(edge);
        this.state.selectedEdgeId = edge.id;
        this.state.selectedNodeId = null;
        this.markDirty();
    }

    onNodePointerDown(ev, node) {
        if (ev.button !== 0 || ev.target.closest("button, input, select, textarea")) {
            return;
        }
        ev.stopPropagation();
        ev.currentTarget.setPointerCapture(ev.pointerId);
        this.pointerGesture = {
            kind: "node",
            nodeId: node.id,
            pointerId: ev.pointerId,
            startX: ev.clientX,
            startY: ev.clientY,
            originX: node.position.x,
            originY: node.position.y,
            moved: false,
        };
    }

    onNodePointerMove(ev) {
        const gesture = this.pointerGesture;
        if (!gesture || gesture.kind !== "node" || gesture.pointerId !== ev.pointerId) {
            return;
        }
        const node = this.state.graph.nodes.find((item) => item.id === gesture.nodeId);
        if (!node) {
            return;
        }
        const dx = (ev.clientX - gesture.startX) / this.state.zoom;
        const dy = (ev.clientY - gesture.startY) / this.state.zoom;
        if (Math.abs(dx) + Math.abs(dy) > 3) {
            gesture.moved = true;
        }
        node.position.x = Math.max(24, Math.round(gesture.originX + dx));
        node.position.y = Math.max(24, Math.round(gesture.originY + dy));
    }

    onNodePointerUp(ev, node) {
        const gesture = this.pointerGesture;
        if (!gesture || gesture.kind !== "node" || gesture.pointerId !== ev.pointerId) {
            return;
        }
        ev.currentTarget.releasePointerCapture?.(ev.pointerId);
        this.pointerGesture = null;
        if (gesture.moved) {
            this.markDirty();
        } else {
            this.selectNode(node);
        }
    }

    onNodeKeydown(ev, node) {
        if (["Enter", " "].includes(ev.key)) {
            ev.preventDefault();
            this.selectNode(node);
        }
    }

    onEdgeKeydown(ev, edge) {
        if (["Enter", " "].includes(ev.key)) {
            ev.preventDefault();
            this.selectEdge(edge, ev);
        }
    }

    onCanvasPointerDown(ev) {
        if (ev.button !== 0 || ev.target.closest(".o_occ_node, .o_occ_edge_hit")) {
            return;
        }
        ev.currentTarget.setPointerCapture(ev.pointerId);
        this.pointerGesture = {
            kind: "pan",
            pointerId: ev.pointerId,
            startX: ev.clientX,
            startY: ev.clientY,
            originX: this.state.panX,
            originY: this.state.panY,
        };
        this.clearSelection();
    }

    onCanvasPointerMove(ev) {
        const gesture = this.pointerGesture;
        if (!gesture || gesture.kind !== "pan" || gesture.pointerId !== ev.pointerId) {
            return;
        }
        this.state.panX = gesture.originX + ev.clientX - gesture.startX;
        this.state.panY = gesture.originY + ev.clientY - gesture.startY;
    }

    onCanvasPointerUp(ev) {
        const gesture = this.pointerGesture;
        if (!gesture || gesture.kind !== "pan" || gesture.pointerId !== ev.pointerId) {
            return;
        }
        ev.currentTarget.releasePointerCapture?.(ev.pointerId);
        this.pointerGesture = null;
    }

    setZoom(value) {
        this.state.zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Number(value.toFixed(2))));
    }

    zoomIn() {
        this.setZoom(this.state.zoom + 0.1);
    }

    zoomOut() {
        this.setZoom(this.state.zoom - 0.1);
    }

    resetViewport() {
        this.state.zoom = 1;
        this.state.panX = 0;
        this.state.panY = 0;
    }

    autoLayout() {
        const nodes = this.state.graph.nodes;
        const edges = this.state.graph.edges;
        const incoming = new Map(nodes.map((node) => [node.id, 0]));
        const outgoing = new Map(nodes.map((node) => [node.id, []]));
        for (const edge of edges) {
            incoming.set(edge.target, (incoming.get(edge.target) || 0) + 1);
            outgoing.get(edge.source)?.push(edge.target);
        }
        const queue = nodes.filter((node) => node.type === "start" || incoming.get(node.id) === 0);
        const levels = new Map(queue.map((node) => [node.id, 0]));
        const pendingIncoming = new Map(incoming);
        for (let cursor = 0; cursor < queue.length; cursor++) {
            const node = queue[cursor];
            for (const targetId of outgoing.get(node.id) || []) {
                levels.set(targetId, Math.max(levels.get(targetId) || 0, (levels.get(node.id) || 0) + 1));
                pendingIncoming.set(targetId, (pendingIncoming.get(targetId) || 0) - 1);
                if (pendingIncoming.get(targetId) === 0) {
                    const target = nodes.find((item) => item.id === targetId);
                    if (target) {
                        queue.push(target);
                    }
                }
            }
        }
        let fallbackLevel = Math.max(0, ...levels.values()) + 1;
        for (const node of nodes) {
            if (!levels.has(node.id)) {
                levels.set(node.id, fallbackLevel++);
            }
        }
        const columns = new Map();
        for (const node of nodes) {
            const level = levels.get(node.id);
            const column = columns.get(level) || [];
            column.push(node);
            columns.set(level, column);
        }
        for (const [level, column] of [...columns.entries()].sort((a, b) => a[0] - b[0])) {
            column.forEach((node, index) => {
                node.position.x = 120 + level * 330;
                node.position.y = 90 + index * 170;
            });
        }
        this.markDirty();
        this.fitGraph();
    }

    fitGraph() {
        const viewport = this.canvasRef.el;
        if (!viewport) {
            return;
        }
        const bounds = this.graphBounds();
        const width = Math.max(1, bounds.maxX - bounds.minX + 160);
        const height = Math.max(1, bounds.maxY - bounds.minY + 160);
        const zoom = Math.min(viewport.clientWidth / width, viewport.clientHeight / height, 1.2);
        this.setZoom(zoom);
        this.state.panX = Math.round((viewport.clientWidth - width * this.state.zoom) / 2 - bounds.minX * this.state.zoom + 80);
        this.state.panY = Math.round((viewport.clientHeight - height * this.state.zoom) / 2 - bounds.minY * this.state.zoom + 80);
    }

    updateNodeField(field, ev) {
        if (!this.selectedNode) {
            return;
        }
        this.selectedNode[field] = ev.target.value;
        this.markDirty();
    }

    updateNodeConfig(field, ev) {
        if (!this.selectedNode) {
            return;
        }
        let value = ev.target.type === "checkbox" ? ev.target.checked : ev.target.value;
        if (ev.target.type === "number") {
            value = Number(value || 0);
        }
        this.selectedNode.config[field] = value;
        this.markDirty();
    }

    updateEdgeCondition(field, ev) {
        if (!this.selectedEdge) {
            return;
        }
        const value = ev.target.value;
        this.selectedEdge.condition[field] = value;
        if (field === "label") {
            this.selectedEdge.condition.custom_label = Boolean(value.trim());
        }
        this.markDirty();
    }

    updateEdgeSequence(ev) {
        if (!this.selectedEdge) {
            return;
        }
        this.selectedEdge.sequence = Math.max(1, Number(ev.target.value || 10));
        this.markDirty();
    }

    toggleAdvancedCondition(ev) {
        if (!this.selectedEdge) {
            return;
        }
        this.selectedEdge.condition.advanced = ev.target.checked;
        if (ev.target.checked && !this.selectedEdge.condition.value) {
            this.selectedEdge.condition.value = "[]";
        }
        if (ev.target.checked) {
            this.selectedEdge.condition.value_type = "json";
        }
        this.markDirty();
    }

    validateGraph({ forPublish = false } = {}) {
        const errors = [];
        const { nodes, edges } = this.state.graph;
        const ids = new Set(nodes.map((node) => node.id));
        if (ids.size !== nodes.length) {
            errors.push(_t("Node identifiers must be unique."));
        }
        for (const node of nodes) {
            if (!node.label?.trim()) {
                errors.push(_t("Every node must have a name."));
                break;
            }
            if (["approval", "task", "copy"].includes(node.type)) {
                if (node.config.assignee_mode === "users" && !node.config.user_ids?.length) {
                    errors.push(_t("Every specified-user node must contain at least one user."));
                }
                if (node.config.assignee_mode === "role" && !Number(node.config.role_id)) {
                    errors.push(_t("Every role-assigned node must select an approval role."));
                }
            }
            if (["approval", "task"].includes(node.type)) {
                const deadline = Number(node.config.deadline_hours || 0);
                const reminder = Number(node.config.reminder_before_hours || 0);
                if (deadline > 0 && reminder > deadline) {
                    errors.push(_t("A reminder cannot be scheduled before the node deadline window."));
                }
                if (
                    node.config.timeout_action === "reject" &&
                    !node.config.timeout_reject_node
                ) {
                    errors.push(_t("Timeout rejection requires a target node."));
                }
            }
        }
        const fallbackBySource = new Map();
        for (const edge of edges) {
            if (!ids.has(edge.source) || !ids.has(edge.target) || edge.source === edge.target) {
                errors.push(_t("The graph contains an invalid connection."));
                break;
            }
            let isFallback = !edge.condition?.field && !edge.condition?.advanced;
            if (edge.condition?.advanced) {
                try {
                    const domain = JSON.parse(edge.condition.value || "[]");
                    if (!Array.isArray(domain)) {
                        errors.push(_t("Every advanced condition must be a JSON array."));
                    } else {
                        isFallback = !domain.length;
                    }
                } catch {
                    errors.push(_t("An advanced condition contains invalid JSON."));
                }
            }
            if (isFallback) {
                fallbackBySource.set(edge.source, (fallbackBySource.get(edge.source) || 0) + 1);
            }
        }
        const invalidFallbackNode = nodes.find(
            (node) =>
                node.type !== "end" &&
                (fallbackBySource.get(node.id) || 0) !== 1
        );
        if (invalidFallbackNode) {
            errors.push(
                _t("Every non-end node must have exactly one fallback connection.")
            );
        }
        if (forPublish) {
            const starts = nodes.filter((node) => node.type === "start");
            const ends = nodes.filter((node) => node.type === "end");
            if (starts.length !== 1 || ends.length !== 1) {
                errors.push(_t("A published workflow requires exactly one start and one end node."));
            } else {
                const outgoing = new Map(nodes.map((node) => [node.id, []]));
                const incoming = new Map(nodes.map((node) => [node.id, 0]));
                for (const edge of edges) {
                    outgoing.get(edge.source)?.push(edge.target);
                    incoming.set(edge.target, (incoming.get(edge.target) || 0) + 1);
                }
                for (const node of nodes) {
                    if (node.type !== "end" && !outgoing.get(node.id)?.length) {
                        errors.push(_t("Every non-end node must lead to another node."));
                        break;
                    }
                    if (node.type !== "start" && !incoming.get(node.id)) {
                        errors.push(_t("Every non-start node must have an incoming connection."));
                        break;
                    }
                }
                const visited = new Set();
                const visiting = new Set();
                let hasCycle = false;
                const visit = (nodeId) => {
                    if (visiting.has(nodeId)) {
                        hasCycle = true;
                        return;
                    }
                    if (visited.has(nodeId)) {
                        return;
                    }
                    visiting.add(nodeId);
                    for (const targetId of outgoing.get(nodeId) || []) {
                        visit(targetId);
                    }
                    visiting.delete(nodeId);
                    visited.add(nodeId);
                };
                visit(starts[0].id);
                if (hasCycle) {
                    errors.push(_t("Published workflows cannot contain cycles."));
                }
                if (visited.size !== nodes.length || !visited.has(ends[0].id)) {
                    errors.push(_t("All nodes must be reachable from the start and lead toward the end."));
                }
            }
        }
        this.state.validationErrors = [...new Set(errors)];
        return !this.state.validationErrors.length;
    }

    async save({ quiet = false } = {}) {
        if (this.state.saving || this.state.publishing) {
            return false;
        }
        if (!this.validateGraph()) {
            return false;
        }
        if (!this.workflowId) {
            this.notification.add(_t("Save the workflow record before opening the designer."), {
                type: "warning",
            });
            return false;
        }
        this.state.saving = true;
        try {
            const result = await this.api.saveGraph(
                this.workflowId,
                copy(this.state.graph),
                this.state.revision
            );
            this.state.revision = Number(result?.revision ?? this.state.revision + 1);
            this.state.workflowState = result?.state || this.state.workflowState;
            this.state.dirty = false;
            if (!quiet) {
                this.notification.add(result?.message || _t("Workflow saved."), { type: "success" });
            }
            return true;
        } catch (error) {
            this.notifyError(error);
            return false;
        } finally {
            this.state.saving = false;
        }
    }

    onPublishClick() {
        if (!this.validateGraph({ forPublish: true })) {
            return;
        }
        this.dialog.add(ConfirmationDialog, {
            title: _t("Publish workflow"),
            body: _t("Publish this revision? New approval instances will use it immediately."),
            confirmLabel: _t("Publish"),
            confirm: () => this.publish(),
        });
    }

    async publish() {
        if (this.state.publishing || this.state.saving) {
            return;
        }
        this.state.publishing = true;
        try {
            if (this.state.dirty) {
                this.state.publishing = false;
                const saved = await this.save({ quiet: true });
                this.state.publishing = true;
                if (!saved) {
                    return;
                }
            }
            const result = await this.api.publishWorkflow(this.workflowId, this.state.revision);
            this.state.revision = Number(result?.revision ?? this.state.revision);
            this.state.workflowState = result?.state || "published";
            this.state.dirty = false;
            this.notification.add(result?.message || _t("Workflow published."), { type: "success" });
        } catch (error) {
            this.notifyError(error);
        } finally {
            this.state.publishing = false;
        }
    }

    beforeLeave({ forceLeave } = {}) {
        if (!this.state.dirty || forceLeave) {
            return true;
        }
        return new Promise((resolve) => {
            this.dialog.add(ConfirmationDialog, {
                title: _t("Unsaved workflow"),
                body: _t("You have unsaved workflow changes. Leave without saving them?"),
                confirmLabel: _t("Leave"),
                confirmClass: "btn-danger",
                confirm: () => resolve(true),
                cancel: () => resolve(false),
                dismiss: () => resolve(false),
            });
        });
    }

    onKeydown(ev) {
        if (ev.target.closest("input, textarea, select")) {
            return;
        }
        if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "s") {
            ev.preventDefault();
            this.save();
        } else if (["Delete", "Backspace"].includes(ev.key)) {
            ev.preventDefault();
            this.requestDeleteSelection();
        } else if (ev.key === "Escape") {
            this.clearSelection();
        }
    }

    notifyError(error) {
        this.notification.add(approvalErrorMessage(error), {
            title: _t("Approval workflow"),
            type: "danger",
        });
    }
}

export { MAX_ZOOM, MIN_ZOOM, NODE_HEIGHT, NODE_TYPES, NODE_WIDTH, normalizeGraph };
