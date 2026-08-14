/** @odoo-module **/

import { Plugin } from "@html_editor/plugin";
import { withSequence } from "@html_editor/utils/resource";
import { _t } from "@web/core/l10n/translation";

import { OccMarkdownDialog } from "./markdown_dialog";

export class OccMarkdownPlugin extends Plugin {
    static id = "occMarkdown";
    static dependencies = ["dialog", "dom", "history"];

    resources = {
        user_commands: [
            {
                id: "occInsertMarkdown",
                title: _t("Markdown"),
                description: _t("使用 Markdown 编写并插入排版内容"),
                icon: "fa-file-code-o",
                run: this.openDialog.bind(this),
            },
        ],
        powerbox_categories: withSequence(60, {
            id: "occMarkdown",
            name: _t("Markdown"),
        }),
        powerbox_items: withSequence(10, {
            categoryId: "occMarkdown",
            commandId: "occInsertMarkdown",
        }),
    };

    openDialog() {
        const record = this.config.getRecordInfo?.() || {};
        this.dependencies.dialog.addDialog(OccMarkdownDialog, {
            resModel: record.resModel,
            resId: record.resId || false,
            insert: (content) => {
                this.dependencies.dom.insert(content);
                this.dependencies.history.addStep();
            },
        });
    }
}
