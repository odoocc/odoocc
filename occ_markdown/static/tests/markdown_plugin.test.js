/** @odoo-module **/

import { describe, expect, test } from "@odoo/hoot";

import { OccMarkdownDialog } from "../src/js/markdown_dialog";
import { OccMarkdownPlugin } from "../src/js/markdown_plugin";

describe.current.tags("headless", "occ_markdown");

function makePlugin() {
    return new OccMarkdownPlugin({
        document,
        editable: document.body,
        config: { getRecordInfo: () => ({ resModel: "res.partner", resId: 7 }) },
        services: {},
        dependencies: {
            dialog: {
                addDialog(component, props) {
                    expect.step(
                        component === OccMarkdownDialog ? "打开Markdown对话框" : "错误对话框"
                    );
                    expect(props.resModel).toBe("res.partner");
                    expect(props.resId).toBe(7);
                    const fragment = document.createDocumentFragment();
                    fragment.append(document.createElement("p"));
                    props.insert(fragment);
                },
            },
            dom: { insert: () => expect.step("插入服务端HTML") },
            history: { addStep: () => expect.step("记录撤销步骤") },
        },
        getResource: () => [],
        dispatchTo: () => {},
        delegateTo: () => {},
        checkPredicates: () => true,
    });
}

test("全局Powerbox注册Markdown命令并打开同一编辑器", () => {
    const plugin = makePlugin();
    expect(plugin.resources.user_commands[0].id).toBe("occInsertMarkdown");
    expect(plugin.resources.powerbox_items.object.commandId).toBe("occInsertMarkdown");
    plugin.resources.user_commands[0].run();
    expect.verifySteps(["打开Markdown对话框", "插入服务端HTML", "记录撤销步骤"]);
});
