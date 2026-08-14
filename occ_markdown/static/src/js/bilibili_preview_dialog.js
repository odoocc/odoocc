/** @odoo-module **/

import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class BilibiliPreviewDialog extends Component {
    static template = "occ_markdown.BilibiliPreviewDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        playerUrl: String,
        videoLabel: String,
    };
}
