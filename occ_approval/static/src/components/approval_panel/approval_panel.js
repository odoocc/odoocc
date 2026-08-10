/** @odoo-module **/

import { Component, onMounted, onWillStart, useRef, useState } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { useHotkey } from "@web/core/hotkeys/hotkey_hook";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";

import { approvalErrorMessage } from "../../api";

const SUCCESS_STATES = new Set(["approved", "completed", "done", "copied"]);
const DANGER_STATES = new Set(["rejected", "failed"]);
const ACTIVE_STATES = new Set(["running", "rework", "active", "pending"]);

function normalizedPanel(payload = {}, userId = 0) {
    const instance = payload.instance || null;
    const nodes = Array.isArray(payload.nodes) ? payload.nodes : [];
    const events = Array.isArray(payload.events) ? payload.events : [];
    const workflows = Array.isArray(payload.workflows) ? payload.workflows : [];
    const permissions = payload.permissions || {};
    const actions = { ...permissions, ...(payload.actions || {}) };
    const pendingTaskIds = new Set((permissions.pending_task_ids || []).map(Number));
    const nodeTasks = nodes.flatMap((node) =>
        (node.tasks || []).map((task) => ({
            ...task,
            node,
            node_name: node.name,
            node_type: node.type,
            reject_targets: node.reject_targets || [],
        }))
    );
    const advertisedTasks = (Array.isArray(payload.tasks) ? payload.tasks : []).map((task) => {
        const node = nodes.find((item) => Number(item.id) === Number(task.node_id)) || null;
        return {
            ...task,
            node,
            node_name: task.node_name || node?.name || task.name,
            node_type: task.node_type || node?.type,
            reject_targets: task.reject_targets || task.available_revert_nodes || node?.reject_targets || [],
        };
    });
    const derivedActorTasks = nodeTasks.filter(
        (task) =>
            pendingTaskIds.has(Number(task.id)) ||
            (Number(task.user_id) === Number(userId) &&
                ["approved", "completed"].includes(task.state))
    );
    const actorTasks = advertisedTasks.length ? advertisedTasks : derivedActorTasks;
    return {
        enabled: Boolean(payload.enabled),
        instance,
        nodes,
        events,
        workflows,
        permissions,
        actions,
        sourceCompanyMismatch: Boolean(payload.source_company_mismatch),
        tasks: nodeTasks,
        actorTasks,
        state: instance?.state || "none",
    };
}

export class ApprovalPanel extends Component {
    static template = "occ_approval.ApprovalPanel";
    static props = {
        resModel: String,
        resId: Number,
        close: Function,
        onUpdate: { type: Function, optional: true },
    };

    setup() {
        this.action = useService("action");
        this.api = useService("occ_approval_api");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.user = useService("user");
        this.panelRef = useRef("panel");
        this.state = useState({
            loading: true,
            actionKey: null,
            data: normalizedPanel({}, this.user.userId),
            selectedWorkflowId: 0,
            operation: null,
            userPicker: null,
        });

        useHotkey("escape", () => {
            if (this.state.operation) {
                this.state.operation = null;
            } else if (this.state.userPicker) {
                this.state.userPicker = null;
            } else if (!this.isBusy) {
                this.props.close();
            }
        });
        onWillStart(() => this.refresh());
        onMounted(() => this.panelRef.el?.focus());
    }

    get instanceId() {
        return Number(this.state.data.instance?.id || 0);
    }

    get isBusy() {
        return Boolean(this.state.actionKey);
    }

    get currentNode() {
        const currentId = Number(this.state.data.instance?.current_node_id || 0);
        return (
            this.state.data.nodes.find((node) => Number(node.id) === currentId) ||
            this.state.data.nodes.find((node) => node.state === "active") ||
            null
        );
    }

    get canRemind() {
        if (Object.hasOwn(this.state.data.actions, "can_remind")) {
            return Boolean(this.state.data.actions.can_remind);
        }
        const node = this.currentNode;
        return Boolean(
            node &&
                ["approval", "task"].includes(node.type) &&
                node.state === "active" &&
                !node.manual_reminder_sent_at &&
                (node.tasks || []).some((task) => task.state === "pending") &&
                this.state.data.permissions.can_cancel_instance
        );
    }

    get requesterChoiceNodes() {
        const advertised = this.state.data.actorTasks.filter(
            (task) =>
                task.kind === "assignment" &&
                (task.actions?.choose_users || task.actions?.set_users)
        );
        if (advertised.length) {
            return advertised;
        }
        return this.state.data.nodes.filter(
            (node) =>
                node.assignment_type === "requester_choice" &&
                node.state === "waiting" &&
                this.state.data.permissions.can_submit
        );
    }

    get actionTasks() {
        return this.state.data.actorTasks.filter((task) => task.kind !== "assignment");
    }

    get requestWorkflows() {
        return this.state.data.workflows.filter(
            (workflow) => !workflow.action_key || workflow.action_key === "manual"
        );
    }

    get selectedWorkflow() {
        return (
            this.requestWorkflows.find(
                (workflow) => Number(workflow.id) === Number(this.state.selectedWorkflowId)
            ) || null
        );
    }

    applyPayload(payload) {
        this.state.data = normalizedPanel(payload, this.user.userId);
        if (this.requestWorkflows.length) {
            const stillAvailable = this.requestWorkflows.some(
                (workflow) => Number(workflow.id) === Number(this.state.selectedWorkflowId)
            );
            if (!stillAvailable) {
                this.state.selectedWorkflowId = Number(this.requestWorkflows[0].id);
            }
        }
        return this.props.onUpdate?.(this.state.data);
    }

    async refresh() {
        this.state.loading = true;
        try {
            const payload = await this.api.getPanelData(this.props.resModel, this.props.resId);
            await this.applyPayload(payload);
        } catch (error) {
            this.notifyError(error);
        } finally {
            this.state.loading = false;
        }
    }

    statusClass(state) {
        if (SUCCESS_STATES.has(state)) {
            return "success";
        }
        if (DANGER_STATES.has(state)) {
            return "danger";
        }
        if (ACTIVE_STATES.has(state)) {
            return state === "rework" ? "warning" : "primary";
        }
        return "secondary";
    }

    stateLabel(state) {
        const labels = {
            none: _t("Not requested"),
            draft: _t("Draft"),
            running: _t("Running"),
            rework: _t("Rework"),
            approved: _t("Approved"),
            cancelled: _t("Cancelled"),
            waiting: _t("Waiting"),
            active: _t("Active"),
            completed: _t("Completed"),
            rejected: _t("Rejected"),
            skipped: _t("Skipped"),
            pending: _t("Pending"),
            copied: _t("Copied"),
            failed: _t("Failed"),
            done: _t("Done"),
        };
        return labels[state] || state || _t("Unknown");
    }

    sameId(left, right) {
        return Number(left || 0) === Number(right || 0);
    }

    nodeIcon(type) {
        return {
            start: "fa-play",
            approval: "fa-check",
            task: "fa-briefcase",
            copy: "fa-paper-plane",
            end: "fa-stop",
        }[type] || "fa-circle";
    }

    canTask(task, action) {
        if (task.actions && Object.hasOwn(task.actions, action)) {
            return Boolean(task.actions[action]);
        }
        if (["approve", "reject"].includes(action)) {
            return (
                task.state === "pending" &&
                this.state.data.permissions.pending_task_ids?.includes(Number(task.id))
            );
        }
        if (action === "revoke") {
            return (
                Number(task.user_id) === Number(this.user.userId) &&
                ["approved", "completed"].includes(task.state)
            );
        }
        return false;
    }

    async runAction(key, callback, fallbackMessage) {
        if (this.isBusy) {
            return false;
        }
        this.state.actionKey = key;
        try {
            const result = await callback();
            if (result && Object.hasOwn(result, "enabled")) {
                await this.applyPayload(result);
            } else {
                await this.refresh();
            }
            this.notification.add(fallbackMessage, { type: "success" });
            return true;
        } catch (error) {
            this.notifyError(error);
            return false;
        } finally {
            this.state.actionKey = null;
        }
    }

    selectWorkflow(ev) {
        this.state.selectedWorkflowId = Number(ev.target.value || 0);
    }

    createInstance() {
        const workflow = this.selectedWorkflow;
        if (!workflow) {
            this.notification.add(_t("Select an approval workflow."), { type: "warning" });
            return;
        }
        return this.runAction(
            "create",
            () =>
                this.api.createInstance(this.props.resModel, this.props.resId, workflow.id, {
                    action_key: workflow.action_key,
                }),
            _t("Approval created.")
        );
    }

    submitInstance() {
        return this.runAction(
            "submit",
            () => this.api.submitInstance(this.instanceId),
            _t("Approval submitted.")
        );
    }

    requestCancelSubmission() {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Cancel submission"),
            body: _t("Return this approval to draft?"),
            confirmLabel: _t("Return to draft"),
            confirm: () =>
                this.runAction(
                    "cancel_submission",
                    () => this.api.cancelSubmission(this.instanceId),
                    _t("Submission returned to draft.")
                ),
        });
    }

    requestCancelInstance() {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Cancel approval"),
            body: _t("Cancel this approval instance? Its audit history will be retained."),
            confirmLabel: _t("Cancel approval"),
            confirmClass: "btn-danger",
            confirm: () =>
                this.runAction(
                    "cancel_instance",
                    () => this.api.cancelInstance(this.instanceId),
                    _t("Approval cancelled.")
                ),
        });
    }

    retryExecution() {
        return this.runAction(
            "retry_execution",
            () => this.api.retryExecution(this.instanceId),
            _t("Business execution retried.")
        );
    }

    async openDocument() {
        if (!this.instanceId || this.isBusy) {
            return;
        }
        this.state.actionKey = "open_document";
        try {
            const action = await this.api.openDocument(this.instanceId);
            await this.action.doAction(action);
            this.props.close();
        } catch (error) {
            this.notifyError(error);
        } finally {
            this.state.actionKey = null;
        }
    }

    openOperation(type, task = null) {
        const titles = {
            approve: task?.kind === "task" ? _t("Complete task") : _t("Approve task"),
            reject: _t("Reject task"),
            revoke: _t("Revoke my action"),
            remind: _t("Send reminder"),
        };
        const rejectTargets = task?.reject_targets || [];
        this.state.operation = {
            type,
            title: titles[type],
            task,
            comment: "",
            target_node_id: rejectTargets[0]?.id || "",
            mode: "sequential",
            node_id: this.currentNode?.id || null,
        };
    }

    updateOperation(field, ev) {
        if (this.state.operation) {
            this.state.operation[field] = ev.target.value;
        }
    }

    closeOperation() {
        if (!this.isBusy) {
            this.state.operation = null;
        }
    }

    async confirmOperation() {
        const operation = this.state.operation;
        if (!operation) {
            return;
        }
        let callback;
        let message;
        if (operation.type === "approve") {
            callback = () =>
                this.api.approveTask(operation.task.id, { comment: operation.comment });
            message = operation.task.kind === "task" ? _t("Task completed.") : _t("Task approved.");
        } else if (operation.type === "reject") {
            if (!operation.target_node_id) {
                this.notification.add(_t("Select the node to reject to."), { type: "warning" });
                return;
            }
            callback = () =>
                this.api.rejectTask(operation.task.id, {
                    target_node_id: Number(operation.target_node_id),
                    mode: operation.mode,
                    comment: operation.comment,
                });
            message = _t("Task rejected.");
        } else if (operation.type === "revoke") {
            callback = () =>
                this.api.revokeTask(operation.task.id, { comment: operation.comment });
            message = _t("Action revoked.");
        } else {
            callback = () =>
                this.api.remind(this.instanceId, {
                    message: operation.comment,
                    node_id: operation.node_id,
                });
            message = _t("Reminder sent.");
        }
        const succeeded = await this.runAction(operation.type, callback, message);
        if (succeeded) {
            this.state.operation = null;
        }
    }

    async openUserPicker(choice) {
        const node = choice.node || choice;
        if (!node?.id) {
            this.notification.add(_t("The assignment node is no longer available."), {
                type: "warning",
            });
            return;
        }
        const advertisedUsers = (choice.assignees || []).map((user) => Number(user.id || user.user_id));
        this.state.userPicker = {
            node,
            query: "",
            loading: false,
            results: [],
            selectedIds: advertisedUsers.length
                ? advertisedUsers
                : [...(node.draft_assignee_user_ids || [])].map(Number),
        };
        await this.searchUsers();
    }

    updateUserQuery(ev) {
        if (this.state.userPicker) {
            this.state.userPicker.query = ev.target.value;
        }
    }

    async searchUsers(ev) {
        ev?.preventDefault();
        const picker = this.state.userPicker;
        if (!picker || picker.loading) {
            return;
        }
        picker.loading = true;
        try {
            const result = await this.api.searchAssignableUsers(
                picker.node.id,
                picker.query,
                100
            );
            picker.results = Array.isArray(result) ? result : [];
        } catch (error) {
            this.notifyError(error);
        } finally {
            picker.loading = false;
        }
    }

    toggleUser(userId) {
        const picker = this.state.userPicker;
        if (!picker) {
            return;
        }
        const id = Number(userId);
        picker.selectedIds = picker.selectedIds.includes(id)
            ? picker.selectedIds.filter((item) => item !== id)
            : [...picker.selectedIds, id];
    }

    isPickerUserSelected(userId) {
        return Boolean(
            this.state.userPicker?.selectedIds.includes(Number(userId))
        );
    }

    async applyUsers() {
        const picker = this.state.userPicker;
        if (!picker) {
            return;
        }
        if (!picker.selectedIds.length) {
            this.notification.add(_t("Select at least one user."), { type: "warning" });
            return;
        }
        const succeeded = await this.runAction(
            "set_users",
            () => this.api.setDraftAssignees(this.instanceId, picker.node.id, picker.selectedIds),
            _t("Assignees updated.")
        );
        if (succeeded) {
            this.state.userPicker = null;
        }
    }

    closeUserPicker() {
        if (!this.isBusy) {
            this.state.userPicker = null;
        }
    }

    eventTitle(event) {
        const labels = {
            instance_requested: _t("Approval requested"),
            instance_submitted: _t("Approval submitted"),
            submission_cancelled: _t("Submission returned to draft"),
            instance_cancelled: _t("Approval cancelled"),
            node_entered: _t("Node entered"),
            tasks_assigned: _t("Tasks assigned"),
            copy_delivered: _t("Copy delivered"),
            task_approved: _t("Task approved"),
            task_completed: _t("Task completed"),
            task_rejected: _t("Task rejected"),
            task_revoked: _t("Task revoked"),
            node_approved: _t("Node approved"),
            node_completed: _t("Node completed"),
            edge_selected: _t("Route selected"),
            instance_approved: _t("Approval completed"),
            draft_assignees_set: _t("Assignees selected"),
            manual_reminder_sent: _t("Reminder sent"),
            automatic_reminder_sent: _t("Automatic reminder sent"),
            node_timeout_reached: _t("Deadline reached"),
            timeout_auto_approved: _t("Automatically approved"),
            execution_started: _t("Business execution started"),
            execution_completed: _t("Business execution completed"),
            execution_failed: _t("Business execution failed"),
        };
        return labels[event.type] || String(event.type || "").replaceAll("_", " ");
    }

    eventDetail(event) {
        const payload = event.payload || {};
        return payload.comment || payload.message || payload.reason || payload.error || "";
    }

    onBackdropClick(ev) {
        if (ev.target === ev.currentTarget && !this.isBusy) {
            this.props.close();
        }
    }

    notifyError(error) {
        this.notification.add(approvalErrorMessage(error), {
            title: _t("Approval"),
            type: "danger",
        });
    }
}

export { normalizedPanel };
