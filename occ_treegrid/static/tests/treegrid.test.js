/** @odoo-module **/

import { animationFrame, describe, expect, press, queryAllTexts, test } from "@odoo/hoot";
import { parseXML } from "@web/core/utils/xml";
import { registry } from "@web/core/registry";
import {
    contains,
    defineModels,
    fields,
    makeServerError,
    models as testModels,
    mountView,
    onRpc,
    webModels,
} from "@web/../tests/web_test_helpers";
import { TreeGridListArchParser } from "@occ_treegrid/treegrid_arch_parser";
import { buildTreeGridRows, getRelationalId } from "@occ_treegrid/treegrid_utils";
import "@occ_treegrid/treegrid_view";

describe.current.tags("headless", "occ_treegrid");

const { ResCompany, ResPartner, ResUsers } = webModels;

const models = {
    node: {
        fields: {
            name: { string: "Name", type: "char" },
            parent_id: {
                relation: "node",
                string: "Parent",
                type: "many2one",
            },
            other_id: {
                relation: "other",
                string: "Other",
                type: "many2one",
            },
            rank: { string: "Rank", type: "char" },
            sequence: { string: "Sequence", type: "integer" },
        },
    },
    other: { fields: {} },
};

class TreeNode extends testModels.Model {
    _name = "tree.node";

    _records = [
        { id: 1, name: "Root", parent_id: false, sequence: 10 },
        { id: 2, name: "Child", parent_id: 1, sequence: 20 },
    ];

    name = fields.Char();
    parent_id = fields.Many2one({ relation: "tree.node" });
    sequence = fields.Integer();
}

defineModels([TreeNode, ResCompany, ResPartner, ResUsers]);

const TREEGRID_ARCH = `
    <list js_class="occ_treegrid" default_order="sequence,id">
        <field name="sequence" widget="handle"/>
        <field name="name"
               options="{'occ_treegrid_column': True,
                         'occ_treegrid_default_expand': 'all'}"/>
        <field name="parent_id" optional="hide"
               options="{'occ_treegrid_parent': True}"/>
    </list>
`;

function serverRecord(id, name, sequence, parentId = null) {
    return {
        id,
        name,
        parent_id: parentId ? { display_name: `Node ${parentId}`, id: parentId } : false,
        sequence,
    };
}

function mockTreeGridRead(records, options = {}) {
    let currentRecords = records;
    onRpc("tree.node", "occ_treegrid_read", ({ args }) => {
        options.onRead?.(args);
        return {
            ancestor_ids: options.ancestorIds || [],
            length: currentRecords.length,
            matched_ids: options.matchedIds || currentRecords.map((record) => record.id),
            max_nodes: 2000,
            orphan_ids: options.orphanIds || [],
            parent_field: "parent_id",
            records: currentRecords,
            sequence_field: "sequence",
        };
    });
    return (records) => {
        currentRecords = records;
    };
}

function parseArch(arch) {
    return new TreeGridListArchParser().parse(parseXML(arch), models, "node");
}

function makeRecord(id, parentId = null) {
    return {
        data: {
            id,
            name: `Node ${id}`,
            parent_id: parentId ? { display_name: `Node ${parentId}`, id: parentId } : false,
            sequence: id * 10,
        },
        id: `node_${id}`,
        resId: id,
    };
}

test("解析器读取合法字段选项并默认仅展开根节点", () => {
    const info = parseArch(`
        <list default_order="sequence,id">
            <field name="sequence" widget="handle"/>
            <field name="name" options="{'occ_treegrid_column': True}"/>
            <field name="parent_id" options="{'occ_treegrid_parent': True}"/>
        </list>
    `);
    expect(info.treeGrid).toEqual({
        defaultExpand: "roots",
        parentField: "parent_id",
        sequenceField: "sequence",
        treeColumn: "name",
        treeColumnId: "column_1",
    });
});

test("解析器拒绝无效的展开模式", () => {
    expect(() =>
        parseArch(`
            <list>
                <field name="sequence" widget="handle"/>
                <field name="name" options="{
                    'occ_treegrid_column': True,
                    'occ_treegrid_default_expand': 'children'
                }"/>
                <field name="parent_id" options="{'occ_treegrid_parent': True}"/>
            </list>
        `)
    ).toThrow("只能是 'all' 或 'roots'");
});

test("解析器强制执行树列、父字段、拖拽字段和禁止行内编辑约定", () => {
    expect(() =>
        parseArch(`
            <list>
                <field name="sequence" widget="handle"/>
                <field name="name" options="{'occ_treegrid_column': True}"/>
                <field name="parent_id"
                       options="{'occ_treegrid_column': True,
                                 'occ_treegrid_parent': True}"/>
            </list>
        `)
    ).toThrow("必须且只能有一个字段设置选项 'occ_treegrid_column'");
    expect(() =>
        parseArch(`
            <list>
                <field name="rank" widget="handle"/>
                <field name="name" options="{'occ_treegrid_column': True}"/>
                <field name="parent_id" options="{'occ_treegrid_parent': True}"/>
            </list>
        `)
    ).toThrow("拖拽字段 'rank' 必须是 Integer");
    expect(() =>
        parseArch(`
            <list>
                <field name="sequence" widget="handle"/>
                <field name="name" options="{'occ_treegrid_column': True}"/>
                <field name="other_id" options="{'occ_treegrid_parent': True}"/>
            </list>
        `)
    ).toThrow("必须是指向当前模型自身的 Many2one");
    expect(() =>
        parseArch(`
            <list editable="top">
                <field name="sequence" widget="handle"/>
                <field name="name" options="{'occ_treegrid_column': True}"/>
                <field name="parent_id" options="{'occ_treegrid_parent': True}"/>
            </list>
        `)
    ).toThrow("暂不支持行内编辑和多记录编辑");
    expect(() =>
        parseArch(`
            <list>
                <field name="sequence" widget="handle"/>
                <field name="name"
                       options="{'occ_treegrid_column': True,
                                 'occ_treegrid_default_expand': False}"/>
                <field name="parent_id" options="{'occ_treegrid_parent': True}"/>
            </list>
        `)
    ).toThrow("只能是 'all' 或 'roots'");
});

test("all 模式按深度优先输出并保留同级顺序", () => {
    const expandedIds = new Set();
    const result = buildTreeGridRows(
        [makeRecord(1), makeRecord(2, 1), makeRecord(4, 2), makeRecord(3, 1), makeRecord(5)],
        {
            defaultExpand: "all",
            expandedIds,
            knownExpandableIds: new Set(),
            matchedIds: [1, 2, 3, 4, 5],
            parentField: "parent_id",
        }
    );
    expect(result.visibleRows.map((row) => row.id)).toEqual([1, 2, 4, 3, 5]);
    expect(result.visibleRows.map((row) => row.depth)).toEqual([0, 1, 2, 1, 0]);
    expect([...expandedIds]).toEqual([1, 2]);
});

test("roots 模式初始仅渲染根节点", () => {
    const result = buildTreeGridRows([makeRecord(1), makeRecord(2, 1), makeRecord(3)], {
        defaultExpand: "roots",
        expandedIds: new Set(),
        knownExpandableIds: new Set(),
        matchedIds: [1, 2, 3],
        parentField: "parent_id",
    });
    expect(result.visibleRows.map((row) => row.id)).toEqual([1, 3]);
    expect(result.rowsById.get(1).isExpanded).toBe(false);
});

test("搜索补入的祖先仅作上下文并强制展开匹配路径", () => {
    const result = buildTreeGridRows(
        [makeRecord(1), makeRecord(2, 1), makeRecord(3, 2)],
        {
            ancestorIds: [1, 2],
            defaultExpand: "roots",
            expandedIds: new Set(),
            forceMatchedPaths: true,
            knownExpandableIds: new Set(),
            matchedIds: [3],
            parentField: "parent_id",
        }
    );
    expect(result.visibleRows.map((row) => row.id)).toEqual([1, 2, 3]);
    expect(result.visibleRows.map((row) => row.isContext)).toEqual([true, true, false]);
    expect(result.rowsById.get(1).isExpanded).toBe(true);
    expect(result.rowsById.get(2).isExpanded).toBe(true);
});

test("父节点不可用时以不可拖拽的临时根节点显示", () => {
    const result = buildTreeGridRows([makeRecord(2)], {
        defaultExpand: "roots",
        expandedIds: new Set(),
        knownExpandableIds: new Set(),
        matchedIds: [2],
        orphanIds: [2],
        parentField: "parent_id",
    });
    expect(result.visibleRows).toHaveLength(1);
    expect(result.visibleRows[0].depth).toBe(0);
    expect(result.visibleRows[0].isOrphan).toBe(true);
});

test("Many2one 标识兼容 web_read 与旧格式值", () => {
    expect(getRelationalId(false)).toBe(null);
    expect(getRelationalId([7, "Parent"])).toBe(7);
    expect(getRelationalId({ display_name: "Parent", id: 8 })).toBe(8);
    expect(getRelationalId(9)).toBe(9);
});

test("all 模式在重新加载后会展开新变为分支的节点", () => {
    const expandedIds = new Set();
    const knownExpandableIds = new Set();
    buildTreeGridRows([makeRecord(1)], {
        defaultExpand: "all",
        expandedIds,
        knownExpandableIds,
        matchedIds: [1],
        parentField: "parent_id",
    });

    const result = buildTreeGridRows([makeRecord(1), makeRecord(2, 1)], {
        defaultExpand: "all",
        expandedIds,
        knownExpandableIds,
        matchedIds: [1, 2],
        parentField: "parent_id",
    });

    expect(result.visibleRows.map((row) => row.id)).toEqual([1, 2]);
    expect(result.rowsById.get(1).isExpanded).toBe(true);
});

describe("occ_treegrid 渲染器集成", () => {
    test("视图注册表会渲染带深度优先行和 ARIA 元数据的 TreeGrid", async () => {
        expect(registry.category("views").contains("occ_treegrid")).toBe(true);
        mockTreeGridRead([
            serverRecord(1, "Root", 10),
            serverRecord(2, "Child A", 10, 1),
            serverRecord(3, "Grandchild", 10, 2),
            serverRecord(4, "Child B", 20, 1),
        ]);

        await mountView({
            arch: TREEGRID_ARCH,
            resModel: "tree.node",
            type: "list",
        });

        expect("table[role='treegrid']").toHaveCount(1);
        expect("tbody[role='rowgroup'] .o_data_row").toHaveCount(4);
        expect(".o_data_row:eq(0)").toHaveAttribute("aria-level", "1");
        expect(".o_data_row:eq(0)").toHaveAttribute("aria-expanded", "true");
        expect(".o_data_row:eq(2)").toHaveAttribute("aria-level", "3");
        expect(queryAllTexts("td[name='name']")).toEqual([
            "Root",
            "Child A",
            "Grandchild",
            "Child B",
        ]);
    });

    test("左右方向键会收起和展开当前分支", async () => {
        mockTreeGridRead([
            serverRecord(1, "Root", 10),
            serverRecord(2, "Child", 10, 1),
        ]);
        await mountView({ arch: TREEGRID_ARCH, resModel: "tree.node", type: "list" });

        await contains(".o_data_row:first td[name='name']").press("ArrowLeft");
        expect(".o_data_row").toHaveCount(1);
        expect(".o_data_row:first").toHaveAttribute("aria-expanded", "false");

        await contains(".o_data_row:first td[name='name']").press("ArrowRight");
        expect(".o_data_row").toHaveCount(2);
        expect(".o_data_row:first").toHaveAttribute("aria-expanded", "true");
    });

    test("祖先上下文行会弱化显示、自动展开且不能被选择", async () => {
        mockTreeGridRead(
            [serverRecord(1, "Context root", 10), serverRecord(2, "Match", 10, 1)],
            { ancestorIds: [1], matchedIds: [2] }
        );
        await mountView({ arch: TREEGRID_ARCH, resModel: "tree.node", type: "list" });

        expect(".o_data_row").toHaveCount(2);
        expect(".o_data_row:first").toHaveClass("o_treegrid_context");
        expect(".o_data_row:first .o_list_record_selector input").toHaveCount(0);
        expect(".o_data_row:eq(1) .o_list_record_selector input").toHaveCount(1);
        expect(".o_treegrid_draggable").toHaveCount(0);

        await contains("thead .o_list_record_selector input").click();
        expect(".o_data_row .o_list_record_selector input:checked").toHaveCount(1);
    });

    test("键盘范围选择不会包含祖先上下文行", async () => {
        mockTreeGridRead(
            [serverRecord(1, "Context root", 10), serverRecord(2, "Match", 10, 1)],
            { ancestorIds: [1], matchedIds: [2] }
        );
        await mountView({ arch: TREEGRID_ARCH, resModel: "tree.node", type: "list" });

        await press("ArrowDown");
        await press("ArrowDown");
        await press(["shift", "ArrowDown"]);
        await animationFrame();

        expect(".o_selection_box").toHaveText(/1\s+selected/);
        expect(".o_data_row:eq(1) .o_list_record_selector input").toBeChecked();
    });

    test("仅按排序字段升序排列时允许拖拽", async () => {
        const orders = [];
        mockTreeGridRead(
            [serverRecord(1, "B", 10), serverRecord(2, "A", 20)],
            { onRead: (args) => orders.push(args[2]) }
        );
        await mountView({ arch: TREEGRID_ARCH, resModel: "tree.node", type: "list" });

        expect(".o_treegrid_draggable").toHaveCount(2);
        await contains("thead th[data-name='name']").click();
        expect(".o_treegrid_draggable").toHaveCount(0);
        expect(orders).toEqual(["sequence ASC, id ASC", "name ASC, sequence ASC, id ASC"]);
    });

    test("显式筛选会禁用拖拽，即使没有补入祖先节点", async () => {
        mockTreeGridRead([
            serverRecord(1, "First", 10),
            serverRecord(2, "Second", 20),
        ]);
        await mountView({
            arch: TREEGRID_ARCH,
            context: { search_default_only_first: true },
            resModel: "tree.node",
            searchViewArch: `
                <search>
                    <filter name="only_first" domain="[('id', '=', 1)]"/>
                </search>
            `,
            type: "list",
        });

        expect(".o_treegrid_draggable").toHaveCount(0);
    });

    test("启用搜索面板分类时会禁用拖拽", async () => {
        mockTreeGridRead([
            serverRecord(1, "First", 10),
            serverRecord(2, "Second", 20),
        ]);
        await mountView({
            arch: TREEGRID_ARCH,
            context: { searchpanel_default_parent_id: 1 },
            resModel: "tree.node",
            searchViewArch: `
                <search>
                    <searchpanel>
                        <field name="parent_id"/>
                    </searchpanel>
                </search>
            `,
            type: "list",
        });

        expect(".o_treegrid_draggable").toHaveCount(0);
    });

    test("只读拖拽字段始终不能启用拖拽", async () => {
        mockTreeGridRead([
            serverRecord(1, "First", 10),
            serverRecord(2, "Second", 20),
        ]);
        await mountView({
            arch: TREEGRID_ARCH.replace(
                '<field name="sequence" widget="handle"/>',
                '<field name="sequence" widget="handle" readonly="1"/>'
            ),
            resModel: "tree.node",
            type: "list",
        });

        expect(".o_treegrid_draggable").toHaveCount(0);
    });

    test("非标准的次级排序会禁用拖拽", async () => {
        mockTreeGridRead([
            serverRecord(1, "First", 10),
            serverRecord(2, "Second", 10),
        ]);
        await mountView({
            arch: TREEGRID_ARCH.replace(
                'default_order="sequence,id"',
                'default_order="sequence,name,id"'
            ),
            resModel: "tree.node",
            type: "list",
        });

        expect(".o_treegrid_draggable").toHaveCount(0);
    });

    test("展开的子树会作为一个视觉整体拖动", async () => {
        let records = [
            serverRecord(1, "Root", 10),
            serverRecord(2, "Branch A", 10, 1),
            serverRecord(3, "Leaf", 10, 2),
            serverRecord(4, "Branch B", 20, 1),
        ];
        const setRecords = mockTreeGridRead(records);
        onRpc("tree.node", "occ_treegrid_resequence", ({ args }) => {
            expect.step(`resequence:${args.join(":")}`);
            records = [records[0], records[3], records[1], records[2]];
            setRecords(records);
            return { moved_id: 2, ordered_ids: [4, 2], parent_id: 1 };
        });
        await mountView({ arch: TREEGRID_ARCH, resModel: "tree.node", type: "list" });

        const { drop, moveTo } = await contains(
            ".o_data_row:contains('Branch A') .o_handle_cell"
        ).drag();
        await moveTo(".o_data_row:contains('Branch B')");
        expect(".o_treegrid_dragged_descendant").toHaveCount(1);
        await drop();
        await animationFrame();

        expect.verifySteps(["resequence:2:4:after"]);
        expect(queryAllTexts("td[name='name']")).toEqual([
            "Root",
            "Branch B",
            "Branch A",
            "Leaf",
        ]);
    });

    test("跨父节点拖放会在调用服务端前被拒绝", async () => {
        mockTreeGridRead([
            serverRecord(1, "Root A", 10),
            serverRecord(2, "Child A", 10, 1),
            serverRecord(3, "Root B", 20),
            serverRecord(4, "Child B", 10, 3),
        ]);
        onRpc("tree.node", "occ_treegrid_resequence", () => expect.step("resequence"));
        await mountView({ arch: TREEGRID_ARCH, resModel: "tree.node", type: "list" });

        await contains(".o_data_row:contains('Child A') .o_handle_cell").dragAndDrop(
            ".o_data_row:contains('Child B')"
        );
        await animationFrame();

        expect.verifySteps([]);
        expect(".o_notification_bar.bg-warning").toHaveCount(1);
        expect(".o_notification_content").toHaveText(
            "树节点只能在同级节点之间的边界处重新排序。"
        );
    });

    test("同级拖放会调用专用 RPC 并在保留展开状态的情况下重新加载", async () => {
        let records = [
            serverRecord(1, "Root", 10),
            serverRecord(2, "Child A", 10, 1),
            serverRecord(3, "Child B", 20, 1),
        ];
        const setRecords = mockTreeGridRead(records, {
            onRead: () => expect.step("read"),
        });
        onRpc("tree.node", "occ_treegrid_resequence", ({ args }) => {
            expect.step(`resequence:${args.join(":")}`);
            records = [records[0], records[2], records[1]];
            setRecords(records);
            return { moved_id: 3, ordered_ids: [3, 2], parent_id: 1 };
        });
        await mountView({ arch: TREEGRID_ARCH, resModel: "tree.node", type: "list" });
        expect.verifySteps(["read"]);

        await contains(".o_data_row:contains('Child B') .o_handle_cell").dragAndDrop(
            ".o_data_row:contains('Child A')"
        );
        await animationFrame();

        expect.verifySteps(["resequence:3:2:before", "read"]);
        expect(queryAllTexts("td[name='name']")).toEqual(["Root", "Child B", "Child A"]);
        expect(".o_data_row:first").toHaveAttribute("aria-expanded", "true");
    });

    test("同级拖放失败时保留原顺序并提示错误", async () => {
        mockTreeGridRead([
            serverRecord(1, "First", 10),
            serverRecord(2, "Second", 20),
        ]);
        onRpc("tree.node", "occ_treegrid_resequence", () => {
            expect.step("resequence failed");
            throw makeServerError({ message: "Cannot resequence" });
        });
        await mountView({ arch: TREEGRID_ARCH, resModel: "tree.node", type: "list" });

        await contains(".o_data_row:contains('Second') .o_handle_cell").dragAndDrop(
            ".o_data_row:contains('First')"
        );
        await animationFrame();

        expect.verifySteps(["resequence failed"]);
        expect(queryAllTexts("td[name='name']")).toEqual(["First", "Second"]);
        expect(".o_notification_bar.bg-danger").toHaveCount(1);
        expect(".o_notification_content").toHaveText("无法保存树节点顺序，请重试。");
    });
});
