/** @odoo-module **/

import { beforeEach, describe, expect, test } from "@odoo/hoot";
import { advanceTime, animationFrame, microTick } from "@odoo/hoot-mock";
import {
    contains,
    mountWithCleanup,
    onRpc,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";

import { OccMarkdownEditor } from "../src/js/markdown_editor";
import { OccMarkdownField } from "../src/js/markdown_field";

describe.current.tags("desktop", "occ_markdown");

let instances;
let serverCalls;

class FakeVditor {
    constructor(host, options) {
        this.host = host;
        this.options = options;
        this.value = options.value;
        this.mode = options.mode;
        instances.push(this);
        this.render();
        Promise.resolve().then(() => options.after());
    }

    render() {
        this.host.innerHTML = this.mode === "wysiwyg"
            ? `<div class="vditor-wysiwyg"><p>${this.value}</p></div>`
            : `<div class="vditor-sv">${this.value}</div>`;
    }

    getValue() {
        return this.value;
    }

    setValue(value) {
        this.value = value;
        this.render();
    }

    insertMD(value) {
        this.value += value;
        this.render();
    }

    disabled() {}

    destroy() {
        this.host.replaceChildren();
    }
}

beforeEach(() => {
    instances = [];
    serverCalls = 0;
    patchWithCleanup(window, { Vditor: FakeVditor });
    onRpc("occ.markdown.service", "convert_markdown", ({ args }) => {
        serverCalls++;
        return `<h1 class="server-result">${args[0].replace(/^# /, "")}</h1>`;
    });
    onRpc("ir.attachment", "generate_access_token", () => ["安全令牌"]);
});

async function mountEditor(props = {}) {
    const component = await mountWithCleanup(OccMarkdownEditor, {
        props: {
            value: "# 初始标题",
            onChange: () => {},
            resModel: "occ.markdown.demo",
            resId: 1,
            ...props,
        },
    });
    await microTick();
    return component;
}

test("字段组件可渲染配置的中文转换选项", async () => {
    await mountWithCleanup(OccMarkdownField, {
        props: {
            name: "markdown_source",
            record: {
                data: {
                    markdown_source: "# 初始标题",
                    markdown_strip_emoji: false,
                    markdown_create_toc: true,
                },
                resModel: "occ.markdown.demo",
                resId: 1,
                update: () => {},
            },
            stripEmojiField: "markdown_strip_emoji",
            createTocField: "markdown_create_toc",
            enableImages: true,
            enableBilibili: true,
            minHeight: 520,
        },
    });
    await microTick();
    expect(".o_occ_markdown_editor").toHaveText(/清除表情符号/);
    expect(".o_occ_markdown_editor").toHaveText(/生成目录/);
});

test("默认只显示单窗口所见即所得编辑器", async () => {
    await mountEditor();
    expect(instances).toHaveLength(1);
    expect(instances[0].mode).toBe("wysiwyg");
    expect(".vditor-wysiwyg").toHaveCount(1);
    expect(".o_occ_markdown_server_preview").toHaveCount(0);
    expect(".o_occ_markdown_mode_wysiwyg").toHaveClass("btn-primary");
});

test("三种单窗模式切换时保留Markdown", async () => {
    await mountEditor();
    await contains(".o_occ_markdown_mode_source").click();
    await microTick();
    expect(instances.at(-1).mode).toBe("sv");
    expect(instances.at(-1).value).toBe("# 初始标题");
    expect(".vditor-wysiwyg").toHaveCount(0);

    await contains(".o_occ_markdown_mode_server").click();
    await microTick();
    expect(".o_occ_markdown_server_preview").toHaveCount(1);
    expect(".server-result").toHaveText("初始标题");

    await contains(".o_occ_markdown_mode_wysiwyg").click();
    await microTick();
    expect(instances.at(-1).mode).toBe("wysiwyg");
    expect(instances.at(-1).value).toBe("# 初始标题");
});

test("未保存记录禁止本地图片并显示中文说明", async () => {
    await mountEditor({ resId: false });
    expect(".o_occ_markdown_image_button").toHaveAttribute("disabled");
    expect(".o_occ_markdown_editor").toHaveText(/保存记录后即可粘贴本地图片/);
});

test("所见即所得模式显示可点击播放的B站预览卡片", async () => {
    await mountEditor({ value: "{{bilibili:BV1xx411c7mD|page=2}}" });
    await animationFrame();
    expect(".o_occ_markdown_bilibili_card").toHaveCount(1);
    expect(".o_occ_markdown_bilibili_card").toHaveAttribute(
        "data-video-label",
        "B站视频：BV1xx411c7mD，第2P · 点击播放"
    );
    expect("iframe").toHaveCount(0);
    await contains(".o_occ_markdown_bilibili_card").click();
    await microTick();
    expect(".modal iframe[title='B站视频预览']").toHaveAttribute(
        "data-player-url",
        "https://player.bilibili.com/player.html?bvid=BV1xx411c7mD&page=2&autoplay=0"
    );
    expect(".modal").toHaveText(/播放器由B站提供/);
});

test("插入B站视频后立即显示可播放预览", async () => {
    patchWithCleanup(window, { prompt: () => "BV1xx411c7mD" });
    await mountEditor({ value: "" });
    await contains("button[title='插入B站视频']").click();
    await microTick();
    expect(instances.at(-1).value).toInclude("{{bilibili:BV1xx411c7mD}}");
    expect(".modal iframe[title='B站视频预览']").toHaveAttribute(
        "data-player-url",
        "https://player.bilibili.com/player.html?bvid=BV1xx411c7mD&page=1&autoplay=0"
    );
});

test("输入后约500毫秒防抖调用同一个服务端转换器", async () => {
    await mountEditor();
    expect(serverCalls).toBe(1);
    instances[0].options.input("# 新标题");
    await advanceTime(499);
    expect(serverCalls).toBe(1);
    await advanceTime(1);
    await microTick();
    expect(serverCalls).toBe(2);
});

test("粘贴网络图片地址转换为Markdown图片", async () => {
    let changedValue = "";
    const component = await mountEditor({ onChange: (value) => (changedValue = value) });
    await component.onPaste({
        clipboardData: {
            items: [],
            getData: (type) =>
                type === "text/plain" ? "https://example.com/photo.png" : "",
        },
        preventDefault: () => {},
        stopImmediatePropagation: () => {},
    });
    expect(changedValue).toInclude("![图片](https://example.com/photo.png)");
});

test("网页图片剪贴板优先保留网络地址而不要求记录已保存", async () => {
    let changedValue = "";
    const component = await mountEditor({
        resId: false,
        onChange: (value) => (changedValue = value),
    });
    await component.onPaste({
        clipboardData: {
            items: [
                {
                    kind: "file",
                    type: "image/png",
                    getAsFile: () => new File([], "图.png"),
                },
            ],
            getData: (type) =>
                type === "text/html"
                    ? '<img src="https://example.com/web-image" alt="网页配图">'
                    : "",
        },
        preventDefault: () => {},
        stopImmediatePropagation: () => {},
    });
    expect(changedValue).toInclude("![网页配图](https://example.com/web-image)");
});

test("粘贴飞书或网页HTML表格时保留粗体和中文业务内容", async () => {
    let changedValue = "";
    const component = await mountEditor({ onChange: (value) => (changedValue = value) });
    await component.onPaste({
        clipboardData: {
            items: [],
            getData: (type) =>
                type === "text/html"
                    ? `<table><tr><th>端到端流程</th><th>英文缩写</th><th>贯穿的核心模块</th></tr>
                       <tr><td><strong>线索到回款</strong></td><td>LTC（Lead to Cash）</td><td>CRM → 销售 → 会计</td></tr></table>`
                    : "",
        },
        preventDefault: () => {},
        stopImmediatePropagation: () => {},
    });
    expect(changedValue).toInclude("| 端到端流程 | 英文缩写 | 贯穿的核心模块 |");
    expect(changedValue).toInclude("| **线索到回款** | LTC（Lead to Cash） | CRM → 销售 → 会计 |");
});

test("粘贴Excel制表符表格时转换为Markdown表格", async () => {
    let changedValue = "";
    const component = await mountEditor({ onChange: (value) => (changedValue = value) });
    await component.onPaste({
        clipboardData: {
            items: [],
            getData: (type) =>
                type === "text/plain"
                    ? "端到端流程\t英文缩写\n采购到付款\tPTP（Procure to Pay）"
                    : "",
        },
        preventDefault: () => {},
        stopImmediatePropagation: () => {},
    });
    expect(changedValue).toInclude("| 端到端流程 | 英文缩写 |");
    expect(changedValue).toInclude("| 采购到付款 | PTP（Procure to Pay） |");
});

test("粘贴flowchart流程图时转换为本地Mermaid代码块", async () => {
    let changedValue = "";
    const component = await mountEditor({ onChange: (value) => (changedValue = value) });
    await component.onPaste({
        clipboardData: {
            items: [],
            getData: (type) =>
                type === "text/plain"
                    ? "flowchart TD\n    A[CRM线索管理] --> B[生成报价单]\n    B --> C{报价审核}"
                    : "",
        },
        preventDefault: () => {},
        stopImmediatePropagation: () => {},
    });
    expect(changedValue).toInclude("```mermaid\nflowchart TD");
    expect(changedValue).toInclude("A[CRM线索管理] --> B[生成报价单]");
});

test("本地剪贴板图片上传后为私有附件增加访问令牌", async () => {
    let changedValue = "";
    const component = await mountEditor({ onChange: (value) => (changedValue = value) });
    component.uploadService = {
        async uploadFiles(_files, _recordInfo, onUploaded) {
            onUploaded({ id: 42, name: "截图.png", public: false, url: false });
        },
    };
    await component.uploadImages([new File(["image"], "截图.png", { type: "image/png" })]);
    expect(changedValue).toInclude(
        "![截图](/web/image/ir.attachment/42/datas?access_token=%E5%AE%89%E5%85%A8%E4%BB%A4%E7%89%8C)"
    );
});
