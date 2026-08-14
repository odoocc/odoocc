/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";

import { OccMarkdownEditor } from "./markdown_editor";

export class OccMarkdownDialog extends Component {
    static template = "occ_markdown.MarkdownDialog";
    static components = { Dialog, OccMarkdownEditor };
    static props = {
        insert: Function,
        close: Function,
        resModel: { type: String, optional: true },
        resId: { type: [Number, Boolean], optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            value: "",
            stripEmoji: false,
            createToc: false,
            saving: false,
        });
    }

    onChange(value) {
        this.state.value = value;
    }

    onOptionChange(name, value) {
        if (name === "stripEmoji") {
            this.state.stripEmoji = value;
        } else {
            this.state.createToc = value;
        }
    }

    async confirm() {
        if (!this.state.value.trim()) {
            this.props.close();
            return;
        }
        this.state.saving = true;
        try {
            const html = await this.orm.call("occ.markdown.service", "convert_markdown", [
                this.state.value,
                {
                    strip_emoji: this.state.stripEmoji,
                    create_toc: this.state.createToc,
                    allow_bilibili: true,
                },
            ]);
            const template = document.createElement("template");
            template.innerHTML = html;
            this.props.insert(template.content);
            this.props.close();
        } finally {
            this.state.saving = false;
        }
    }
}
