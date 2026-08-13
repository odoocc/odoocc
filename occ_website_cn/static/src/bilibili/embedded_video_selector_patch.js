/** @odoo-module **/

import { EmbeddedVideoSelector } from "@html_editor/others/embedded_components/plugins/video_plugin/video_selector_dialog/embedded_video_selector";
import { patch } from "@web/core/utils/patch";

import { BILIBILI_PLATFORM } from "./bilibili_parser";


patch(EmbeddedVideoSelector, {
    createElements(selectedMedia) {
        const elements = super.createElements(...arguments);
        selectedMedia.forEach((media, index) => {
            if (media.platform === BILIBILI_PLATFORM) {
                // This stable class lets website QWeb mark the dynamic iframe
                // container for Odoo's optional-cookie approval workflow.
                elements[index].classList.add("occ_bilibili_embedded_video");
            }
        });
        return elements;
    },
});
