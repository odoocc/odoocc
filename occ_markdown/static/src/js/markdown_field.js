/** @odoo-module **/

import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

import { OccMarkdownEditor } from "./markdown_editor";

export class OccMarkdownField extends Component {
    static template = "occ_markdown.MarkdownField";
    static components = { OccMarkdownEditor };
    static props = {
        ...standardFieldProps,
        stripEmojiField: { type: String, optional: true },
        createTocField: { type: String, optional: true },
        enableImages: { type: Boolean, optional: true },
        enableBilibili: { type: Boolean, optional: true },
        minHeight: { type: Number, optional: true },
    };

    get value() {
        return this.props.record.data[this.props.name] || "";
    }

    get stripEmoji() {
        return Boolean(
            this.props.stripEmojiField && this.props.record.data[this.props.stripEmojiField]
        );
    }

    get createToc() {
        return Boolean(
            this.props.createTocField && this.props.record.data[this.props.createTocField]
        );
    }

    get showStripEmoji() {
        return Boolean(this.props.stripEmojiField);
    }

    get showCreateToc() {
        return Boolean(this.props.createTocField);
    }

    onChange(value) {
        return this.props.record.update({ [this.props.name]: value });
    }

    onOptionChange(name, value) {
        const fieldName = name === "stripEmoji" ? this.props.stripEmojiField : this.props.createTocField;
        if (fieldName) {
            return this.props.record.update({ [fieldName]: value });
        }
    }
}

registry.category("fields").add("occ_markdown", {
    component: OccMarkdownField,
    displayName: _t("Markdown 所见即所得编辑器"),
    supportedTypes: ["text"],
    extractProps({ options }) {
        return {
            stripEmojiField: options.strip_emoji_field,
            createTocField: options.create_toc_field,
            enableImages: options.enable_images !== false,
            enableBilibili: options.enable_bilibili !== false,
            minHeight: options.min_height || 520,
        };
    },
});
