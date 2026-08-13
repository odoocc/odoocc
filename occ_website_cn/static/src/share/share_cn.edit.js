import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";

export class ShareCnEdit extends Interaction {
    static selector = ".s_share_cn";
}

registry.category("public.interactions.edit").add("occ_website_cn.share_cn", {
    Interaction: ShareCnEdit,
});

