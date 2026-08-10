/** @odoo-module **/

import { ListArchParser } from "@web/views/list/list_arch_parser";

const EXPAND_MODES = new Set(["all", "roots"]);

function configurationError(message) {
    throw new Error(`occ_treegrid 视图配置无效：${message}`);
}

/**
 * 解析并校验 TreeGrid 列表视图使用的显式接入字段选项。
 *
 * 将配置保留在常规字段的 `options` 中，可避免修改 Odoo 列表视图的 XML 架构。
 */
export class TreeGridListArchParser extends ListArchParser {
    parse(xmlDoc, models, modelName) {
        const archInfo = super.parse(xmlDoc, models, modelName);
        const fieldColumns = archInfo.columns.filter((column) => column.type === "field");
        const treeColumns = fieldColumns.filter(
            (column) => column.options?.occ_treegrid_column === true
        );
        const parentColumns = fieldColumns.filter(
            (column) => column.options?.occ_treegrid_parent === true
        );
        const handleColumns = fieldColumns.filter((column) => column.isHandle);

        if (treeColumns.length !== 1) {
            configurationError("必须且只能有一个字段设置选项 'occ_treegrid_column'。");
        }
        if (parentColumns.length !== 1) {
            configurationError("必须且只能有一个字段设置选项 'occ_treegrid_parent'。");
        }
        if (handleColumns.length !== 1) {
            configurationError("必须且只能有一个 Integer 字段使用组件 'handle'。");
        }
        if (archInfo.editable || archInfo.multiEdit) {
            configurationError("暂不支持行内编辑和多记录编辑。");
        }
        if (archInfo.defaultGroupBy || Object.keys(archInfo.groupBy.fields).length) {
            configurationError("暂不支持分组。");
        }

        const fields = models[modelName].fields;
        const treeColumn = treeColumns[0];
        const parentColumn = parentColumns[0];
        const handleColumn = handleColumns[0];
        const parentField = fields[parentColumn.name];
        const sequenceField = fields[handleColumn.name];

        if (parentField.type !== "many2one" || parentField.relation !== modelName) {
            configurationError(
                `字段 '${parentColumn.name}' 必须是指向当前模型自身的 Many2one。`
            );
        }
        if (sequenceField.type !== "integer") {
            configurationError(`拖拽字段 '${handleColumn.name}' 必须是 Integer。`);
        }

        for (const column of fieldColumns) {
            if (
                "occ_treegrid_default_expand" in (column.options || {}) &&
                column !== treeColumn
            ) {
                configurationError(
                    "选项 'occ_treegrid_default_expand' 必须设置在树结构列上。"
                );
            }
        }

        const defaultExpand = treeColumn.options.occ_treegrid_default_expand ?? "roots";
        if (!EXPAND_MODES.has(defaultExpand)) {
            configurationError(
                "选项 'occ_treegrid_default_expand' 只能是 'all' 或 'roots'。"
            );
        }

        archInfo.treeGrid = {
            defaultExpand,
            parentField: parentColumn.name,
            sequenceField: handleColumn.name,
            treeColumn: treeColumn.name,
            treeColumnId: treeColumn.id,
        };
        return archInfo;
    }
}
