/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { useSortable } from "@web/core/utils/sortable_owl";
import { ListRenderer } from "@web/views/list/list_renderer";
import { onWillRender, useState } from "@odoo/owl";
import { buildTreeGridRows } from "./treegrid_utils";

const GROUP_SEARCH_TYPES = new Set(["dateGroupBy", "groupBy"]);

export class TreeGridListRenderer extends ListRenderer {
    static template = "occ_treegrid.ListRenderer";
    static rowsTemplate = "occ_treegrid.ListRenderer.Rows";
    static recordRowTemplate = "occ_treegrid.ListRenderer.RecordRow";

    setup() {
        super.setup();
        this.expandedIds = new Set();
        this.knownExpandableIds = new Set();
        this.treeGridState = useState({ resequencing: false, version: 0 });
        this.treeRows = [];
        this.allTreeRows = [];
        this.treeRowsById = new Map();
        this.forcedExpandedIds = new Set();
        this.draggedRecord = null;
        this.draggedSubtreeIds = new Set();
        this.draggedDescendantElements = [];

        onWillRender(() => this.prepareTreeGridRows());

        useSortable({
            enable: () => this.canTreeGridResequence,
            ref: this.rootRef,
            elements: ".o_treegrid_draggable",
            handle: ".o_handle_cell",
            cursor: "grabbing",
            placeholderClasses: ["d-table-row", "o_treegrid_placeholder"],
            onDragStart: (params) => this.onTreeGridDragStart(params),
            onDragEnd: (params) => this.onTreeGridDragEnd(params),
            onDrop: (params) => this.onTreeGridDrop(params),
        });
    }

    prepareTreeGridRows() {
        const meta = this.props.list.treeGridMeta || {};
        const matchedIds = meta.matchedIds || this.props.list.records.map((record) => record.resId);
        const result = buildTreeGridRows(this.props.list.records, {
            ancestorIds: meta.ancestorIds,
            defaultExpand: this.props.archInfo.treeGrid.defaultExpand,
            expandedIds: this.expandedIds,
            forceMatchedPaths: this.hasExplicitSearch,
            knownExpandableIds: this.knownExpandableIds,
            matchedIds,
            orphanIds: meta.orphanIds,
            parentField: meta.parentField || this.props.archInfo.treeGrid.parentField,
        });
        this.treeRows = result.visibleRows;
        this.allTreeRows = result.allRows;
        this.treeRowsById = result.rowsById;
        this.forcedExpandedIds = result.forcedExpandedIds;
    }

    // 禁用 Odoo 平铺列表的排序器。TreeGrid 会注册独立排序钩子，并仅在校验拖放位置后
    // 调用 occ_treegrid_resequence。
    get canResequenceRows() {
        return false;
    }

    get hasExplicitSearch() {
        if (this.props.list.treeGridMeta?.ancestorIds?.length) {
            return true;
        }
        const searchModel = this.env.searchModel;
        if (
            searchModel?.getSections?.().some((section) => {
                if (section.type === "category") {
                    return Boolean(section.activeValueId);
                }
                return (
                    section.type === "filter" &&
                    [...(section.values?.values?.() || [])].some((value) => value.checked)
                );
            })
        ) {
            return true;
        }
        return Boolean(
            searchModel?.query?.some((queryItem) => {
                const searchItem = searchModel.searchItems[queryItem.searchItemId];
                return searchItem && !GROUP_SEARCH_TYPES.has(searchItem.type);
            })
        );
    }

    get canTreeGridResequence() {
        const { list, readonly } = this.props;
        const sequenceField = list.treeGridMeta?.sequenceField;
        const [sequenceOrder, idOrder] = list.orderBy || [];
        return Boolean(
            !readonly &&
                this.activeActions.edit !== false &&
                !this.hasExplicitSearch &&
                !this.treeGridState.resequencing &&
                !list.model.treeGridLoading &&
                sequenceField &&
                list.handleField === sequenceField &&
                sequenceOrder?.name === sequenceField &&
                sequenceOrder.asc &&
                idOrder?.name === "id" &&
                idOrder.asc
        );
    }

    canTreeGridResequenceRecord(record) {
        const row = this.treeRowsById.get(record.resId);
        const handleColumn = this.props.archInfo.columns.find(
            (column) =>
                column.type === "field" && column.name === this.props.list.handleField
        );
        return Boolean(
            this.canTreeGridResequence &&
                row &&
                !row.isContext &&
                !row.isOrphan &&
                handleColumn &&
                !this.isCellReadonly(handleColumn, record) &&
                !this.isRecordReadonly(record)
        );
    }

    getRowClass(record) {
        const classNames = [super.getRowClass(record)];
        const row = this.treeRowsById.get(record.resId);
        if (row?.isContext) {
            classNames.push("o_treegrid_context");
        }
        if (row?.isOrphan) {
            classNames.push("o_treegrid_orphan");
        }
        if (this.canTreeGridResequenceRecord(record)) {
            classNames.push("o_treegrid_draggable");
        }
        return classNames.filter(Boolean).join(" ");
    }

    getFieldProps(record, column) {
        const props = super.getFieldProps(record, column);
        if (column.widget === "handle") {
            props.readonly = props.readonly || !this.canTreeGridResequenceRecord(record);
        }
        return props;
    }

    isTreeGridColumn(column) {
        return column.id === this.props.archInfo.treeGrid.treeColumnId;
    }

    isTreeGridSelectable(record) {
        return !this.treeRowsById.get(record.resId)?.isContext;
    }

    get selectableRecords() {
        return this.props.list.records.filter((record) => this.isTreeGridSelectable(record));
    }

    get selectAll() {
        const records = this.selectableRecords;
        return Boolean(records.length && records.every((record) => record.selected));
    }

    toggleSelection() {
        if (!this.canSelectRecord) {
            return;
        }
        const selected = !this.selectAll;
        for (const record of this.selectableRecords) {
            if (record.selected !== selected) {
                record.toggleSelection();
            }
        }
    }

    toggleRecordSelection(record) {
        if (!this.isTreeGridSelectable(record)) {
            return;
        }
        return super.toggleRecordSelection(record);
    }

    toggleRangeSelection(record) {
        const records = this.treeRows
            .filter((row) => !row.isContext)
            .map((row) => row.record);
        const recordIndex = records.indexOf(record);
        const lastIndex = records.indexOf(this.lastCheckedRecord);
        if (recordIndex < 0 || lastIndex < 0) {
            return record.toggleSelection();
        }
        const [start, end] = [recordIndex, lastIndex].sort((a, b) => a - b);
        const selected = !record.selected;
        for (const item of records.slice(start, end + 1)) {
            if (item.selected !== selected) {
                item.toggleSelection();
            }
        }
    }

    expandCheckboxes(record, direction) {
        const records = this.treeRows
            .filter((row) => !row.isContext)
            .map((row) => row.record);
        if (!records.length) {
            return false;
        }
        const recordIndex = records.indexOf(record);
        if (recordIndex < 0) {
            if (direction !== "down") {
                return false;
            }
            const defaultRecord = records[0];
            this.shiftKeyedRecord = defaultRecord;
            defaultRecord.toggleSelection(true);
            return true;
        }

        let shiftKeyedRecordIndex = records.indexOf(this.shiftKeyedRecord);
        if (shiftKeyedRecordIndex < 0) {
            this.shiftKeyedRecord = record;
            shiftKeyedRecordIndex = recordIndex;
        }
        let nextRecord;
        let isExpanding;
        if (direction === "up") {
            if (recordIndex <= 0) {
                return false;
            }
            nextRecord = records[recordIndex - 1];
            isExpanding = shiftKeyedRecordIndex > recordIndex - 1;
        } else {
            if (recordIndex === records.length - 1) {
                return false;
            }
            nextRecord = records[recordIndex + 1];
            isExpanding = shiftKeyedRecordIndex < recordIndex + 1;
        }

        if (isExpanding) {
            record.toggleSelection(true);
            nextRecord.toggleSelection(true);
        } else {
            record.toggleSelection(false);
        }
        return true;
    }

    getTreeGridIndentStyle(treeRow) {
        return `--o-treegrid-level: ${treeRow.depth};`;
    }

    toggleTreeGridRow(treeRow) {
        if (!treeRow.hasChildren || this.forcedExpandedIds.has(treeRow.id)) {
            return;
        }
        if (this.expandedIds.has(treeRow.id)) {
            this.expandedIds.delete(treeRow.id);
        } else {
            this.expandedIds.add(treeRow.id);
        }
        this.treeGridState.version++;
    }

    onTreeRowKeydown(treeRow, ev) {
        if (!treeRow.hasChildren || !["ArrowLeft", "ArrowRight"].includes(ev.key)) {
            return;
        }
        if (ev.key === "ArrowRight" && !treeRow.isExpanded) {
            this.toggleTreeGridRow(treeRow);
        } else if (ev.key === "ArrowLeft" && treeRow.isExpanded) {
            this.toggleTreeGridRow(treeRow);
        } else {
            return;
        }
        ev.preventDefault();
        ev.stopPropagation();
    }

    getRecordFromElement(element) {
        const resId = Number(element?.dataset.resId);
        return this.props.list.records.find((record) => record.resId === resId);
    }

    onTreeGridDragStart({ element }) {
        this.draggedRecord = this.getRecordFromElement(element);
        if (!this.draggedRecord) {
            return;
        }
        super.sortStart({ element });
        const rootRow = this.treeRowsById.get(this.draggedRecord.resId);
        this.draggedSubtreeIds = new Set([rootRow.id]);
        for (const row of this.allTreeRows) {
            let parentId = row.parentId;
            while (parentId && this.treeRowsById.has(parentId)) {
                if (parentId === rootRow.id) {
                    this.draggedSubtreeIds.add(row.id);
                    break;
                }
                parentId = this.treeRowsById.get(parentId).parentId;
            }
        }
        this.draggedDescendantElements = [
            ...this.rootRef.el.querySelectorAll("tr.o_data_row"),
        ].filter(
            (rowElement) =>
                this.draggedSubtreeIds.has(Number(rowElement.dataset.resId)) &&
                Number(rowElement.dataset.resId) !== rootRow.id
        );
        for (const descendant of this.draggedDescendantElements) {
            descendant.classList.add("o_treegrid_dragged_descendant");
        }
        element.classList.add("o_treegrid_dragging");
    }

    onTreeGridDragEnd({ element }) {
        super.sortStop({ element });
        element.classList.remove("o_treegrid_dragging");
        for (const descendant of this.draggedDescendantElements) {
            descendant.classList.remove("o_treegrid_dragged_descendant");
        }
        this.draggedRecord = null;
        this.draggedSubtreeIds = new Set();
        this.draggedDescendantElements = [];
    }

    findAdjacentTreeRow(element, direction) {
        let current = element;
        while (current) {
            if (current.matches?.("tr.o_data_row")) {
                const id = Number(current.dataset.resId);
                if (!this.draggedSubtreeIds.has(id) && this.treeRowsById.has(id)) {
                    return this.treeRowsById.get(id);
                }
            }
            current =
                direction === "previous"
                    ? current.previousElementSibling
                    : current.nextElementSibling;
        }
        return null;
    }

    getSiblingAtParent(row, parentId) {
        const seen = new Set();
        let current = row;
        while (current && current.parentId !== parentId && !seen.has(current.id)) {
            seen.add(current.id);
            current = this.treeRowsById.get(current.parentId);
        }
        return current?.parentId === parentId ? current : null;
    }

    getTreeGridDropTarget(previousElement, nextElement, movedRow) {
        const previousRow = this.findAdjacentTreeRow(previousElement, "previous");
        const nextRow = this.findAdjacentTreeRow(nextElement, "next");
        const previousSibling = previousRow
            ? this.getSiblingAtParent(previousRow, movedRow.parentId)
            : null;
        const nextSibling = nextRow ? this.getSiblingAtParent(nextRow, movedRow.parentId) : null;

        // 位于其他节点子树内部的占位符不属于同级边界。
        if (previousSibling && nextSibling && previousSibling.id === nextSibling.id) {
            return null;
        }
        if (
            nextSibling &&
            nextSibling.id !== movedRow.id &&
            !nextSibling.isContext &&
            !nextSibling.isOrphan
        ) {
            return { position: "before", target: nextSibling };
        }
        if (
            previousSibling &&
            previousSibling.id !== movedRow.id &&
            !previousSibling.isContext &&
            !previousSibling.isOrphan
        ) {
            return { position: "after", target: previousSibling };
        }
        return null;
    }

    async onTreeGridDrop({ previous, next }) {
        const movedRecord = this.draggedRecord;
        const movedRow = movedRecord && this.treeRowsById.get(movedRecord.resId);
        const drop = movedRow && this.getTreeGridDropTarget(previous, next, movedRow);
        if (!drop) {
            this.notificationService.add(
                _t("树节点只能在同级节点之间的边界处重新排序。"),
                { type: "warning" }
            );
            return;
        }

        this.treeGridState.resequencing = true;
        try {
            await this.props.list.model.treeGridResequence(
                movedRow.id,
                drop.target.id,
                drop.position
            );
        } catch {
            this.notificationService.add(_t("无法保存树节点顺序，请重试。"), {
                type: "danger",
            });
        } finally {
            this.treeGridState.resequencing = false;
        }
    }
}
