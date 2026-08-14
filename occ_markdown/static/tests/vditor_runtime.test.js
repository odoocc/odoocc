/** @odoo-module **/

import { describe, expect, getFixture, test } from "@odoo/hoot";

describe.current.tags("desktop", "occ_markdown");

test("本地Vditor运行资源可完成所见即所得初始化", async () => {
    const host = document.createElement("div");
    getFixture().append(host);
    let ready;
    const readyPromise = new Promise((resolve) => (ready = resolve));
    const editor = new window.Vditor(host, {
        cdn: "/occ_markdown/static/lib/vditor",
        lang: "zh_CN",
        icon: "material",
        mode: "wysiwyg",
        value: "# 本地资源",
        cache: { enable: false },
        toolbar: [],
        preview: { hljs: { enable: false } },
        after: ready,
    });
    await readyPromise;
    expect(editor.getCurrentMode()).toBe("wysiwyg");
    expect(editor.getValue()).toInclude("本地资源");
    expect(host.querySelector(".vditor-wysiwyg")).not.toBe(null);
    editor.destroy();
});
