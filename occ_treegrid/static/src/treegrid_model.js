/** @odoo-module **/

import { DynamicRecordList } from "@web/model/relational_model/dynamic_record_list";
import { RelationalModel } from "@web/model/relational_model/relational_model";
import { getFieldsSpec } from "@web/model/relational_model/utils";
import { orderByToString } from "@web/search/utils/order_by";

export class TreeGridDynamicRecordList extends DynamicRecordList {
    _setData(data) {
        super._setData(data);
        const recordIds = this.records.map((record) => record.resId);
        this.treeGridMeta = {
            ancestorIds: data.ancestor_ids || [],
            matchedIds: data.matched_ids || recordIds,
            maxNodes: data.max_nodes,
            orphanIds: data.orphan_ids || [],
            parentField:
                data.parent_field || this.model.treeGridConfig?.parentField || "parent_id",
            sequenceField:
                data.sequence_field || this.model.treeGridConfig?.sequenceField || "sequence",
        };
        this.count = this.treeGridMeta.matchedIds.length;
        if (this.isDomainSelected) {
            const matchedIds = new Set(this.treeGridMeta.matchedIds);
            for (const record of this.records) {
                record.selected = matchedIds.has(record.resId);
            }
        }
    }

    // 标准列表排序器不能修改展平后的深度优先行；渲染器改用 TreeGrid 专用 RPC。
    canResequence() {
        return false;
    }

    _selectDomain(value) {
        super._selectDomain(value);
        if (value && this.treeGridMeta) {
            const matchedIds = new Set(this.treeGridMeta.matchedIds);
            for (const record of this.records) {
                if (!matchedIds.has(record.resId)) {
                    record.selected = false;
                }
            }
        }
    }
}

export class TreeGridRelationalModel extends RelationalModel {
    static DynamicRecordList = TreeGridDynamicRecordList;

    setup(params, services) {
        super.setup(params, services);
        this.treeGridConfig = params.treeGrid;
        this.treeGridLoadMeta = new WeakMap();
        this.treeGridLoadingCount = 0;
    }

    get treeGridLoading() {
        return this.treeGridLoadingCount > 0;
    }

    setTreeGridLoading(loading) {
        this.treeGridLoadingCount = Math.max(
            0,
            this.treeGridLoadingCount + (loading ? 1 : -1)
        );
        this.notify();
    }

    async load(params = {}) {
        // 收藏筛选中可能残留分组条件，即使 TreeGrid 搜索菜单并不显示分组选项；
        // 因此始终保持此模型不分组。
        return super.load({ ...params, groupBy: [] });
    }

    async _loadData(config, cache) {
        const data = await super._loadData(config, cache);
        const treeGridMeta = this.treeGridLoadMeta.get(config);
        this.treeGridLoadMeta.delete(config);
        return treeGridMeta ? { ...data, ...treeGridMeta } : data;
    }

    async _loadUngroupedList(config) {
        this.setTreeGridLoading(true);
        try {
            const orderBy = config.orderBy.filter((order) => order.name !== "__count");
            const specification = getFieldsSpec(
                config.activeFields,
                config.fields,
                config.context
            );
            const response = await this.orm.call(
                config.resModel,
                "occ_treegrid_read",
                [config.domain, specification, orderByToString(orderBy)],
                { context: { bin_size: true, ...config.context } }
            );
            const records = response.records || [];
            if (
                response.parent_field &&
                response.parent_field !== this.treeGridConfig.parentField
            ) {
                throw new Error(
                    `TreeGrid 父字段不一致：视图使用 ` +
                        `'${this.treeGridConfig.parentField}'，` +
                        `模型使用 '${response.parent_field}'。`
                );
            }
            if (
                response.sequence_field &&
                response.sequence_field !== this.treeGridConfig.sequenceField
            ) {
                throw new Error(
                    `TreeGrid 排序字段不一致：视图使用 ` +
                        `'${this.treeGridConfig.sequenceField}'，` +
                        `模型使用 '${response.sequence_field}'。`
                );
            }

            // TreeGrid 有意不分页。保持标准列表计数一致，使完整树加载后分页器继续隐藏。
            config.offset = 0;
            config.limit = Math.max(records.length, 1);
            config.countLimit = Number.MAX_SAFE_INTEGER;
            const treeGridMeta = { ...response };
            delete treeGridMeta.records;
            delete treeGridMeta.length;
            this.treeGridLoadMeta.set(config, treeGridMeta);
            return {
                ...response,
                records,
                length: records.length,
            };
        } finally {
            this.setTreeGridLoading(false);
        }
    }

    async treeGridResequence(movedId, targetId, position) {
        const result = await this.mutex.exec(async () => {
            this.setTreeGridLoading(true);
            try {
                return await this.orm.call(
                    this.config.resModel,
                    "occ_treegrid_resequence",
                    [movedId, targetId, position],
                    { context: this.config.context }
                );
            } finally {
                this.setTreeGridLoading(false);
            }
        });

        // 释放互斥锁后，通过当前列表数据点重新加载。与 model.load() 不同，list.load()
        // 不受 KeepLast 包装，因此并发搜索不会让此次重新排序一直处于未完成状态。
        const reloadedRoot = this.root;
        await reloadedRoot.load();
        if (this.root !== reloadedRoot) {
            await this.root.load();
        }
        return result;
    }
}
