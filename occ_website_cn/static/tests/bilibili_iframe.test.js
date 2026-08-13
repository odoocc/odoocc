/** @odoo-module **/

import { describe, expect, getFixture, test } from "@odoo/hoot";
import { ReadonlyEmbeddedVideoComponent } from "@html_editor/others/embedded_components/core/video/readonly_video";
import { mountWithCleanup, onRpc } from "@web/../tests/web_test_helpers";
import { generateBilibiliIframe } from "@occ_website_cn/bilibili/generate_video_iframe";
import {
    optionalCookiesNeedApproval,
    prepareIframeForOptionalConsent,
} from "@occ_website_cn/bilibili/public_embedded_video_patch";


describe.current.tags("headless", "occ_website_cn");

function makeContainer(src, cookieApproval = false) {
    const wrapper = document.createElement("div");
    if (cookieApproval) {
        wrapper.dataset.needCookiesApproval = "true";
    }
    const container = document.createElement("div");
    container.className = "media_iframe_video";
    container.dataset.oeExpression = src;
    wrapper.append(container);
    return container;
}

test("rebuilds a canonical Bilibili iframe", () => {
    const src =
        "https://player.bilibili.com/player.html?bvid=BV1xx411c7mD&page=1&autoplay=0";
    const container = makeContainer(src);
    const iframe = generateBilibiliIframe(container);
    expect(iframe.src).toBe(src);
    expect(iframe.getAttribute("referrerpolicy")).toBe("strict-origin-when-cross-origin");
});

test("keeps Bilibili network-free before optional cookie consent", () => {
    const src =
        "https://player.bilibili.com/player.html?bvid=BV1xx411c7mD&page=1&autoplay=0";
    const container = makeContainer(src, true);
    const iframe = generateBilibiliIframe(container);
    expect(iframe.getAttribute("src")).toBe("about:blank");
    expect(iframe.dataset.nocookieSrc).toBe(src);
    expect(iframe.dataset.needCookiesApproval).toBe("true");
});

test("continues rejecting lookalike hosts and unsupported protocols", () => {
    for (const src of [
        "https://player.bilibili.com.evil.example/player.html?aid=1",
        "javascript://player.bilibili.com/player.html?aid=1",
    ]) {
        const container = makeContainer(src);
        expect(generateBilibiliIframe(container)).toBe(undefined);
        expect(container.querySelector("iframe")).toBe(null);
    }
});

test("stored HTML embeds honor Odoo's QWeb approval marker", () => {
    getFixture().innerHTML =
        '<div data-need-cookies-approval="true">' +
        '<div class="occ_bilibili_embedded_video"></div></div>';
    const host = document.querySelector(".occ_bilibili_embedded_video");
    const iframe = document.createElement("iframe");
    expect(optionalCookiesNeedApproval(host)).toBe(true);
    prepareIframeForOptionalConsent(
        iframe,
        host,
        "https://player.bilibili.com/player.html?aid=170001&page=1&autoplay=0"
    );
    expect(iframe.getAttribute("src")).toBe("about:blank");
    expect(iframe.dataset.nocookieSrc).toBe(
        "https://player.bilibili.com/player.html?aid=170001&page=1&autoplay=0"
    );
    expect(iframe.dataset.needCookiesApproval).toBe("true");
});

test("stored HTML embeds load when Odoo did not mark them for approval", () => {
    getFixture().innerHTML =
        '<div id="website_cookies_bar"><button id="cookies-consent-essential"></button></div>' +
        '<div class="occ_bilibili_embedded_video"></div>';
    const host = document.querySelector(".occ_bilibili_embedded_video");
    expect(optionalCookiesNeedApproval(host)).toBe(false);
});

test("mounted readonly embeds do not expose Bilibili src before approval", async () => {
    // The global test environment includes mail services. This component does
    // not use messaging, so isolate it from mail's mock model bootstrap.
    onRpc("/mail/data", () => ({}));
    const host = document.createElement("div");
    host.dataset.needCookiesApproval = "true";
    getFixture().append(host);
    const playerUrl =
        "https://player.bilibili.com/player.html?bvid=BV1xx411c7mD&page=1&autoplay=0";
    let managedIframe;
    await mountWithCleanup(ReadonlyEmbeddedVideoComponent, {
        target: host,
        componentEnv: {
            services: {
                website_cookies: {
                    manageIframeSrc(iframe, src) {
                        managedIframe = iframe;
                        iframe.dataset.nocookieSrc = src;
                        iframe.src = "about:blank";
                    },
                },
            },
        },
        props: {
            host,
            platform: "bilibili",
            videoId: "BV1xx411c7mD",
            params: { page: 1, autoplay: 0 },
        },
    });
    const iframe = host.querySelector("iframe");
    expect(iframe).toBe(managedIframe);
    expect(iframe.getAttribute("src")).toBe("about:blank");
    expect(iframe.dataset.nocookieSrc).toBe(playerUrl);
    expect(iframe.dataset.needCookiesApproval).toBe("true");
});
