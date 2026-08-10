/** @odoo-module **/

import { expect, test } from "@odoo/hoot";

import { toDesignerGraph, toServerGraph } from "@occ_approval/api";

test.tags("headless");

function graphWithValue(value, extraEdgeValues = {}) {
    return {
        schema_version: 1,
        nodes: [
            { id: "start", type: "start", name: "Start" },
            { id: "end", type: "end", name: "End" },
        ],
        edges: [
            {
                source: "start",
                target: "end",
                sequence: 10,
                condition: [["name", "=", value]],
                ...extraEdgeValues,
            },
        ],
    };
}

test("simple edge condition values keep their JSON type during a designer round trip", () => {
    const values = ["1", "true", "null", "[1]", 1, true, false, null, [1], { key: 1 }];
    for (const value of values) {
        const designerGraph = toDesignerGraph(graphWithValue(value));
        const serverGraph = toServerGraph(designerGraph);
        expect(serverGraph.edges[0].condition[0][2]).toEqual(value);
    }
});

test("edge labels are optional and explicit labels survive a designer round trip", () => {
    const withoutLabel = toServerGraph(toDesignerGraph(graphWithValue("draft")));
    expect(Object.hasOwn(withoutLabel.edges[0], "label")).toBe(false);

    const withLabel = toServerGraph(
        toDesignerGraph(graphWithValue("draft", { label: "Draft route" }))
    );
    expect(withLabel.edges[0].label).toBe("Draft route");
});

test("typed condition editors reject invalid number and JSON values", () => {
    const numberGraph = toDesignerGraph(graphWithValue(1));
    numberGraph.edges[0].condition.value = "not-a-number";
    expect(() => toServerGraph(numberGraph)).toThrow();

    const jsonGraph = toDesignerGraph(graphWithValue([1]));
    jsonGraph.edges[0].condition.value = "[";
    expect(() => toServerGraph(jsonGraph)).toThrow();
});
