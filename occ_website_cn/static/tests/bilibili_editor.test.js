/** @odoo-module **/

import { describe, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup, onRpc } from "@web/../tests/web_test_helpers";

import { EmbeddedVideoSelector } from "@html_editor/others/embedded_components/plugins/video_plugin/video_selector_dialog/embedded_video_selector";
import { EmbeddedVideoComponent } from "@html_editor/others/embedded_components/backend/video/video";
import { CustomMediaDialog } from "@html_editor/fields/x2many_field/custom_media_dialog";
import { HtmlField } from "@html_editor/fields/html_field";
import { VideoSelector } from "@html_editor/main/media/media_dialog/video_selector";

import { BilibiliPastePlugin } from "@occ_website_cn/bilibili/bilibili_paste_plugin";
import "@occ_website_cn/bilibili/embedded_video_selector_patch";
import "@occ_website_cn/bilibili/html_field_patch";
import "@occ_website_cn/bilibili/product_media_guard_patch";


describe.current.tags("headless", "occ_website_cn");

// Mounting any OWL component starts Website's mail service. This suite does
// not exercise messaging, so isolate it from mail's large mock model graph.
onRpc("/mail/data", () => ({}));

const VIDEO = {
    src: "https://player.bilibili.com/player.html?bvid=BV1xx411c7mD&page=2&autoplay=0",
    platform: "bilibili",
    videoId: "BV1xx411c7mD",
    params: { page: 2, autoplay: 0 },
};

test("media selector support hint includes Bilibili", async () => {
    await mountWithCleanup(VideoSelector, {
        props: { selectMedia: () => {}, errorMessages: () => {} },
    });
    expect(".o_video_dialog_form .text-muted").toHaveText(/Bilibili \(B站\)/);
});

test("regular media selector creates a Website-compatible video container", () => {
    const [element] = VideoSelector.createElements([VIDEO]);
    expect(element.dataset.oeExpression).toBe(VIDEO.src);
    expect(element.querySelector("iframe").src).toBe(VIDEO.src);
});

test("embedded selector saves Bilibili props and cookie marker without media iframe class", () => {
    const [element] = EmbeddedVideoSelector.createElements([VIDEO]);
    expect(element.classList.contains("occ_bilibili_embedded_video")).toBe(true);
    expect(element.classList.contains("media_iframe_video")).toBe(false);
    expect(JSON.parse(element.dataset.embeddedProps)).toEqual({
        params: VIDEO.params,
        platform: VIDEO.platform,
        videoId: VIDEO.videoId,
    });
});

test("HTML field adds the paste plugin once to its real editor config", () => {
    const fakeField = Object.create(HtmlField.prototype);
    fakeField.props = {
        codeview: false,
        dynamicPlaceholder: false,
        editorConfig: {},
        embeddedComponents: false,
        isCollaborative: false,
        migrateHTML: false,
        name: "body",
        record: {
            data: { body: "<p>测试</p>" },
            fields: { body: { sanitize: false, sanitize_tags: false } },
        },
    };
    const config = fakeField.getConfig();
    expect(
        config.Plugins.filter((PluginClass) => PluginClass.id === BilibiliPastePlugin.id)
    ).toHaveLength(1);
});

test("product media explicitly disables Bilibili and does not select it", async () => {
    const videoTab = CustomMediaDialog.defaultProps.extraTabs.find(
        (tab) => tab.Component === VideoSelector
    );
    expect(videoTab.props.occDisableBilibili).toBe(true);
    let rpcCalled = false;
    onRpc("/html_editor/video_url/data", () => {
        rpcCalled = true;
    });
    const selected = [];
    const errors = [];
    const selector = await mountWithCleanup(VideoSelector, {
        props: {
            errorMessages: (message) => errors.push(message),
            occDisableBilibili: true,
            selectMedia: (media) => selected.push(media),
        },
    });
    selector.state.urlInput = "https://www.bilibili.com/video/BV1xx411c7mD";
    await selector.updateVideo();
    expect(rpcCalled).toBe(false);
    expect(selected.at(-1)).toEqual({});
    expect(errors.at(-1)).toMatch(/not supported in product media/i);
});

test("media selector sends a supported URL through the strict Bilibili RPC path", async () => {
    const selected = [];
    const errors = [];
    const input = "https://www.bilibili.com/video/BV1xx411c7mD?p=2";
    onRpc("/html_editor/video_url/data", async (request) => {
        const { params } = await request.json();
        expect(params).toEqual({ video_url: input });
        return {
            platform: VIDEO.platform,
            embed_url: VIDEO.src,
            video_id: VIDEO.videoId,
            params: VIDEO.params,
        };
    });
    const selector = await mountWithCleanup(VideoSelector, {
        props: {
            selectMedia: (media) => selected.push(media),
            errorMessages: (message) => errors.push(message),
        },
    });
    selector.state.urlInput = input;
    await selector.updateVideo();
    expect(selector.shownOptions).toEqual([]);
    expect(selected.at(-1)).toEqual({
        id: VIDEO.src,
        ...VIDEO,
    });
    expect(errors.at(-1)).toBe("");
});

test("media selector extracts an official iframe without sending stale options", async () => {
    const iframe =
        '<iframe src="https://player.bilibili.com/player.html?aid=170001&amp;bvid=BV1xx411c7mD&amp;cid=123&amp;p=2" frameborder="0" allowfullscreen></iframe>';
    onRpc("/html_editor/video_url/data", async (request) => {
        const { params } = await request.json();
        expect(params).toEqual({ video_url: iframe });
        return {
            platform: VIDEO.platform,
            embed_url: VIDEO.src,
            video_id: VIDEO.videoId,
            params: VIDEO.params,
        };
    });
    const selector = await mountWithCleanup(VideoSelector, {
        props: { selectMedia: () => {}, errorMessages: () => {} },
    });
    selector.state.urlInput = iframe;
    await selector.updateVideo();
    await animationFrame();
    expect(selector.state.src).toBe(VIDEO.src);
});

test("invalid claimed Bilibili input is rejected and never falls through", async () => {
    let rpcCalled = false;
    onRpc("/html_editor/video_url/data", () => {
        rpcCalled = true;
    });
    const selected = [];
    const selector = await mountWithCleanup(VideoSelector, {
        props: {
            selectMedia: (media) => selected.push(media),
            errorMessages: () => {},
        },
    });
    selector.state.urlInput = "https://b23.tv/not-supported";
    await selector.updateVideo();
    expect(rpcCalled).toBe(false);
    expect(selected.at(-1)).toEqual({});
    expect(selector.state.src).toBe("");
});

test("replacing embedded videos synchronizes the Bilibili cookie marker both ways", () => {
    const host = document.createElement("div");
    const component = Object.create(EmbeddedVideoComponent.prototype);
    component.videoBlock = host;
    component.state = { platform: "youtube", videoId: "old", params: {} };
    component.props = { focusEditable: () => {} };
    component.replaceVideo({
        platform: VIDEO.platform,
        videoId: VIDEO.videoId,
        params: VIDEO.params,
    });
    expect(host.classList.contains("occ_bilibili_embedded_video")).toBe(true);
    component.replaceVideo({ platform: "youtube", videoId: "new", params: {} });
    expect(host.classList.contains("occ_bilibili_embedded_video")).toBe(false);
});
