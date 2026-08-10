/** @odoo-module **/

import { onWillUnmount, useEffect, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { FormController } from "@web/views/form/form_controller";

import { approvalErrorMessage } from "../api";
import { ApprovalPanel } from "../components/approval_panel/approval_panel";

patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);
        this.occApprovalApi = useService("occ_approval_api");
        this.occApprovalDrawer = useService("occ_approval_drawer");
        this.occApprovalNotification = useService("notification");
        this.occApproval = useState({
            visible: false,
            loading: false,
            enabled: false,
            state: "none",
            instanceId: 0,
            canRequest: false,
        });
        this._occApprovalRequestToken = 0;
        this._occApprovalLastAutoOpenKey = null;
        this._occApprovalDrawerClose = null;

        useEffect(
            (resModel, resId) => {
                this._occCloseApprovalDrawer();
                this._occRefreshApprovalState(resModel, resId);
                return () => this._occCloseApprovalDrawer();
            },
            () => [this.model.root.resModel, this.model.root.resId]
        );
        onWillUnmount(() => {
            this._occApprovalRequestToken += 1;
            this._occCloseApprovalDrawer();
        });
    },

    get occApprovalLabel() {
        if (this.occApproval.state === "none") {
            return this.occApproval.canRequest ? _t("Request approval") : _t("Approval");
        }
        const labels = {
            draft: _t("Approval draft"),
            running: _t("Approval running"),
            rework: _t("Approval rework"),
            approved: _t("Approval approved"),
            cancelled: _t("Approval cancelled"),
        };
        return labels[this.occApproval.state] || _t("Approval");
    },

    get occApprovalTone() {
        return (
            {
                none: "secondary",
                draft: "secondary",
                running: "primary",
                rework: "warning",
                approved: "success",
                cancelled: "secondary",
            }[this.occApproval.state] || "secondary"
        );
    },

    _occApprovalSnapshot() {
        return {
            resModel: this.model.root.resModel,
            resId: Number(this.model.root.resId || 0),
            enabled: this.occApproval.enabled,
            state: this.occApproval.state,
            instanceId: Number(this.occApproval.instanceId || 0),
        };
    },

    async _occRefreshApprovalState(resModel = null, resId = null) {
        const modelName = resModel || this.model.root.resModel;
        const recordId = Number(resId || this.model.root.resId || 0);
        const token = ++this._occApprovalRequestToken;
        if (!modelName || !recordId) {
            Object.assign(this.occApproval, {
                visible: false,
                loading: false,
                enabled: false,
                state: "none",
                instanceId: 0,
                canRequest: false,
            });
            return null;
        }

        this.occApproval.loading = true;
        try {
            const supported = await this.occApprovalApi.supportsModel(modelName);
            if (token !== this._occApprovalRequestToken) {
                return null;
            }
            if (!supported) {
                Object.assign(this.occApproval, {
                    visible: false,
                    enabled: false,
                    state: "none",
                    instanceId: 0,
                    canRequest: false,
                });
                return null;
            }
            const payload = await this.occApprovalApi.getRecordState(modelName, recordId);
            if (
                token !== this._occApprovalRequestToken ||
                this.model.root.resModel !== modelName ||
                Number(this.model.root.resId || 0) !== recordId
            ) {
                return null;
            }
            Object.assign(this.occApproval, {
                visible: Boolean(payload?.enabled),
                enabled: Boolean(payload?.enabled),
                state: payload?.state || "none",
                instanceId: Number(payload?.instance_id || 0),
                canRequest: Boolean(payload?.can_request),
            });
            return payload;
        } catch (error) {
            if (token === this._occApprovalRequestToken) {
                this.occApproval.visible = false;
            }
            const accessError = ["odoo.exceptions.AccessError", "AccessError"].includes(
                error?.data?.name
            );
            if (!accessError) {
                this.occApprovalNotification.add(approvalErrorMessage(error), {
                    title: _t("Approval"),
                    type: "danger",
                });
            }
            return null;
        } finally {
            if (token === this._occApprovalRequestToken) {
                this.occApproval.loading = false;
            }
        }
    },

    onOpenOccApproval() {
        const resModel = this.model.root.resModel;
        const resId = Number(this.model.root.resId || 0);
        if (!resModel || !resId) {
            return;
        }
        this._occApprovalDrawerClose = this.occApprovalDrawer.add(
            ApprovalPanel,
            {
                resModel,
                resId,
                onUpdate: () => this._occRefreshApprovalState(resModel, resId),
            },
            {
                key: `occ-approval:${resModel}:${resId}`,
                onClose: () => {
                    this._occApprovalDrawerClose = null;
                },
            }
        );
    },

    _occCloseApprovalDrawer() {
        const close = this._occApprovalDrawerClose;
        this._occApprovalDrawerClose = null;
        close?.();
    },

    async beforeExecuteActionButton(clickParams) {
        this._occApprovalBeforeButton = this._occApprovalSnapshot();
        return super.beforeExecuteActionButton(...arguments);
    },

    async afterExecuteActionButton(clickParams) {
        await super.afterExecuteActionButton(...arguments);
        if (!clickParams?.name || !this.model.root.resId) {
            return;
        }
        const before = this._occApprovalBeforeButton || {
            state: "none",
            instanceId: 0,
        };
        await this._occRefreshApprovalState();
        const after = this._occApprovalSnapshot();
        const transitioned =
            before.instanceId !== after.instanceId || before.state !== after.state;
        const needsAttention = ["draft", "running", "rework"].includes(after.state);
        const autoOpenKey = `${after.resModel}:${after.resId}:${after.instanceId}:${after.state}`;
        if (
            transitioned &&
            after.enabled &&
            needsAttention &&
            autoOpenKey !== this._occApprovalLastAutoOpenKey
        ) {
            this._occApprovalLastAutoOpenKey = autoOpenKey;
            this.onOpenOccApproval();
        }
    },
});
