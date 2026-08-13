/** @odoo-module **/

export const BILIBILI_PLAYER_HOST = "player.bilibili.com";
export const BILIBILI_PLATFORM = "bilibili";

const VIDEO_HOSTS = new Set(["bilibili.com", "www.bilibili.com", "m.bilibili.com"]);
const PLAYER_QUERY_KEYS = new Set([
    "aid",
    "autoplay",
    "bvid",
    "cid",
    "isoutside",
    "p",
    "page",
]);
const VIDEO_QUERY_KEYS = new Set(["p", "page"]);
const ALLOWED_IFRAME_ATTRIBUTES = new Set([
    "allowfullscreen",
    "border",
    "frameborder",
    "framespacing",
    "height",
    "scrolling",
    "src",
    "width",
]);
const BVID_RE = /^BV[A-Za-z0-9]{10}$/;
const AID_RE = /^[1-9][0-9]*$/;
const MAX_INPUT_LENGTH = 4096;
const MAX_PAGE = 10000;

function extractExplicitPort(candidate) {
    const authorityMatch = /^(?:https?:)?\/\/([^/?#]+)/i.exec(candidate);
    if (!authorityMatch) {
        return null;
    }
    const authority = authorityMatch[1].split("@").at(-1);
    if (authority.startsWith("[")) {
        const closingBracket = authority.indexOf("]");
        return closingBracket >= 0 && authority[closingBracket + 1] === ":"
            ? authority.slice(closingBracket + 2)
            : null;
    }
    const separator = authority.lastIndexOf(":");
    return separator >= 0 ? authority.slice(separator + 1) : null;
}

function extractIframeSrc(value) {
    if (!value.trimStart().toLowerCase().startsWith("<iframe")) {
        return undefined;
    }
    if (!/<\/iframe\s*>\s*$/i.test(value)) {
        return null;
    }
    const rawStartTag = /^\s*<iframe\b([^>]*)>/i.exec(value);
    const rawSrcAttributes = rawStartTag?.[1].match(/(?:^|\s)src\s*=/gi) || [];
    if (rawSrcAttributes.length !== 1) {
        return null;
    }
    const document = new DOMParser().parseFromString(value, "text/html");
    if (document.body.childNodes.length !== 1 || document.body.children.length !== 1) {
        return null;
    }
    const iframe = document.body.firstElementChild;
    if (iframe.tagName !== "IFRAME" || iframe.children.length || iframe.textContent.trim()) {
        return null;
    }
    const attributeNames = iframe.getAttributeNames().map((name) => name.toLowerCase());
    if (
        attributeNames.length !== new Set(attributeNames).size ||
        attributeNames.some((name) => !ALLOWED_IFRAME_ATTRIBUTES.has(name))
    ) {
        return null;
    }
    return iframe.getAttribute("src")?.trim() || null;
}

function parseStrictQuery(searchParams, allowedKeys) {
    const values = {};
    for (const [rawKey, value] of searchParams) {
        const key = rawKey.toLowerCase();
        if (!allowedKeys.has(key) || Object.hasOwn(values, key)) {
            return null;
        }
        values[key] = value;
    }
    return values;
}

function parsePage(values) {
    if (values.page !== undefined && values.p !== undefined && values.page !== values.p) {
        return null;
    }
    const value = values.page ?? values.p ?? "1";
    if (!AID_RE.test(value)) {
        return null;
    }
    const page = Number(value);
    return Number.isSafeInteger(page) && page <= MAX_PAGE ? page : null;
}

function normalizedResult(videoId, page) {
    const idParameter = BVID_RE.test(videoId) ? "bvid" : "aid";
    const url = new URL(`https://${BILIBILI_PLAYER_HOST}/player.html`);
    url.search = new URLSearchParams({ [idParameter]: videoId, page, autoplay: 0 });
    return {
        embedUrl: url.href,
        params: { page, autoplay: 0 },
        platform: BILIBILI_PLATFORM,
        videoId,
    };
}

function parseVideoPage(url) {
    if (!VIDEO_HOSTS.has(url.hostname.toLowerCase())) {
        return null;
    }
    const pathMatch = /^\/video\/([^/]+)\/?$/.exec(url.pathname);
    if (!pathMatch) {
        return null;
    }
    const idMatch = /^(BV[A-Za-z0-9]{10})$|^av([1-9][0-9]*)$/i.exec(pathMatch[1]);
    if (!idMatch || (idMatch[1] && !BVID_RE.test(idMatch[1]))) {
        return null;
    }
    const values = parseStrictQuery(url.searchParams, VIDEO_QUERY_KEYS);
    const page = values && parsePage(values);
    if (!page) {
        return null;
    }
    return normalizedResult(idMatch[1] || idMatch[2], page);
}

function parsePlayer(url) {
    if (url.hostname.toLowerCase() !== BILIBILI_PLAYER_HOST || url.pathname !== "/player.html") {
        return null;
    }
    const values = parseStrictQuery(url.searchParams, PLAYER_QUERY_KEYS);
    const page = values && parsePage(values);
    if (
        !page ||
        (values.bvid !== undefined && !BVID_RE.test(values.bvid)) ||
        (values.aid !== undefined && !AID_RE.test(values.aid)) ||
        (values.cid !== undefined && !AID_RE.test(values.cid)) ||
        (values.autoplay !== undefined && values.autoplay !== "0") ||
        (values.isoutside !== undefined &&
            !["0", "1", "false", "true"].includes(values.isoutside.toLowerCase())) ||
        (!values.bvid && !values.aid)
    ) {
        return null;
    }
    return normalizedResult(values.bvid || values.aid, page);
}

export function parseBilibiliVideo(value) {
    if (typeof value !== "string") {
        return null;
    }
    let candidate = value.trim();
    if (
        !candidate ||
        candidate.length > MAX_INPUT_LENGTH ||
        [...candidate].some((character) => character.charCodeAt(0) < 32)
    ) {
        return null;
    }
    const iframeSrc = extractIframeSrc(candidate);
    if (iframeSrc === null) {
        return null;
    }
    if (iframeSrc !== undefined) {
        candidate = iframeSrc;
    }
    const explicitPort = extractExplicitPort(candidate);
    const bareAidMatch = /^av([1-9][0-9]*)$/i.exec(candidate);
    if (bareAidMatch) {
        return normalizedResult(bareAidMatch[1], 1);
    }
    if (candidate.startsWith("//")) {
        candidate = `https:${candidate}`;
    }
    let url;
    try {
        url = new URL(candidate);
    } catch {
        return null;
    }
    if (
        !["http:", "https:"].includes(url.protocol.toLowerCase()) ||
        url.username ||
        url.password ||
        explicitPort !== null ||
        url.port ||
        url.hash ||
        /(?:^|&)&|&$/.test(url.search.slice(1))
    ) {
        return null;
    }
    return parseVideoPage(url) || parsePlayer(url);
}

export function isBilibiliVideoInput(value) {
    if (typeof value !== "string") {
        return false;
    }
    let candidate = value.trim();
    if (/^av[1-9][0-9]*$/i.test(candidate)) {
        return true;
    }
    if (candidate.trimStart().toLowerCase().startsWith("<iframe")) {
        const document = new DOMParser().parseFromString(candidate, "text/html");
        const iframe = document.body.querySelector("iframe");
        candidate = iframe?.getAttribute("src")?.trim();
        if (!candidate) {
            return false;
        }
    }
    if (candidate.startsWith("//")) {
        candidate = `https:${candidate}`;
    } else if (!candidate.includes("://")) {
        // Recognize a scheme-less Bilibili authority as a claimed but invalid
        // URL without scanning arbitrary paths and query values for keywords.
        candidate = `https://${candidate}`;
    }
    let hostname;
    try {
        hostname = new URL(candidate).hostname.toLowerCase().replace(/\.$/, "");
    } catch {
        return false;
    }
    const wrappedHostname = `.${hostname}.`;
    return ["bilibili.com", "b23.tv"].some((domain) =>
        wrappedHostname.includes(`.${domain}.`)
    );
}

export function getBilibiliVideoUrl(videoId, params = {}) {
    const page = params.page ?? 1;
    const unsupportedOptions = Object.keys(params).some(
        (key) => !["page", "autoplay"].includes(key)
    );
    if (
        unsupportedOptions ||
        (!BVID_RE.test(videoId) && !AID_RE.test(videoId)) ||
        !Number.isInteger(page) ||
        page < 1 ||
        page > MAX_PAGE
    ) {
        throw new Error("Invalid Bilibili video data");
    }
    const result = normalizedResult(videoId, page);
    if (!result || (params.autoplay ?? 0) !== 0) {
        throw new Error("Unsupported Bilibili player options");
    }
    return new URL(result.embedUrl);
}
