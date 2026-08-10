/** @odoo-module **/

import { registry } from "@web/core/registry";

import "./api";
import "./services/drawer_service";
import { ApprovalDesigner } from "./components/designer/designer";
import { ApprovalDashboard } from "./components/dashboard/dashboard";
import "./form/form_controller_patch";

registry.category("actions").add("occ_approval.designer", ApprovalDesigner);
registry.category("actions").add("occ_approval.dashboard", ApprovalDashboard);
