/** @odoo-module **/

import { describe, expect, test } from "@odoo/hoot";

import {
    getBilibiliVideoUrl,
    isBilibiliVideoInput,
    parseBilibiliVideo,
} from "@occ_website_cn/bilibili/bilibili_parser";


describe.current.tags("headless", "occ_website_cn");

const VALID_INPUTS = [
    ["https://www.bilibili.com/video/BV1xx411c7mD", "BV1xx411c7mD", 1],
    ["https://bilibili.com/video/BV1xx411c7mD?p=2", "BV1xx411c7mD", 2],
    ["https://m.bilibili.com/video/av170001?page=3", "170001", 3],
    ["av170001", "170001", 1],
    [
        "//player.bilibili.com/player.html?bvid=BV1xx411c7mD&page=4",
        "BV1xx411c7mD",
        4,
    ],
    ["https://player.bilibili.com/player.html?aid=170001&p=5", "170001", 5],
    [
        '<iframe src="https://player.bilibili.com/player.html?bvid=BV1xx411c7mD&amp;cid=123&amp;page=6&amp;isOutside=true" frameborder="0" allowfullscreen></iframe>',
        "BV1xx411c7mD",
        6,
    ],
    [
        '<iframe src="https://player.bilibili.com/player.html?aid=170001&amp;bvid=BV1xx411c7mD&amp;cid=123&amp;p=7&amp;isOutside=true" frameborder="0" allowfullscreen></iframe>',
        "BV1xx411c7mD",
        7,
    ],
];

const INVALID_INPUTS = [
    "https://b23.tv/abc123",
    "https://live.bilibili.com/123",
    "https://www.bilibili.com/bangumi/play/ep123",
    "https://www.bilibili.com/cheese/play/ep123",
    "https://player.bilibili.com/player.html?cid=123",
    "https://player.bilibili.com/player.html?bvid=BV1xx411c7mD&autoplay=1",
    "https://player.bilibili.com/player.html?bvid=BV1xx411c7mD&danmaku=0",
    "https://player.bilibili.com/player.html?bvid=BV1xx411c7mD&page=0",
    "https://player.bilibili.com/player.html?bvid=BV1xx411c7mD&page=10001",
    "https://player.bilibili.com/player.html?bvid=BV1xx411c7mD&page=1&p=2",
    "https://player.bilibili.com.evil.example/player.html?bvid=BV1xx411c7mD",
    "https://user@player.bilibili.com/player.html?bvid=BV1xx411c7mD",
    "https://player.bilibili.com:443/player.html?bvid=BV1xx411c7mD",
    "javascript://player.bilibili.com/player.html?bvid=BV1xx411c7mD",
    "https://player.bilibili.com/player.html?bvid=BV1xx411c7mD&",
    "https://www.bilibili.com/video/BV1xx411c7mD?share_source=copy_web",
    '<iframe src="https://player.bilibili.com/player.html?aid=170001" onload="alert(1)"></iframe>',
];

test("accepts and canonicalizes the strict Bilibili contract", () => {
    for (const [input, videoId, page] of VALID_INPUTS) {
        const result = parseBilibiliVideo(input);
        expect(result).toEqual({
            embedUrl: getBilibiliVideoUrl(videoId, { page, autoplay: 0 }).href,
            params: { page, autoplay: 0 },
            platform: "bilibili",
            videoId,
        });
    }
});

test("rejects short links, non-video products, unsafe hosts, and arbitrary options", () => {
    for (const input of INVALID_INPUTS) {
        expect(parseBilibiliVideo(input)).toBe(null);
        expect(isBilibiliVideoInput(input)).toBe(true);
    }
});

test("canonical URL contains only identity, page and disabled autoplay", () => {
    const result = parseBilibiliVideo(
        "https://player.bilibili.com/player.html?bvid=BV1xx411c7mD&cid=123&isOutside=true&p=9"
    );
    expect(result.embedUrl).toBe(
        "https://player.bilibili.com/player.html?bvid=BV1xx411c7mD&page=9&autoplay=0"
    );
    expect(result.embedUrl).not.toInclude("cid");
    expect(result.embedUrl).not.toInclude("isOutside");
});

test("refuses unsupported reconstructed player options", () => {
    expect(() =>
        getBilibiliVideoUrl("BV1xx411c7mD", { page: 1, autoplay: 1 })
    ).toThrow();
    expect(() => getBilibiliVideoUrl("BV1xx411c7mD", { page: 1, loop: true })).toThrow();
    expect(() => getBilibiliVideoUrl("not-an-id", { page: 1 })).toThrow();
});

test("does not claim an iframe belonging to an upstream provider", () => {
    const vimeoIframe = '<iframe src="https://player.vimeo.com/video/123"></iframe>';
    expect(isBilibiliVideoInput(vimeoIframe)).toBe(false);
    expect(parseBilibiliVideo(vimeoIframe)).toBe(null);
});

test("keeps strict iframe validation aligned with the server", () => {
    const inputs = [
        '<iframe src="https://player.bilibili.com/player.html?aid=170001">',
        '<iframe src="https://player.bilibili.com/player.html?aid=170001" src="https://example.test"></iframe>',
    ];
    for (const input of inputs) {
        expect(isBilibiliVideoInput(input)).toBe(true);
        expect(parseBilibiliVideo(input)).toBe(null);
    }
});

test("does not claim upstream URLs that only mention Bilibili outside the authority", () => {
    const inputs = [
        "https://vimeo.com/123456789?utm_source=bilibili",
        "https://www.youtube.com/watch?v=xCvFZrrQq7k&utm_campaign=bilibili",
        "https://vimeo.com/channels/bilibili/123456789",
    ];
    for (const input of inputs) {
        expect(isBilibiliVideoInput(input)).toBe(false);
        expect(parseBilibiliVideo(input)).toBe(null);
    }
});

test("rejects a bare BV id without claiming an upstream provider", () => {
    expect(parseBilibiliVideo("BV1xx411c7mD")).toBe(null);
    expect(isBilibiliVideoInput("BV1xx411c7mD")).toBe(false);
});

test("keeps large av identifiers exact across the Python and JavaScript contracts", () => {
    const aid = "900719925474099312345";
    const result = parseBilibiliVideo(`av${aid}`);
    expect(result.videoId).toBe(aid);
    expect(result.embedUrl).toBe(
        `https://player.bilibili.com/player.html?aid=${aid}&page=1&autoplay=0`
    );
});
