/** @odoo-module **/

import { describe, expect, test } from "@odoo/hoot";
import {
    getBilibiliVideoUrl,
    isBilibiliVideoInput,
    parseBilibiliVideo,
} from "@occ_base_bilibili/bilibili_parser";

describe.current.tags("headless", "occ_base_bilibili");

test("规范化合法的B站视频地址", () => {
    const result = parseBilibiliVideo(
        "https://www.bilibili.com/video/BV1xx411c7mD?p=2"
    );
    expect(result).toEqual({
        embedUrl:
            "https://player.bilibili.com/player.html?bvid=BV1xx411c7mD&page=2&autoplay=0",
        params: { page: 2, autoplay: 0 },
        platform: "bilibili",
        videoId: "BV1xx411c7mD",
    });
});

test("单独BV号必须显式允许", () => {
    expect(parseBilibiliVideo("BV1xx411c7mD")).toBe(null);
    expect(
        parseBilibiliVideo("BV1xx411c7mD", { allowBareBvid: true }).videoId
    ).toBe("BV1xx411c7mD");
});

test("拒绝危险输入且不误认其他平台", () => {
    for (const value of [
        "https://b23.tv/abc123",
        "https://player.bilibili.com.evil.example/player.html?aid=1",
        "javascript://player.bilibili.com/player.html?aid=1",
    ]) {
        expect(parseBilibiliVideo(value)).toBe(null);
        expect(isBilibiliVideoInput(value)).toBe(true);
    }
    expect(
        isBilibiliVideoInput("https://youtube.com/watch?v=x&utm_source=bilibili")
    ).toBe(false);
});

test("只允许固定的播放器参数", () => {
    expect(() =>
        getBilibiliVideoUrl("BV1xx411c7mD", { page: 1, autoplay: 1 })
    ).toThrow();
});
