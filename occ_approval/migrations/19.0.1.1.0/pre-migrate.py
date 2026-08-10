def migrate(cr, version):
    cr.execute("SELECT to_regclass('occ_approval_v2_instance')")
    if not cr.fetchone()[0]:
        return
    cr.execute(
        """
          SELECT source_model,
                 source_res_id,
                 array_agg(id ORDER BY id),
                 array_agg(DISTINCT company_id ORDER BY company_id)
            FROM occ_approval_v2_instance
           WHERE state IN ('draft', 'running', 'rework')
              OR (state = 'approved' AND execution_state IN ('pending', 'running', 'failed'))
        GROUP BY source_model, source_res_id
          HAVING count(*) > 1
        ORDER BY source_model, source_res_id
           LIMIT 10
        """
    )
    conflicts = cr.fetchall()
    if conflicts:
        details = "; ".join(
            f"source={model_name},{res_id}, companies={company_ids}, instances={ids}"
            for model_name, res_id, ids, company_ids in conflicts
        )
        raise RuntimeError(
            "OCC Approval now permits only one unfinished instance per source record. "
            "Cancel or complete the conflicting instances before upgrading: "
            f"{details}"
        )
    cr.execute(
        "DROP INDEX IF EXISTS occ_approval_v2_instance_active_source_unique"
    )
