import { Plugin } from "@html_editor/plugin";
import { registry } from "@web/core/registry";

class ShareCnBuilderPlugin extends Plugin {
    static id = "occWebsiteCnShareBuilderPlugin";
    resources = {
        // Odoo 19 only creates inner-content drop zones for roots registered
        // in this resource. Without it, the Builder marks the `div` snippet
        // as impossible to drop anywhere on the page.
        so_content_addition_selector: [".s_share_cn"],
        content_not_editable_selectors: [".s_share_cn"],
        content_editable_selectors: [".s_share_cn_title"],
    };
}

registry.category("website-plugins").add(ShareCnBuilderPlugin.id, ShareCnBuilderPlugin);
