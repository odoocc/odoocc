/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";

import { approvalErrorMessage } from "../../api";

function emptySummary() {
    return {
        counts: {
            pending: 0,
            overdue: 0,
            my_draft: 0,
            my_running: 0,
            my_approved: 0,
            execution_failed: 0,
        },
        pending_tasks: [],
        instances: [],
    };
}

export class ApprovalDashboard extends Component {
    static template = "occ_approval.ApprovalDashboard";
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
        this.action = useService("action");
        this.api = useService("occ_approval_api");
        this.notification = useService("notification");
        this.state = useState({
            loading: true,
            loaded: false,
            openingId: 0,
            data: emptySummary(),
        });
        this.countCards = [
            { key: "pending", label: _t("Pending tasks"), icon: "fa-inbox", tone: "primary" },
            { key: "overdue", label: _t("Overdue"), icon: "fa-clock-o", tone: "danger" },
            { key: "my_draft", label: _t("My drafts"), icon: "fa-pencil", tone: "secondary" },
            { key: "my_running", label: _t("In progress"), icon: "fa-refresh", tone: "warning" },
            { key: "my_approved", label: _t("Approved"), icon: "fa-check", tone: "success" },
            { key: "execution_failed", label: _t("Execution failed"), icon: "fa-exclamation-triangle", tone: "danger" },
        ];
        onWillStart(() => this.load());
    }

    async load() {
        if (this.state.loading === "refresh") {
            return;
        }
        this.state.loading = this.state.loaded ? "refresh" : true;
        try {
            const payload = await this.api.getDashboardSummary();
            this.state.data = {
                ...emptySummary(),
                ...(payload || {}),
                counts: { ...emptySummary().counts, ...(payload?.counts || {}) },
                pending_tasks: Array.isArray(payload?.pending_tasks) ? payload.pending_tasks : [],
                instances: Array.isArray(payload?.instances) ? payload.instances : [],
            };
        } catch (error) {
            this.notification.add(approvalErrorMessage(error), {
                title: _t("Approval dashboard"),
                type: "danger",
            });
        } finally {
            this.state.loaded = true;
            this.state.loading = false;
        }
    }

    statusClass(state) {
        if (["approved", "done", "completed"].includes(state)) {
            return "success";
        }
        if (["failed", "rejected"].includes(state)) {
            return "danger";
        }
        if (["running", "rework", "pending"].includes(state)) {
            return state === "rework" ? "warning" : "primary";
        }
        return "secondary";
    }

    stateLabel(state) {
        return (
            {
                draft: _t("Draft"),
                running: _t("Running"),
                rework: _t("Rework"),
                approved: _t("Approved"),
                cancelled: _t("Cancelled"),
                pending: _t("Pending"),
                failed: _t("Failed"),
                done: _t("Done"),
                none: _t("Not required"),
            }[state] || state || _t("Unknown")
        );
    }

    isOverdue(task) {
        if (!task.deadline_at) {
            return false;
        }
        const value = String(task.deadline_at).replace(" ", "T");
        const deadline = new Date(value.endsWith("Z") ? value : `${value}Z`);
        return !Number.isNaN(deadline.getTime()) && deadline.getTime() < Date.now();
    }

    taskTitle(task) {
        if (task.node_name) {
            return task.node_name;
        }
        return task.kind === "task" ? _t("Execution task") : _t("Approval task");
    }

    taskSubtitle(task) {
        return (
            task.source_display_name ||
            task.instance_name ||
            task.workflow_name ||
            _t("Assigned to you")
        );
    }

    isOpening(instanceId) {
        return Number(this.state.openingId || 0) === Number(instanceId || 0);
    }

    async openInstance(instance) {
        if (!instance?.id || this.state.openingId) {
            return;
        }
        this.state.openingId = Number(instance.id);
        try {
            const target = await this.api.openDocument(instance.id);
            await this.action.doAction(target);
        } catch (error) {
            this.notification.add(approvalErrorMessage(error), { type: "danger" });
        } finally {
            this.state.openingId = 0;
        }
    }

    async openTask(task) {
        if (task.instance_id) {
            return this.openInstance({ id: task.instance_id });
        }
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: _t("My approval task"),
            res_model: "occ.approval.task",
            views: [[false, "list"]],
            domain: [["id", "=", Number(task.id)]],
            target: "current",
        });
    }
}

export { emptySummary };
