const SENSITIVE_PARAMETER_NAMES = new Set([
    "token",
    "secret",
    "password",
    "session",
    "auth",
    "signature",
    "code",
    "key",
]);

/**
 * Return the current page URL that is safe to hand to a share endpoint.
 * Query parameters are intentionally preserved; only the client-side fragment
 * is stripped.
 *
 * @param {string} href
 * @returns {string}
 */
export function getShareUrl(href) {
    const fragmentIndex = href.indexOf("#");
    return fragmentIndex === -1 ? href : href.slice(0, fragmentIndex);
}

/**
 * Return suspicious query parameter names without exposing their values.
 * Matching is deliberately case-insensitive and exact to avoid noisy warnings
 * for benign names such as "keyboard".
 *
 * @param {string} href
 * @returns {string[]}
 */
export function getSensitiveParameterNames(href) {
    const names = new Set();
    for (const name of new URL(href).searchParams.keys()) {
        const normalizedName = name
            .replace(/([a-z\d])([A-Z])/g, "$1_$2")
            .toLowerCase()
            .replace(/\[\]$/, "");
        const nameParts = normalizedName.split(/[^a-z\d]+/).filter(Boolean);
        if (
            SENSITIVE_PARAMETER_NAMES.has(normalizedName) ||
            nameParts.some((part) => SENSITIVE_PARAMETER_NAMES.has(part))
        ) {
            names.add(name);
        }
    }
    return [...names];
}

/**
 * Build a domestic share endpoint. URLSearchParams performs exactly one layer
 * of percent-encoding for both the page URL and title.
 *
 * @param {"qq" | "qzone" | "weibo"} platform
 * @param {string} shareUrl
 * @param {string} title
 * @returns {string}
 */
export function buildShareEndpoint(platform, shareUrl, title) {
    const endpoints = {
        qq: "https://connect.qq.com/widget/shareqq/index.html",
        qzone: "https://sns.qzone.qq.com/cgi-bin/qzshare/cgi_qzshare_onekey",
        weibo: "https://service.weibo.com/share/share.php",
    };
    if (!(platform in endpoints)) {
        throw new Error(`Unsupported domestic share platform: ${platform}`);
    }
    const endpoint = new URL(endpoints[platform]);
    endpoint.searchParams.set("url", shareUrl);
    endpoint.searchParams.set("title", title);
    return endpoint.toString();
}

/** @param {string} userAgent */
export function isWechatBrowser(userAgent) {
    return /MicroMessenger/i.test(userAgent);
}

/** @param {string} userAgent */
export function isMobileBrowser(userAgent) {
    return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini|Windows Phone/i.test(
        userAgent
    );
}
