/** @odoo-module **/

import { ListController } from "@web/views/list/list_controller";

export class TreeGridListController extends ListController {
    get modelParams() {
        return {
            ...super.modelParams,
            treeGrid: this.archInfo.treeGrid,
        };
    }
}

