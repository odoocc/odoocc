/** @odoo-module **/

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";

export const APPROVAL_MODELS = Object.freeze({
    workflow: "occ.approval.workflow",
    instance: "occ.approval.instance",
    role: "occ.approval.role",
    user: "res.users",
});

export const RPC_CONTRACT = Object.freeze({
    workflow: Object.freeze({
        supportedModels: "get_supported_models",
        designerData: "get_designer_data",
        saveGraph: "save_designer_data",
        publish: "publish_designer_data",
    }),
    instance: Object.freeze({
        supportedModels: "get_supported_models",
        dashboard: "get_dashboard_summary",
        recordState: "get_record_state",
        panelData: "get_record_panel",
        create: "create_for_record",
        submit: "submit",
        cancelSubmission: "cancel_submission",
        cancelInstance: "cancel_instance",
        approveTask: "approve_task",
        rejectTask: "reject_task",
        revokeTask: "revoke_task",
        remind: "remind",
        searchAssignableUsers: "search_assignable_users",
        setTaskUsers: "set_task_users",
        setDraftAssignees: "set_draft_assignees",
        retryExecution: "retry_execution",
        openDocument: "open_document",
    }),
});

export function approvalErrorMessage(error) {
    return (
        error?.data?.arguments?.[0] ||
        error?.data?.message ||
        error?.message ||
        _t("The approval request could not be completed.")
    );
}

function modelName(item) {
    if (typeof item === "string") {
        return item;
    }
    return item?.model || item?.model_name || item?.name || false;
}

function conditionValueType(value) {
    if (value === null) {
        return "null";
    }
    if (Array.isArray(value) || typeof value === "object") {
        return "json";
    }
    if (["string", "number", "boolean"].includes(typeof value)) {
        return typeof value;
    }
    return "string";
}

function conditionEditorValue(condition, explicitLabel = "") {
    const label = typeof explicitLabel === "string" ? explicitLabel.trim() : "";
    const customLabel = Boolean(label);
    if (!Array.isArray(condition) || !condition.length) {
        return {
            label,
            custom_label: customLabel,
            field: "",
            operator: "=",
            value: "",
            value_type: "string",
        };
    }
    const isSingleLeaf =
        condition.length === 1 && Array.isArray(condition[0]) && condition[0].length === 3;
    if (!isSingleLeaf) {
        return {
            label,
            custom_label: customLabel,
            field: "",
            operator: "=",
            value: JSON.stringify(condition),
            value_type: "json",
            advanced: true,
        };
    }
    const leaf = condition[0];
    return {
        label,
        custom_label: customLabel,
        field: leaf[0],
        operator: leaf[1],
        value:
            typeof leaf[2] === "string"
                ? leaf[2]
                : leaf[2] === null
                  ? ""
                  : JSON.stringify(leaf[2]),
        value_type: conditionValueType(leaf[2]),
    };
}

function assignmentEditorValue(assignment = {}) {
    return {
        assignee_mode: assignment.type || "users",
        user_ids: assignment.user_ids || [],
        role_id: Number(assignment.role_id || 0),
        role_ids: assignment.role_id ? [Number(assignment.role_id)] : [],
        manager_level: Number(assignment.level || 1),
        manager_chain_levels: Number(assignment.levels || 0),
    };
}

function asGraph(payload) {
    const graph = payload?.graph || payload?.definition || payload || {};
    const nodes = Array.isArray(graph.nodes)
        ? graph.nodes.map((node) => ({
              id: node.id,
              type: node.type,
              label: node.name,
              description: node.description || "",
              position: node.position,
              config: {
                  ...assignmentEditorValue(node.assignment),
                  approval_mode: node.mode || "all",
                  completion_mode: node.mode || "all",
                  deadline_hours: Number(node.deadline_hours || 0),
                  reminder_before_hours: Number(node.reminder_before_hours || 0),
                  timeout_action: node.timeout_action || "none",
                  timeout_reject_node: node.timeout_reject_node || "",
                  timeout_reject_mode: node.timeout_reject_mode || "sequential",
              },
          }))
        : [];
    const edges = Array.isArray(graph.edges)
        ? graph.edges.map((edge, index) => ({
              id: edge.id || `edge_${edge.source}_${edge.target}_${edge.sequence || index}`,
              source: edge.source,
              target: edge.target,
              sequence: Number(edge.sequence || (index + 1) * 10),
              condition: conditionEditorValue(edge.condition, edge.label),
          }))
        : [];
    return {
        schema_version: Number(graph.schema_version || 1),
        nodes,
        edges,
    };
}

function parseConditionValue(value, valueType = "string") {
    const text = typeof value === "string" ? value : String(value ?? "");
    const trimmed = text.trim();
    if (valueType === "string") {
        return text;
    }
    if (valueType === "null") {
        return null;
    }
    if (valueType === "number") {
        const parsed = Number(trimmed);
        if (!trimmed || !Number.isFinite(parsed)) {
            throw new Error(_t("A numeric edge condition contains an invalid value."));
        }
        return parsed;
    }
    if (valueType === "boolean") {
        if (trimmed === "true") {
            return true;
        }
        if (trimmed === "false") {
            return false;
        }
        throw new Error(_t("A boolean edge condition must be true or false."));
    }
    if (valueType === "json") {
        try {
            return JSON.parse(trimmed);
        } catch {
            throw new Error(_t("A JSON edge condition contains an invalid value."));
        }
    }
    throw new Error(_t("An edge condition uses an unsupported value type."));
}

function serverAssignment(config = {}) {
    const type = config.assignee_mode || "users";
    const assignment = { type };
    if (type === "users") {
        assignment.user_ids = config.user_ids || [];
    } else if (type === "role") {
        assignment.role_id = Number(config.role_id || config.role_ids?.[0] || 0);
    } else if (type === "manager") {
        assignment.level = Number(config.manager_level || 1);
    } else if (type === "manager_chain") {
        assignment.levels = Number(config.manager_chain_levels || 0);
    }
    return assignment;
}

function serverCondition(edge) {
    if (edge.condition?.advanced) {
        let parsed;
        try {
            parsed = JSON.parse(edge.condition.value || "[]");
        } catch {
            throw new Error(_t("An advanced edge condition contains invalid JSON."));
        }
        if (!Array.isArray(parsed)) {
            throw new Error(_t("An advanced edge condition must be a JSON array."));
        }
        return parsed;
    }
    if (edge.condition?.field) {
        return [
            [
                edge.condition.field,
                edge.condition.operator || "=",
                parseConditionValue(
                    edge.condition.value,
                    edge.condition.value_type || "string"
                ),
            ],
        ];
    }
    return [];
}

function toServerGraph(graph) {
    const nodes = graph.nodes.map((node) => {
        const result = {
            id: node.id,
            type: node.type,
            name: node.label,
            position: {
                x: Number(node.position?.x || 0),
                y: Number(node.position?.y || 0),
            },
        };
        if (node.description) {
            result.description = node.description;
        }
        if (["approval", "task", "copy"].includes(node.type)) {
            result.assignment = serverAssignment(node.config);
        }
        if (["approval", "task"].includes(node.type)) {
            result.mode =
                node.type === "approval"
                    ? node.config.approval_mode || "all"
                    : node.config.completion_mode || "all";
            result.deadline_hours = Number(node.config.deadline_hours || 0);
            result.reminder_before_hours = Number(node.config.reminder_before_hours || 0);
            result.timeout_action = node.config.timeout_action || "none";
            if (result.timeout_action === "reject") {
                result.timeout_reject_node = node.config.timeout_reject_node || "";
                result.timeout_reject_mode = node.config.timeout_reject_mode || "sequential";
            }
        }
        return result;
    });

    const edgesBySource = new Map();
    for (const edge of graph.edges) {
        const group = edgesBySource.get(edge.source) || [];
        group.push(edge);
        edgesBySource.set(edge.source, group);
    }
    const edges = [];
    for (const group of edgesBySource.values()) {
        const ordered = [...group]
            .sort((a, b) => Number(a.sequence || 0) - Number(b.sequence || 0))
            .map((edge) => ({ edge, condition: serverCondition(edge) }));
        const conditional = ordered.filter((item) => item.condition.length);
        const fallback = ordered.filter((item) => !item.condition.length);
        [...conditional, ...fallback].forEach(({ edge, condition }, index) => {
            const serverEdge = {
                source: edge.source,
                target: edge.target,
                sequence: (index + 1) * 10,
                condition,
            };
            const label = edge.condition?.label?.trim();
            if (edge.condition?.custom_label && label) {
                serverEdge.label = label;
            }
            edges.push(serverEdge);
        });
    }
    return { schema_version: Number(graph.schema_version || 1), nodes, edges };
}

export class ApprovalApi {
    constructor(orm) {
        this.orm = orm;
        this.supportedModelsPromise = null;
        this.supportedModels = new Set();
    }

    call(model, method, args = [], kwargs = {}) {
        return this.orm.call(model, method, args, kwargs);
    }

    async getSupportedModels({ force = false } = {}) {
        if (force) {
            this.supportedModelsPromise = null;
        }
        if (!this.supportedModelsPromise) {
            this.supportedModelsPromise = this.call(
                APPROVAL_MODELS.instance,
                RPC_CONTRACT.instance.supportedModels
            )
                .then((payload) => {
                    const rows = Array.isArray(payload) ? payload : payload?.models || [];
                    this.supportedModels = new Set(rows.map(modelName).filter(Boolean));
                    return this.supportedModels;
                })
                .catch((error) => {
                    if (
                        error?.data?.name === "odoo.exceptions.AccessError" ||
                        error?.data?.name === "AccessError"
                    ) {
                        this.supportedModels = new Set();
                        return this.supportedModels;
                    }
                    this.supportedModelsPromise = null;
                    throw error;
                });
        }
        return this.supportedModelsPromise;
    }

    async supportsModel(resModel) {
        if (!resModel) {
            return false;
        }
        const supported = await this.getSupportedModels();
        return supported.has(resModel);
    }

    async getDesignerData(workflowId) {
        const payload = await this.call(
            APPROVAL_MODELS.workflow,
            RPC_CONTRACT.workflow.designerData,
            [workflowId]
        );
        return {
            id: payload?.id || workflowId,
            name: payload?.name || _t("Approval workflow"),
            state: payload?.state || "draft",
            revision: Number(payload?.revision || 0),
            companyId: Number(payload?.company_id || 0),
            modelName: payload?.model_name || "",
            graph: asGraph(payload),
        };
    }

    saveGraph(workflowId, graph, expectedRevision) {
        return this.call(APPROVAL_MODELS.workflow, RPC_CONTRACT.workflow.saveGraph, [
            workflowId,
            toServerGraph(graph),
            expectedRevision,
        ]);
    }

    publishWorkflow(workflowId, expectedRevision) {
        return this.call(APPROVAL_MODELS.workflow, RPC_CONTRACT.workflow.publish, [
            workflowId,
            expectedRevision,
        ]);
    }

    getDashboardSummary() {
        return this.call(APPROVAL_MODELS.instance, RPC_CONTRACT.instance.dashboard);
    }

    getRecordState(resModel, resId) {
        return this.call(APPROVAL_MODELS.instance, RPC_CONTRACT.instance.recordState, [
            resModel,
            resId,
        ]);
    }

    getPanelData(resModel, resId) {
        return this.call(APPROVAL_MODELS.instance, RPC_CONTRACT.instance.panelData, [
            resModel,
            resId,
        ]);
    }

    createInstance(resModel, resId, workflowId = null, values = {}) {
        return this.call(APPROVAL_MODELS.instance, RPC_CONTRACT.instance.create, [
            resModel,
            resId,
            workflowId || null,
            values || {},
        ]);
    }

    submitInstance(instanceId) {
        return this.call(APPROVAL_MODELS.instance, RPC_CONTRACT.instance.submit, [instanceId]);
    }

    cancelSubmission(instanceId) {
        return this.call(
            APPROVAL_MODELS.instance,
            RPC_CONTRACT.instance.cancelSubmission,
            [instanceId]
        );
    }

    cancelInstance(instanceId) {
        return this.call(
            APPROVAL_MODELS.instance,
            RPC_CONTRACT.instance.cancelInstance,
            [instanceId]
        );
    }

    approveTask(taskId, values) {
        return this.call(APPROVAL_MODELS.instance, RPC_CONTRACT.instance.approveTask, [
            taskId,
            values,
        ]);
    }

    rejectTask(taskId, values) {
        return this.call(APPROVAL_MODELS.instance, RPC_CONTRACT.instance.rejectTask, [
            taskId,
            values,
        ]);
    }

    revokeTask(taskId, values = {}) {
        return this.call(APPROVAL_MODELS.instance, RPC_CONTRACT.instance.revokeTask, [
            taskId,
            values,
        ]);
    }

    remind(instanceId, values) {
        return this.call(APPROVAL_MODELS.instance, RPC_CONTRACT.instance.remind, [
            instanceId,
            values,
        ]);
    }

    searchAssignableUsers(taskId, query = "", limit = 30) {
        return this.call(
            APPROVAL_MODELS.instance,
            RPC_CONTRACT.instance.searchAssignableUsers,
            [taskId, query, limit]
        );
    }

    setTaskUsers(taskId, userIds) {
        return this.call(APPROVAL_MODELS.instance, RPC_CONTRACT.instance.setTaskUsers, [
            taskId,
            userIds,
        ]);
    }

    setDraftAssignees(instanceId, nodeId, userIds) {
        return this.call(APPROVAL_MODELS.instance, RPC_CONTRACT.instance.setDraftAssignees, [
            instanceId,
            nodeId,
            userIds,
        ]);
    }

    retryExecution(instanceId) {
        return this.call(APPROVAL_MODELS.instance, RPC_CONTRACT.instance.retryExecution, [
            instanceId,
        ]);
    }

    openDocument(instanceId) {
        return this.call(APPROVAL_MODELS.instance, RPC_CONTRACT.instance.openDocument, [
            instanceId,
        ]);
    }

    async searchDesignerUsers(companyId, query = "", limit = 50) {
        if (!companyId) {
            return [];
        }
        const domain = [
            ["active", "=", true],
            ["share", "=", false],
            ["company_ids", "in", Number(companyId)],
        ];
        if (query?.trim()) {
            domain.push(["name", "ilike", query.trim()]);
        }
        return this.orm.searchRead(
            APPROVAL_MODELS.user,
            domain,
            ["id", "name", "login", "email"],
            { limit: Math.min(Math.max(Number(limit) || 50, 1), 200), order: "name, id" }
        );
    }

    async getDesignerUsersByIds(companyId, userIds = []) {
        const ids = [...new Set((userIds || []).map(Number).filter((id) => id > 0))];
        if (!companyId || !ids.length) {
            return [];
        }
        return this.orm.searchRead(
            APPROVAL_MODELS.user,
            [
                ["id", "in", ids],
                ["active", "=", true],
                ["share", "=", false],
                ["company_ids", "in", Number(companyId)],
            ],
            ["id", "name", "login", "email"],
            { limit: Math.min(ids.length, 200), order: "name, id" }
        );
    }

    async getDesignerRoles(companyId, limit = 200) {
        if (!companyId) {
            return [];
        }
        return this.orm.searchRead(
            APPROVAL_MODELS.role,
            [
                ["active", "=", true],
                ["company_id", "=", Number(companyId)],
            ],
            ["id", "name", "code"],
            { limit: Math.min(Math.max(Number(limit) || 200, 1), 500), order: "name, id" }
        );
    }
}

export { asGraph as toDesignerGraph, toServerGraph };

export const approvalApiService = {
    dependencies: ["orm"],
    start(env, { orm }) {
        return new ApprovalApi(orm);
    },
};

registry.category("services").add("occ_approval_api", approvalApiService);
