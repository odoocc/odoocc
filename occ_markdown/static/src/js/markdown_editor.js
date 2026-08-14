/** @odoo-module **/

import { MediaDialog, TABS } from "@html_editor/main/media/media_dialog/media_dialog";
import {
    markup,
    Component,
    onMounted,
    onWillDestroy,
    onWillUpdateProps,
    useRef,
    useState,
} from "@odoo/owl";
import { parseBilibiliVideo } from "@occ_base_bilibili/bilibili_parser";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";

import { BilibiliPreviewDialog } from "./bilibili_preview_dialog";

const BILIBILI_MARKER_RE =
    /^\{\{bilibili:(BV[A-Za-z0-9]{10}|av[1-9][0-9]*)(?:\|page=((?:[1-9][0-9]{0,3}|10000)))?\}\}$/;

export class OccMarkdownEditor extends Component {
    static template = "occ_markdown.MarkdownEditor";
    static props = {
        value: { type: String, optional: true },
        onChange: Function,
        readonly: { type: Boolean, optional: true },
        resModel: { type: String, optional: true },
        resId: { type: [Number, Boolean], optional: true },
        stripEmoji: { type: Boolean, optional: true },
        createToc: { type: Boolean, optional: true },
        showStripEmoji: { type: Boolean, optional: true },
        showCreateToc: { type: Boolean, optional: true },
        onOptionChange: { type: Function, optional: true },
        enableImages: { type: Boolean, optional: true },
        enableBilibili: { type: Boolean, optional: true },
        minHeight: { type: Number, optional: true },
    };
    static defaultProps = {
        value: "",
        readonly: false,
        resId: false,
        stripEmoji: false,
        createToc: false,
        showStripEmoji: false,
        showCreateToc: false,
        enableImages: true,
        enableBilibili: true,
        minHeight: 520,
    };

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.uploadService = useService("upload");
        this.host = useRef("editorHost");
        this.state = useState({
            mode: "wysiwyg",
            serverHtml: "",
            previewLoading: false,
            previewError: false,
            uploadingImage: false,
        });
        this.currentValue = this.props.value || "";
        this.previewSequence = 0;
        this.debouncedPreview = useDebounced(() => this.updateServerPreview(), 500);
        this.onPasteCapture = (event) => this.onPaste(event);
        this.onBilibiliCardClick = (event) => this.openBilibiliCard(event);
        this.onBilibiliCardKeydown = (event) => {
            if (["Enter", " "].includes(event.key)) {
                this.openBilibiliCard(event);
            }
        };
        onMounted(() => this.mountVditor());
        onWillUpdateProps((nextProps) => {
            if (nextProps.value !== this.props.value && nextProps.value !== this.currentValue) {
                this.currentValue = nextProps.value || "";
                this.editor?.setValue(this.currentValue);
                this.debouncedPreview();
            }
            if (
                nextProps.stripEmoji !== this.props.stripEmoji ||
                nextProps.createToc !== this.props.createToc
            ) {
                this.debouncedPreview();
            }
        });
        onWillDestroy(() => {
            this.host.el?.removeEventListener("paste", this.onPasteCapture, true);
            this.host.el?.removeEventListener("click", this.onBilibiliCardClick, true);
            this.host.el?.removeEventListener("keydown", this.onBilibiliCardKeydown, true);
            this.editor?.destroy?.();
        });
    }

    get serverMarkup() {
        return markup(this.state.serverHtml || "");
    }

    get canUpload() {
        return Boolean(this.props.resModel && this.props.resId && !this.props.readonly);
    }

    mountVditor() {
        if (!window.Vditor) {
            this.notification.add(_t("Markdown 编辑器资源加载失败。"), { type: "danger" });
            return;
        }
        this.createVditor("wysiwyg");
        this.host.el.addEventListener("paste", this.onPasteCapture, true);
        this.host.el.addEventListener("click", this.onBilibiliCardClick, true);
        this.host.el.addEventListener("keydown", this.onBilibiliCardKeydown, true);
    }

    createVditor(mode) {
        this.editor?.destroy?.();
        this.editor = new window.Vditor(this.host.el, {
            cdn: "/occ_markdown/static/lib/vditor",
            lang: "zh_CN",
            icon: "material",
            mode,
            value: this.currentValue,
            height: "auto",
            minHeight: this.props.minHeight,
            cache: { enable: false },
            counter: { enable: true, type: "text" },
            toolbar: [
                "headings",
                "bold",
                "italic",
                "strike",
                "|",
                "list",
                "ordered-list",
                "check",
                "quote",
                "code",
                "inline-code",
                "table",
                "link",
                "|",
                "undo",
                "redo",
            ],
            preview: { hljs: { enable: false } },
            input: (value) => this.onEditorInput(value),
            after: () => {
                if (this.props.readonly) {
                    this.editor.disabled();
                }
                this.decorateBilibiliCards();
                this.updateServerPreview();
            },
        });
    }

    onEditorInput(value) {
        if (this.props.readonly) {
            return;
        }
        this.currentValue = value;
        this.props.onChange(value);
        this.decorateBilibiliCards();
        this.debouncedPreview();
    }

    async setMode(mode) {
        if (mode === this.state.mode) {
            return;
        }
        if (mode === "server") {
            this.currentValue = this.editor?.getValue() || this.currentValue;
            await this.updateServerPreview();
            this.state.mode = "server";
            return;
        }
        this.currentValue = this.editor?.getValue() || this.currentValue;
        this.state.mode = mode;
        this.createVditor(mode === "source" ? "sv" : "wysiwyg");
    }

    conversionOptions() {
        return {
            strip_emoji: Boolean(this.props.stripEmoji),
            create_toc: Boolean(this.props.createToc),
            allow_bilibili: Boolean(this.props.enableBilibili),
        };
    }

    async updateServerPreview() {
        const sequence = ++this.previewSequence;
        if (!this.currentValue.trim()) {
            this.state.serverHtml = "";
            this.state.previewError = false;
            return;
        }
        this.state.previewLoading = true;
        try {
            const html = await this.orm.call("occ.markdown.service", "convert_markdown", [
                this.currentValue,
                this.conversionOptions(),
            ]);
            if (sequence === this.previewSequence) {
                this.state.serverHtml = html;
                this.state.previewError = false;
            }
        } catch {
            if (sequence === this.previewSequence) {
                this.state.previewError = true;
                this.notification.add(_t("服务端 Markdown 效果生成失败。"), {
                    type: "danger",
                });
            }
        } finally {
            if (sequence === this.previewSequence) {
                this.state.previewLoading = false;
            }
        }
    }

    decorateBilibiliCards() {
        if (!this.props.enableBilibili || !this.host.el) {
            return;
        }
        requestAnimationFrame(() => {
            for (const block of this.host.el.querySelectorAll(".vditor-wysiwyg p")) {
                const match = block.textContent.trim().match(BILIBILI_MARKER_RE);
                block.classList.toggle("o_occ_markdown_bilibili_card", Boolean(match));
                if (match) {
                    block.dataset.videoLabel = `B站视频：${match[1]}${
                        match[2] ? `，第${match[2]}P` : ""
                    } · 点击播放`;
                    block.setAttribute("role", "button");
                    block.setAttribute("tabindex", "0");
                    block.setAttribute("title", "点击播放B站视频预览");
                } else {
                    delete block.dataset.videoLabel;
                    block.removeAttribute("role");
                    block.removeAttribute("tabindex");
                    block.removeAttribute("title");
                }
            }
        });
    }

    openBilibiliCard(event) {
        const card = event.target.closest?.(".o_occ_markdown_bilibili_card");
        if (!card || !this.host.el?.contains(card)) {
            return;
        }
        const match = card.textContent.trim().match(BILIBILI_MARKER_RE);
        if (!match) {
            return;
        }
        const video = this.parseBilibili(
            `https://www.bilibili.com/video/${match[1]}?p=${match[2] || 1}`
        );
        if (!video) {
            return;
        }
        event.preventDefault();
        event.stopImmediatePropagation();
        this.showBilibiliPreview(video);
    }

    showBilibiliPreview(video) {
        this.dialog.add(BilibiliPreviewDialog, {
            playerUrl: video.embedUrl,
            videoLabel: `${video.videoId}${video.params.page > 1 ? `，第${video.params.page}P` : ""}`,
        });
    }

    imageMarkdown(alt, src) {
        return `![${(alt || _t("图片")).replaceAll("]", "\\]")}](${src})`;
    }

    insertMarkdown(markdown) {
        this.editor?.insertMD(`\n\n${markdown}\n\n`);
        this.currentValue = this.editor?.getValue() || this.currentValue;
        this.props.onChange(this.currentValue);
        this.debouncedPreview();
    }

    bilibiliMarker(video) {
        const videoId = video.videoId.startsWith("BV") ? video.videoId : `av${video.videoId}`;
        const page = video.params.page === 1 ? "" : `|page=${video.params.page}`;
        return `{{bilibili:${videoId}${page}}}`;
    }

    parseBilibili(value) {
        return parseBilibiliVideo(value, { allowBareBvid: true });
    }

    insertBilibiliVideo() {
        const value = window.prompt(_t("请输入B站视频地址、BV号或av号"));
        if (value === null) {
            return;
        }
        const video = this.parseBilibili(value.trim());
        if (!video) {
            this.notification.add(_t("无法识别B站视频，请检查地址或视频号。"), {
                type: "warning",
            });
            return;
        }
        this.insertMarkdown(this.bilibiliMarker(video));
        this.showBilibiliPreview(video);
    }

    openMediaDialog() {
        if (!this.canUpload) {
            this.notification.add(_t("请先保存记录，再插入本地图片。"), {
                type: "warning",
            });
            return;
        }
        this.dialog.add(MediaDialog, {
            activeTab: TABS.IMAGES.id,
            visibleTabs: [TABS.IMAGES.id],
            onlyImages: true,
            useMediaLibrary: true,
            resModel: this.props.resModel,
            resId: this.props.resId,
            onAttachmentChange: () => {},
            save: (element) => {
                const src = element?.getAttribute("src");
                if (src) {
                    this.insertMarkdown(
                        this.imageMarkdown(element.getAttribute("alt") || _t("图片"), src)
                    );
                }
            },
        });
    }

    isNetworkImageUrl(value) {
        try {
            const url = new URL(value);
            return (
                ["http:", "https:"].includes(url.protocol) &&
                /\.(?:avif|gif|jpe?g|png|svg|webp)$/i.test(url.pathname)
            );
        } catch {
            return false;
        }
    }

    async attachmentUrl(attachment) {
        let src = attachment.image_src || `/web/image/ir.attachment/${attachment.id}/datas`;
        if (!attachment.public && !attachment.url) {
            let token = attachment.access_token;
            if (!token) {
                [token] = await this.orm.call("ir.attachment", "generate_access_token", [
                    attachment.id,
                ]);
            }
            src += `${src.includes("?") ? "&" : "?"}access_token=${encodeURIComponent(token)}`;
        }
        return src;
    }

    async uploadImages(files) {
        if (!this.canUpload) {
            this.notification.add(_t("请先保存记录，再粘贴本地图片。"), {
                type: "warning",
            });
            return;
        }
        this.state.uploadingImage = true;
        const attachments = [];
        try {
            await this.uploadService.uploadFiles(
                files,
                { resModel: this.props.resModel, resId: this.props.resId, isImage: true },
                (attachment) => attachments.push(attachment)
            );
            const images = await Promise.all(
                attachments.map(async (attachment) =>
                    this.imageMarkdown(
                        (attachment.name || _t("图片")).replace(/\.[^.]+$/, ""),
                        await this.attachmentUrl(attachment)
                    )
                )
            );
            if (images.length) {
                this.insertMarkdown(images.join("\n\n"));
            }
        } catch {
            this.notification.add(_t("剪贴板图片上传失败，请重试。"), { type: "danger" });
        } finally {
            this.state.uploadingImage = false;
        }
    }

    tableCellMarkdown(cell) {
        const convertNode = (node) => {
            if (node.nodeType === Node.TEXT_NODE) {
                return node.nodeValue.replace(/\s+/g, " ");
            }
            if (node.nodeType !== Node.ELEMENT_NODE) {
                return "";
            }
            const content = Array.from(node.childNodes).map(convertNode).join("");
            const tagName = node.tagName.toLowerCase();
            if (["strong", "b"].includes(tagName)) {
                return `**${content.trim()}**`;
            }
            if (["em", "i"].includes(tagName)) {
                return `*${content.trim()}*`;
            }
            if (tagName === "br") {
                return "<br>";
            }
            if (tagName === "code") {
                return `\`${content.replaceAll("`", "\\`").trim()}\``;
            }
            if (tagName === "a") {
                const href = node.getAttribute("href") || "";
                return this.isSafeHttpUrl(href) ? `[${content.trim()}](${href})` : content;
            }
            if (tagName === "img" && this.props.enableImages) {
                const src = node.getAttribute("src") || "";
                return this.isSafeHttpUrl(src)
                    ? this.imageMarkdown(node.getAttribute("alt") || _t("图片"), src)
                    : "";
            }
            return content;
        };
        return Array.from(cell.childNodes)
            .map(convertNode)
            .join("")
            .replace(/\|/g, "\\|")
            .trim();
    }

    rowsToMarkdownTable(rows) {
        const columnCount = Math.max(0, ...rows.map((row) => row.length));
        if (rows.length < 2 || columnCount < 2) {
            return "";
        }
        const normalizeRow = (row) => [
            ...row,
            ...Array(Math.max(0, columnCount - row.length)).fill(""),
        ];
        const renderRow = (row) => `| ${normalizeRow(row).join(" | ")} |`;
        return [
            renderRow(rows[0]),
            renderRow(Array(columnCount).fill("---")),
            ...rows.slice(1).map(renderRow),
        ].join("\n");
    }

    htmlTableToMarkdown(table) {
        if (!table) {
            return "";
        }
        const rows = Array.from(table.querySelectorAll("tr"))
            .map((row) =>
                Array.from(row.children)
                    .filter((cell) => ["TH", "TD"].includes(cell.tagName))
                    .map((cell) => this.tableCellMarkdown(cell))
            )
            .filter((row) => row.length);
        return this.rowsToMarkdownTable(rows);
    }

    tabularTextToMarkdown(text) {
        const lines = text.replace(/\r\n?/g, "\n").split("\n").filter((line) => line.trim());
        if (lines.length < 2 || lines.some((line) => !line.includes("\t"))) {
            return "";
        }
        const rows = lines.map((line) =>
            line.split("\t").map((cell) => cell.trim().replace(/\|/g, "\\|"))
        );
        return this.rowsToMarkdownTable(rows);
    }

    mermaidFlowchartMarkdown(text) {
        const source = text.trim();
        if (
            source.length > 50000 ||
            !/^flowchart\s+(?:TD|TB|BT|LR|RL)\b/i.test(source) ||
            !/\n/.test(source) ||
            /(?:javascript:|<\s*script\b|^\s*click\b|^\s*%%\{)/im.test(source)
        ) {
            return "";
        }
        return `\`\`\`mermaid\n${source}\n\`\`\``;
    }

    async onPaste(event) {
        if (this.props.readonly || !event.clipboardData) {
            return;
        }
        const clipboardHtml = event.clipboardData.getData("text/html");
        const template = document.createElement("template");
        template.innerHTML = clipboardHtml;
        const markdownTable = this.htmlTableToMarkdown(template.content.querySelector("table"));
        if (markdownTable) {
            event.preventDefault();
            event.stopImmediatePropagation();
            this.insertMarkdown(markdownTable);
            return;
        }
        const networkImage = template.content.querySelector("img[src]");
        const networkImageSrc = networkImage?.getAttribute("src") || "";
        if (
            this.props.enableImages &&
            networkImage &&
            this.isSafeHttpUrl(networkImageSrc)
        ) {
            event.preventDefault();
            event.stopImmediatePropagation();
            this.insertMarkdown(
                this.imageMarkdown(
                    networkImage.getAttribute("alt") || _t("图片"),
                    networkImageSrc
                )
            );
            return;
        }
        const imageFiles = Array.from(event.clipboardData.items || [])
            .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
            .map((item) => item.getAsFile())
            .filter(Boolean);
        if (imageFiles.length && this.props.enableImages) {
            event.preventDefault();
            event.stopImmediatePropagation();
            await this.uploadImages(imageFiles);
            return;
        }
        const text = event.clipboardData.getData("text/plain").trim();
        const tabularMarkdown = this.tabularTextToMarkdown(text);
        if (tabularMarkdown) {
            event.preventDefault();
            event.stopImmediatePropagation();
            this.insertMarkdown(tabularMarkdown);
            return;
        }
        const mermaidMarkdown = this.mermaidFlowchartMarkdown(text);
        if (mermaidMarkdown) {
            event.preventDefault();
            event.stopImmediatePropagation();
            this.insertMarkdown(mermaidMarkdown);
            return;
        }
        if (this.props.enableBilibili) {
            const video = this.parseBilibili(text);
            if (video) {
                event.preventDefault();
                event.stopImmediatePropagation();
                this.insertMarkdown(this.bilibiliMarker(video));
                this.showBilibiliPreview(video);
                return;
            }
        }
        if (this.props.enableImages && this.isNetworkImageUrl(text)) {
            event.preventDefault();
            event.stopImmediatePropagation();
            this.insertMarkdown(this.imageMarkdown(_t("图片"), text));
        }
    }

    isSafeHttpUrl(value) {
        try {
            return ["http:", "https:"].includes(new URL(value).protocol);
        } catch {
            return false;
        }
    }

    onOptionChange(name, event) {
        this.props.onOptionChange?.(name, event.target.checked);
        this.debouncedPreview();
    }
}
