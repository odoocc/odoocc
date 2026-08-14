/** @odoo-module **/

import { describe, expect, getFixture, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";

import { renderMermaidDiagrams } from "../src/js/mermaid_renderer";

describe.current.tags("desktop", "occ_markdown");

test("服务端流程图容器使用严格安全模式渲染为SVG", async () => {
    let initializeOptions;
    patchWithCleanup(window, {
        mermaid: {
            initialize: (options) => (initializeOptions = options),
            render: async (_id, source) => ({
                svg: `<svg><text>${source}</text></svg>`,
            }),
        },
    });
    const diagram = document.createElement("pre");
    diagram.className = "mermaid o_occ_markdown_mermaid";
    diagram.dataset.occMermaidState = "pending";
    diagram.textContent = "flowchart TD\nA-->B";
    getFixture().append(diagram);

    await renderMermaidDiagrams(getFixture());

    expect(initializeOptions.securityLevel).toBe("strict");
    expect(".o_occ_markdown_mermaid_diagram svg").toHaveCount(1);
    expect(".o_occ_markdown_mermaid_diagram").toHaveText(/flowchart TD/);
});
