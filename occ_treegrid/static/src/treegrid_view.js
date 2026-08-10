/** @odoo-module **/

import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { TreeGridListArchParser } from "./treegrid_arch_parser";
import { TreeGridListController } from "./treegrid_controller";
import { TreeGridRelationalModel } from "./treegrid_model";
import { TreeGridListRenderer } from "./treegrid_renderer";

export const treeGridListView = {
    ...listView,
    ArchParser: TreeGridListArchParser,
    Controller: TreeGridListController,
    Model: TreeGridRelationalModel,
    Renderer: TreeGridListRenderer,
    canOrderByCount: false,
    hideCustomGroupBy: true,
    searchMenuTypes: ["filter", "favorite"],
};

registry.category("views").add("occ_treegrid", treeGridListView);

