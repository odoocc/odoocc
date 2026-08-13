import { startInteractions, setupInteractionWhiteList } from "@web/../tests/public/helpers";

import { describe, expect, test } from "@odoo/hoot";
import { click, press, tick } from "@odoo/hoot-dom";
import { mockService, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";

setupInteractionWhiteList("occ_website_cn.share_cn");
describe.current.tags("headless", "occ_website_cn");

const actionButtons = `
    <button class="s_share_cn_action s_share_cn_wechat" data-platform="wechat">微信</button>
    <button class="s_share_cn_action s_share_cn_qq" data-platform="qq">QQ好友</button>
    <button class="s_share_cn_action s_share_cn_qzone" data-platform="qzone">QQ空间</button>
    <button class="s_share_cn_action s_share_cn_weibo" data-platform="weibo">微博</button>
    <button class="s_share_cn_action s_share_cn_copy" data-platform="copy">复制链接</button>`;

function shareSnippet(extraClass = "") {
    return `
        <div class="s_share_cn ${extraClass}">
            ${actionButtons}
            <div class="s_share_cn_dialog" hidden role="dialog" aria-modal="true" tabindex="-1">
                <span class="s_share_cn_dialog_title"></span>
                <button class="s_share_cn_dialog_header_close s_share_cn_dialog_close">页眉关闭</button>
                <div class="s_share_cn_dialog_body"></div>
                <button class="s_share_cn_dialog_confirm" hidden>继续分享</button>
                <button class="s_share_cn_dialog_cancel s_share_cn_dialog_close">关闭</button>
            </div>
        </div>`;
}

function patchLocation(href) {
    patchWithCleanup(browser.location, { href });
}

function patchNavigator(userAgent, clipboard = browser.navigator.clipboard) {
    patchWithCleanup(browser, {
        navigator: { ...browser.navigator, clipboard, userAgent },
    });
}

function mockNotifications() {
    const messages = [];
    mockService("notification", {
        add(message) {
            messages.push(message);
        },
    });
    return messages;
}

test("敏感参数先确认；取消不分享，继续时保留查询参数并移除 fragment", async () => {
    let openedUrl;
    const popup = {};
    patchWithCleanup(browser, {
        open(url) {
            openedUrl = url;
            return popup;
        },
    });
    patchLocation("https://example.test/page?token=do-not-display&keep=yes#fragment");
    await startInteractions(shareSnippet());

    await click(".s_share_cn_qq");
    expect(openedUrl).toBe(undefined);
    expect(".s_share_cn_sensitive_warning").toHaveText(/token/);
    expect(".s_share_cn_sensitive_warning").not.toHaveText(/do-not-display/);
    expect(".s_share_cn_dialog_cancel").toBeFocused();

    await click(".s_share_cn_dialog_cancel");
    expect(openedUrl).toBe(undefined);
    expect(".s_share_cn_qq").toBeFocused();

    await click(".s_share_cn_qq");
    await click(".s_share_cn_dialog_confirm");
    expect(".s_share_cn_qq").toBeFocused();
    const endpoint = new URL(openedUrl);
    expect(endpoint.origin + endpoint.pathname).toBe(
        "https://connect.qq.com/widget/shareqq/index.html"
    );
    expect(endpoint.searchParams.get("url")).toBe(
        "https://example.test/page?token=do-not-display&keep=yes"
    );
    expect(popup.opener).toBe(null);
});

test("QQ空间和微博使用各自端点并正确传递中文标题", async () => {
    const openedUrls = [];
    patchWithCleanup(browser, {
        open(url) {
            openedUrls.push(url);
            return {};
        },
    });
    patchLocation("https://example.test/文章?from=首页#评论");
    const originalTitle = document.title;
    document.title = "中文 标题";
    try {
        await startInteractions(shareSnippet());
        await click(".s_share_cn_qzone");
        await click(".s_share_cn_weibo");
    } finally {
        document.title = originalTitle;
    }
    const [qzoneUrl, weiboUrl] = openedUrls.map((url) => new URL(url));
    expect(qzoneUrl.origin + qzoneUrl.pathname).toBe(
        "https://sns.qzone.qq.com/cgi-bin/qzshare/cgi_qzshare_onekey"
    );
    expect(weiboUrl.origin + weiboUrl.pathname).toBe(
        "https://service.weibo.com/share/share.php"
    );
    expect(qzoneUrl.searchParams.get("title")).toBe("中文 标题");
    expect(weiboUrl.searchParams.get("url")).toBe("https://example.test/文章?from=首页");
});

test("弹窗被拦截时显示中文警告", async () => {
    const notifications = mockNotifications();
    patchWithCleanup(browser, { open: () => null });
    patchLocation("https://example.test/page");
    await startInteractions(shareSnippet());
    await click(".s_share_cn_qq");
    expect(notifications).toEqual(["分享窗口被浏览器拦截，请允许本站弹出窗口后重试。"]);
});

test("复制成功使用去 fragment 的完整 URL", async () => {
    let copiedUrl;
    const notifications = mockNotifications();
    patchNavigator("Mozilla/5.0 (X11; Linux x86_64)", {
        async writeText(value) {
            copiedUrl = value;
        },
    });
    patchLocation("https://example.test/page?keep=yes#fragment");
    await startInteractions(shareSnippet());
    await click(".s_share_cn_copy");
    expect(copiedUrl).toBe("https://example.test/page?keep=yes");
    expect(notifications).toEqual(["页面链接已复制。"]);
});

test("剪贴板失败时显示手动复制框，Escape 关闭并恢复焦点", async () => {
    patchNavigator("Mozilla/5.0 (X11; Linux x86_64)", {
        writeText: () => Promise.reject(new Error("denied")),
    });
    patchLocation("https://example.test/page?keep=yes#fragment");
    await startInteractions(shareSnippet());
    await click(".s_share_cn_copy");
    await tick();
    expect(".s_share_cn_copy_fallback").toHaveValue("https://example.test/page?keep=yes");
    expect(".s_share_cn_copy_fallback").toBeFocused();
    await press("Escape");
    expect(".s_share_cn_dialog").toHaveAttribute("hidden");
    expect(".s_share_cn_copy").toBeFocused();
});

test("微信内只提示右上角分享，不打开窗口也不复制", async () => {
    let copyCalls = 0;
    let openCalls = 0;
    patchNavigator("Mozilla/5.0 (Linux; Android 15) MicroMessenger/8.0.50", {
        async writeText() {
            copyCalls++;
        },
    });
    patchWithCleanup(browser, {
        open() {
            openCalls++;
        },
    });
    patchLocation("https://example.test/page");
    await startInteractions(shareSnippet());
    await click(".s_share_cn_wechat");
    expect(".s_share_cn_wechat_message").toHaveText(/右上角/);
    expect(copyCalls).toBe(0);
    expect(openCalls).toBe(0);
});

test("普通手机浏览器复制链接并提示切换微信", async () => {
    let copiedUrl;
    const notifications = mockNotifications();
    patchNavigator("Mozilla/5.0 (Linux; Android 15) Chrome/140 Mobile", {
        async writeText(value) {
            copiedUrl = value;
        },
    });
    patchLocation("https://example.test/page#fragment");
    await startInteractions(shareSnippet());
    await click(".s_share_cn_wechat");
    expect(copiedUrl).toBe("https://example.test/page");
    expect(notifications).toEqual(["链接已复制，请切换到微信后粘贴分享。"]);
});

test("桌面微信入口使用本地库生成 SVG，不打开窗口、不创建外部资源", async () => {
    let openCalls = 0;
    patchNavigator("Mozilla/5.0 (X11; Linux x86_64)");
    patchWithCleanup(browser, {
        open() {
            openCalls++;
        },
    });
    patchLocation("https://example.test/page?name=中文");
    await startInteractions(shareSnippet());
    await click(".s_share_cn_wechat");
    expect(".s_share_cn_qr svg").toHaveCount(1);
    expect(".s_share_cn_qr svg").toHaveAttribute("role", "img");
    expect(".s_share_cn_qr svg").toHaveAttribute("aria-label", "当前页面链接二维码");
    expect(".s_share_cn_qr [id]").toHaveCount(0);
    expect(".s_share_cn_dialog_body img").toHaveCount(0);
    expect(".s_share_cn_dialog_body script").toHaveCount(0);
    expect(openCalls).toBe(0);
});

test("对话框将 Tab 焦点限制在内部，并在关闭后恢复到触发按钮", async () => {
    patchNavigator("Mozilla/5.0 (X11; Linux x86_64)");
    patchLocation("https://example.test/page");
    await startInteractions(shareSnippet());
    await click(".s_share_cn_wechat");
    expect(".s_share_cn_dialog_header_close").toBeFocused();
    await press("Tab");
    expect(".s_share_cn_dialog_cancel").toBeFocused();
    await press("Tab");
    expect(".s_share_cn_dialog_header_close").toBeFocused();
    await press("Tab", { shiftKey: true });
    expect(".s_share_cn_dialog_cancel").toBeFocused();
    await press("Escape");
    expect(".s_share_cn_wechat").toBeFocused();
});

test("同页多个分享区块的对话框状态、内容和焦点相互隔离", async () => {
    patchNavigator("Mozilla/5.0 (Linux; Android 15) MicroMessenger/8.0.50");
    patchLocation("https://example.test/page");
    await startInteractions(`${shareSnippet("first")}${shareSnippet("second")}`);
    await click(".second .s_share_cn_wechat");
    expect(".first .s_share_cn_dialog").toHaveAttribute("hidden");
    expect(".first .s_share_cn_dialog_body").toHaveText("");
    expect(".second .s_share_cn_dialog").not.toHaveAttribute("hidden");
    expect(".second .s_share_cn_wechat_message").toHaveCount(1);
    await press("Escape");
    expect(".second .s_share_cn_wechat").toBeFocused();
});
