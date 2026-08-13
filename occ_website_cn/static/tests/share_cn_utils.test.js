import { describe, expect, test } from "@odoo/hoot";

import {
    buildShareEndpoint,
    getSensitiveParameterNames,
    getShareUrl,
    isMobileBrowser,
    isWechatBrowser,
} from "@occ_website_cn/share/share_utils";

describe.current.tags("headless", "occ_website_cn");

test("分享链接保留原始完整 URL，只移除 fragment", () => {
    expect(getShareUrl("https://example.test/path?a=1&name=%E8%B5%B5#section")).toBe(
        "https://example.test/path?a=1&name=%E8%B5%B5"
    );
    expect(getShareUrl("https://example.test/path?empty=&flag")).toBe(
        "https://example.test/path?empty=&flag"
    );
});

test("敏感参数检测不区分大小写，支持常见组合名且不暴露参数值", () => {
    expect(
        getSensitiveParameterNames(
            "https://example.test/?Token=do-not-log&keyboard=ok&access_token=hidden" +
                "&authCode=hidden-too&signature=also-secret"
        )
    ).toEqual(["Token", "access_token", "authCode", "signature"]);
});

test("QQ好友、QQ空间和微博端点只编码 URL 与标题一次", () => {
    const pageUrl = "https://example.test/文章?a=1&b=中文";
    const title = "中文 标题";
    const expectations = {
        qq: "https://connect.qq.com/widget/shareqq/index.html",
        qzone: "https://sns.qzone.qq.com/cgi-bin/qzshare/cgi_qzshare_onekey",
        weibo: "https://service.weibo.com/share/share.php",
    };
    for (const [platform, originAndPath] of Object.entries(expectations)) {
        const endpoint = new URL(buildShareEndpoint(platform, pageUrl, title));
        expect(`${endpoint.origin}${endpoint.pathname}`).toBe(originAndPath);
        expect(endpoint.searchParams.get("url")).toBe(pageUrl);
        expect(endpoint.searchParams.get("title")).toBe(title);
    }
});

test("拒绝未声明的分享平台", () => {
    expect(() => buildShareEndpoint("unknown", "https://example.test", "标题")).toThrow(
        /Unsupported domestic share platform/
    );
});

test("浏览器识别区分微信、普通移动端和桌面端", () => {
    expect(isWechatBrowser("Mozilla/5.0 MicroMessenger/8.0.0")).toBe(true);
    expect(isMobileBrowser("Mozilla/5.0 (Linux; Android 15) MicroMessenger/8.0.0")).toBe(true);
    expect(isMobileBrowser("Mozilla/5.0 (Linux; Android 15)")).toBe(true);
    expect(isWechatBrowser("Mozilla/5.0 (Linux; Android 15)")).toBe(false);
    expect(isMobileBrowser("Mozilla/5.0 (X11; Linux x86_64)")).toBe(false);
});
