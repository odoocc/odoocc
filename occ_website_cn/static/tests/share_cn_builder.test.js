/** @odoo-module **/

import {
    getDragHelper,
    waitForEndOfOperation,
    waitForSnippetDialog,
} from "@html_builder/../tests/helpers";
import { describe, expect, test } from "@odoo/hoot";
import { contains } from "@web/../tests/web_test_helpers";
import {
    defineWebsiteModels,
    setupWebsiteBuilder,
} from "@website/../tests/builder/website_helpers";

import "@occ_website_cn/share/share_cn_builder_plugin";

defineWebsiteModels();
describe.current.tags("desktop", "occ_website_cn");

const SHARE_CN_SNIPPET = `
    <div name="国内分享" data-oe-snippet-id="456">
        <div class="s_share_cn" data-snippet="s_share_cn">
            <h4 class="s_share_cn_title d-none">分享到国内平台</h4>
            <div class="s_share_cn_actions"></div>
        </div>
    </div>`;

const SHARE_CN_GROUP = `
    <div name="社交" data-oe-snippet-id="123" data-o-snippet-group="social">
        <section data-snippet="s_snippet_group"></section>
    </div>`;

const SHARE_CN_STRUCTURE = `
    <div name="国内分享" data-oe-snippet-id="789" data-o-group="social">
        <section class="s_share_cn_block" data-snippet="s_share_cn_block">
            <div class="container">
                <div class="s_share_cn"></div>
            </div>
        </section>
    </div>`;

test("国内分享内嵌区块可拖入普通 Website 页面", async () => {
    await setupWebsiteBuilder(
        `<section class="s_text_block" data-snippet="s_text_block">
            <div class="container"><p>正文</p></div>
        </section>`,
        {
            snippets: {
                snippet_content: [SHARE_CN_SNIPPET],
            },
        }
    );

    const tileSelector = "#snippet_content [name='国内分享']";
    expect(tileSelector).toHaveClass("o_draggable");
    expect(tileSelector).not.toHaveClass("o_disabled");

    const { moveTo, drop } = await contains(`${tileSelector} .o_snippet_thumbnail`).drag();
    expect(":iframe .oe_drop_zone").not.toHaveCount(0);
    await moveTo(":iframe .oe_drop_zone");
    await drop(getDragHelper());
    await waitForEndOfOperation();

    expect(":iframe .s_text_block .s_share_cn").toHaveCount(1);
});

test("国内分享完整区块可从社交分类拖入空白 Website 页面", async () => {
    await setupWebsiteBuilder("", {
        snippets: {
            snippet_groups: [SHARE_CN_GROUP],
            snippet_structure: [SHARE_CN_STRUCTURE],
        },
    });

    const groupSelector = "#snippet_groups [name='社交']";
    expect(groupSelector).toHaveClass("o_draggable");
    expect(groupSelector).not.toHaveClass("o_disabled");

    const { moveTo, drop } = await contains(`${groupSelector} .o_snippet_thumbnail`).drag();
    expect(":iframe .oe_drop_zone").not.toHaveCount(0);
    await moveTo(":iframe .oe_drop_zone");
    await drop(getDragHelper());
    await waitForSnippetDialog();
    await contains(
        ".o_add_snippet_dialog .o_add_snippet_iframe:iframe .o_snippet_preview_wrap:has(.s_share_cn_block)"
    ).click();
    await waitForEndOfOperation();

    expect(":iframe #wrap > .s_share_cn_block").toHaveCount(1);
    expect(":iframe #wrap > .s_share_cn_block .s_share_cn").toHaveCount(1);
});
