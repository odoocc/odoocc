/** @odoo-module **/

export function getRelationalId(value) {
    if (!value) {
        return null;
    }
    if (Array.isArray(value)) {
        return value[0] || null;
    }
    if (typeof value === "object") {
        return value.id || value.resId || null;
    }
    return value;
}

function getRecordId(record) {
    return record.resId || record.data?.id || record.id;
}

function getRecordData(record) {
    return record.data || record;
}

function hasParentCycle(row, rowsById) {
    const seen = new Set([row.id]);
    let parentId = row.parentId;
    while (parentId && rowsById.has(parentId)) {
        if (seen.has(parentId)) {
            return true;
        }
        seen.add(parentId);
        parentId = rowsById.get(parentId).parentId;
    }
    return false;
}

/**
 * 将 RPC 返回的有序平铺记录转换为结构行和可见的深度优先行。
 * 子节点保留 RPC 结果中的顺序，该结果已经按列表当前排序条件排列。
 */
export function buildTreeGridRows(
    records,
    {
        ancestorIds = [],
        defaultExpand = "roots",
        expandedIds = new Set(),
        forceMatchedPaths = false,
        knownExpandableIds = new Set(),
        matchedIds = [],
        orphanIds = [],
        parentField,
    }
) {
    const ancestorSet = new Set(ancestorIds);
    const matchedSet = new Set(matchedIds);
    const orphanSet = new Set(orphanIds);
    const rows = records.map((record) => ({
        children: [],
        id: getRecordId(record),
        isContext: false,
        isOrphan: false,
        parentId: getRelationalId(getRecordData(record)[parentField]),
        record,
    }));
    const rowsById = new Map(rows.map((row) => [row.id, row]));
    const roots = [];

    for (const row of rows) {
        row.isContext = ancestorSet.has(row.id) && !matchedSet.has(row.id);
        const parent = row.parentId && rowsById.get(row.parentId);
        if (orphanSet.has(row.id)) {
            row.isOrphan = true;
            roots.push(row);
        } else if (!row.parentId) {
            roots.push(row);
        } else if (!parent || row.parentId === row.id || hasParentCycle(row, rowsById)) {
            row.isOrphan = true;
            roots.push(row);
        } else {
            parent.children.push(row);
        }
    }

    const forcedExpandedIds = new Set(ancestorSet);
    if (forceMatchedPaths) {
        for (const matchedId of matchedSet) {
            let row = rowsById.get(matchedId);
            const seen = new Set();
            while (row?.parentId && rowsById.has(row.parentId) && !seen.has(row.parentId)) {
                seen.add(row.parentId);
                forcedExpandedIds.add(row.parentId);
                row = rowsById.get(row.parentId);
            }
        }
    }

    const allRows = [];
    const collect = (row, depth, position, setSize) => {
        row.depth = depth;
        row.position = position;
        row.setSize = setSize;
        row.hasChildren = Boolean(row.children.length);
        if (row.hasChildren && !knownExpandableIds.has(row.id)) {
            knownExpandableIds.add(row.id);
            if (defaultExpand === "all") {
                expandedIds.add(row.id);
            }
        }
        row.isExpanded =
            row.hasChildren &&
            (expandedIds.has(row.id) || forcedExpandedIds.has(row.id));
        allRows.push(row);
        row.children.forEach((child, index) =>
            collect(child, depth + 1, index + 1, row.children.length)
        );
    };
    roots.forEach((root, index) => collect(root, 0, index + 1, roots.length));

    const visibleRows = [];
    const makeVisible = (row) => {
        visibleRows.push(row);
        if (row.isExpanded) {
            row.children.forEach(makeVisible);
        }
    };
    roots.forEach(makeVisible);

    return { allRows, forcedExpandedIds, rowsById, visibleRows };
}
