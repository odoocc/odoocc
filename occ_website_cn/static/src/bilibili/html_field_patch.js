/** @odoo-module **/

import { HtmlField } from "@html_editor/fields/html_field";
import { patch } from "@web/core/utils/patch";

import { BilibiliPastePlugin } from "./bilibili_paste_plugin";


patch(HtmlField.prototype, {
    getConfig() {
        const config = super.getConfig(...arguments);
        if (
            config.allowVideo !== false &&
            !config.Plugins.some((PluginClass) => PluginClass.id === BilibiliPastePlugin.id)
        ) {
            config.Plugins = [...config.Plugins, BilibiliPastePlugin];
        }
        return config;
    },
});
