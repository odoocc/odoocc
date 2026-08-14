/** @odoo-module **/

import { HtmlField } from "@html_editor/fields/html_field";
import { patch } from "@web/core/utils/patch";

import { OccMarkdownPlugin } from "./markdown_plugin";

patch(HtmlField.prototype, {
    getConfig() {
        const config = super.getConfig(...arguments);
        config.Plugins = config.Plugins || [];
        if (!config.Plugins.includes(OccMarkdownPlugin)) {
            config.Plugins = [...config.Plugins, OccMarkdownPlugin];
        }
        return config;
    },
});
