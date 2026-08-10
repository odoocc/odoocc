from copy import deepcopy

from odoo import api, models
from odoo.exceptions import AccessError, LockError, UserError


def _treegrid_configuration(model):
    """返回并校验 ``model`` 上配置的树结构字段。"""
    parent_name = getattr(model, "_occ_treegrid_parent_field", None)
    sequence_name = getattr(model, "_occ_treegrid_sequence_field", None)
    max_nodes = getattr(model, "_occ_treegrid_max_nodes", None)

    parent_field = model._fields.get(parent_name)
    if (
        not parent_name
        or not parent_field
        or parent_field.type != "many2one"
        or parent_field.comodel_name != model._name
        or not parent_field.store
    ):
        raise UserError(
            model.env._(
                "TreeGrid 模型 %(model)s 必须配置一个已存储且指向自身的 "
                "Many2one 父字段。",
                model=model._name,
            )
        )

    sequence_field = model._fields.get(sequence_name)
    if (
        not sequence_name
        or not sequence_field
        or sequence_field.type != "integer"
        or not sequence_field.store
    ):
        raise UserError(
            model.env._(
                "TreeGrid 模型 %(model)s 必须配置一个已存储的 Integer 排序字段。",
                model=model._name,
            )
        )

    if isinstance(max_nodes, bool) or not isinstance(max_nodes, int) or max_nodes <= 0:
        raise UserError(
            model.env._(
                "TreeGrid 模型 %(model)s 必须配置一个大于零的最大节点数。",
                model=model._name,
            )
        )

    return parent_name, sequence_name, max_nodes


def _treegrid_record_id(model, value):
    if isinstance(value, bool):
        raise AccessError(model.env._("请求的 TreeGrid 记录不可用。"))
    try:
        record_id = int(value)
    except (OverflowError, TypeError, ValueError) as error:
        raise AccessError(
            model.env._("请求的 TreeGrid 记录不可用。")
        ) from error
    if record_id <= 0 or (
        isinstance(value, float) and not value.is_integer()
    ):
        raise AccessError(model.env._("请求的 TreeGrid 记录不可用。"))
    return record_id


def _treegrid_raise_too_many_nodes(model, max_nodes):
    raise UserError(
        model.env._(
            "当前 TreeGrid 的可见节点超过 %(max_nodes)s 个，请缩小搜索范围后再打开。",
            max_nodes=max_nodes,
        )
    )


def _treegrid_read_specification(model, specification, parent_name, sequence_name):
    if not isinstance(specification, dict):
        raise UserError(
            model.env._("TreeGrid 字段规格必须使用映射结构。")
        )

    read_specification = deepcopy(specification)
    parent_specification = read_specification.setdefault(parent_name, {})
    if not isinstance(parent_specification, dict):
        raise UserError(
            model.env._("TreeGrid 父字段规格无效。")
        )
    related_fields = parent_specification.setdefault("fields", {})
    if not isinstance(related_fields, dict):
        raise UserError(
            model.env._("TreeGrid 父字段规格无效。")
        )
    related_fields.setdefault("display_name", {})
    read_specification.setdefault(sequence_name, {})
    return read_specification


class OccTreegridMixin(models.AbstractModel):
    _name = "occ.treegrid.mixin"
    _description = "OCC 层级列表混入"

    _occ_treegrid_parent_field = "parent_id"
    _occ_treegrid_sequence_field = "sequence"
    _occ_treegrid_max_nodes = 2000

    @api.model
    @api.readonly
    def occ_treegrid_read(self, domain, specification, order=None):
        """一次返回匹配节点及当前用户可读取的祖先链。"""
        parent_name, sequence_name, max_nodes = _treegrid_configuration(self)
        if order is not None and not isinstance(order, str):
            raise UserError(self.env._("TreeGrid 排序条件必须是字符串。"))
        order = order or f"{sequence_name}, id"
        read_specification = _treegrid_read_specification(
            self, specification, parent_name, sequence_name
        )

        # 提前执行与标准 Web 读取方法一致的 ACL 检查。
        self.browse().check_access("read")
        matching_records = self.search(domain, order=order, limit=max_nodes + 1)
        if len(matching_records) > max_nodes:
            _treegrid_raise_too_many_nodes(self, max_nodes)

        all_records = matching_records
        ancestor_records = self.browse()
        frontier = matching_records
        visited_ids = set(matching_records.ids)

        while frontier:
            parent_ids = {
                record[parent_name].id
                for record in frontier
                if record[parent_name]
            }
            parent_ids.difference_update(visited_ids)
            if not parent_ids:
                break

            remaining = max_nodes - len(all_records)
            # 普通搜索会保留 active_test、ACL 与记录规则，因此不会补入已归档或
            # 当前用户不可访问的父节点。
            readable_parents = self.search(
                [("id", "in", list(parent_ids))],
                order=order,
                limit=remaining + 1,
            )
            if len(readable_parents) > remaining:
                _treegrid_raise_too_many_nodes(self, max_nodes)

            # 将所有尝试读取的 ID 标记为已访问；即使异常循环层级中存在不可读父节点，
            # 也能在此终止遍历。
            visited_ids.update(parent_ids)
            if not readable_parents:
                break
            ancestor_records |= readable_parents
            all_records |= readable_parents
            frontier = readable_parents

        if all_records:
            # 再次搜索，为客户端提供稳定的初始同级顺序，并在序列化前重新应用记录规则。
            all_records = self.search(
                [("id", "in", all_records.ids)],
                order=order,
                limit=max_nodes + 1,
            )
        if len(all_records) > max_nodes:
            _treegrid_raise_too_many_nodes(self, max_nodes)

        returned_ids = set(all_records.ids)
        matched_id_set = set(matching_records.ids)
        ancestor_id_set = set(ancestor_records.ids)
        matched_ids = [
            record_id
            for record_id in matching_records.ids
            if record_id in returned_ids
        ]
        ancestor_ids = [
            record.id
            for record in all_records
            if record.id in ancestor_id_set and record.id not in matched_id_set
        ]
        records = all_records.web_read(read_specification)
        orphan_ids = []
        for values in records:
            parent_value = values.get(parent_name)
            if isinstance(parent_value, dict):
                parent_id = parent_value.get("id")
            elif isinstance(parent_value, (tuple, list)):
                parent_id = parent_value[0] if parent_value else False
            else:
                parent_id = parent_value
            if parent_id and parent_id not in returned_ids:
                # ``web_read`` 会以提升后的权限取得 Many2one 显示名。不得泄露已归档或
                # 被记录规则隐藏、且已明确排除在返回树之外的祖先。
                values[parent_name] = False
                orphan_ids.append(values["id"])
        return {
            "records": records,
            "length": len(records),
            "matched_ids": matched_ids,
            "ancestor_ids": ancestor_ids,
            "orphan_ids": orphan_ids,
            "parent_field": parent_name,
            "sequence_field": sequence_name,
            "max_nodes": max_nodes,
        }

    @api.model
    def occ_treegrid_resequence(self, moved_id, target_id, position):
        """将节点移到同级节点前后，并重新规范同级排序值。"""
        parent_name, sequence_name, max_nodes = _treegrid_configuration(self)
        if position not in ("before", "after"):
            raise UserError(
                self.env._(
                    "TreeGrid 行只能移动到同级节点之前或之后。"
                )
            )

        moved_id = _treegrid_record_id(self, moved_id)
        target_id = _treegrid_record_id(self, target_id)
        if moved_id == target_id:
            raise UserError(self.env._("TreeGrid 行不能拖放到自身。"))

        TreeModel = self.with_context(active_test=False)
        TreeModel.browse().check_access("write")
        moved_and_target = TreeModel.search([("id", "in", [moved_id, target_id])])
        records_by_id = {record.id: record for record in moved_and_target}
        if moved_id not in records_by_id or target_id not in records_by_id:
            raise AccessError(
                self.env._("请求的 TreeGrid 记录不可用。")
            )
        moved_and_target.check_access("write")

        TreeModel.flush_model([parent_name, sequence_name])
        moved = TreeModel.browse(moved_id)
        target = TreeModel.browse(target_id)
        parent_id = moved[parent_name].id or False
        if parent_id != (target[parent_name].id or False):
            raise UserError(
                self.env._("TreeGrid 行只能在同一个父节点下排序。")
            )

        siblings = TreeModel.search(
            [(parent_name, "=", parent_id)],
            order=f"{sequence_name}, id",
            limit=max_nodes + 1,
        )
        if len(siblings) > max_nodes:
            _treegrid_raise_too_many_nodes(self, max_nodes)
        siblings.check_access("write")
        if moved_id not in siblings.ids or target_id not in siblings.ids:
            raise AccessError(
                self.env._("请求的 TreeGrid 同级节点集合不可用。")
            )

        # 对完整同级集合获取一次非阻塞锁。把锁放在保存点内，可在进程内调用方捕获异常时，
        # 同时释放已取得的部分锁并回滚排序值写入。
        with self.env.cr.savepoint():
            siblings.lock_for_update(allow_referencing=True)
            siblings.invalidate_recordset([parent_name, sequence_name], flush=False)
            moved_and_target.invalidate_recordset(
                [parent_name, sequence_name], flush=False
            )

            moved_parent_id = moved[parent_name].id or False
            target_parent_id = target[parent_name].id or False
            if moved_parent_id != parent_id or target_parent_id != parent_id:
                raise LockError(
                    self.env._(
                        "TreeGrid 层级在排序过程中发生了变化，请刷新后重试。"
                    )
                )

            refreshed_siblings = TreeModel.search(
                [(parent_name, "=", parent_id)],
                order=f"{sequence_name}, id",
                limit=max_nodes + 1,
            )
            if len(refreshed_siblings) > max_nodes:
                _treegrid_raise_too_many_nodes(self, max_nodes)
            if set(refreshed_siblings.ids) != set(siblings.ids):
                raise LockError(
                    self.env._(
                        "TreeGrid 层级在排序过程中发生了变化，请刷新后重试。"
                    )
                )
            refreshed_siblings.check_access("write")

            ordered_ids = [
                record_id
                for record_id in refreshed_siblings.ids
                if record_id != moved_id
            ]
            target_index = ordered_ids.index(target_id)
            insertion_index = target_index + (position == "after")
            ordered_ids.insert(insertion_index, moved_id)

            for sequence, record_id in enumerate(ordered_ids, start=1):
                TreeModel.browse(record_id).write({sequence_name: sequence * 10})

        return {
            "moved_id": moved_id,
            "parent_id": parent_id,
            "ordered_ids": ordered_ids,
        }
