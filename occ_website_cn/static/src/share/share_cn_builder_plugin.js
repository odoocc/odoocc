import { Plugin } from "@html_editor/plugin";
import { registry } from "@web/core/registry";

class ShareCnBuilderPlugin extends Plugin {
    static id = "occWebsiteCnShareBuilderPlugin";
    resources = {
        content_not_editable_selectors: [".s_share_cn"],
        content_editable_selectors: [".s_share_cn_title"],
    };
}

registry.category("website-plugins").add(ShareCnBuilderPlugin.id, ShareCnBuilderPlugin);

