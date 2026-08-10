from odoo import SUPERUSER_ID, api


WORKFLOW_USER_DOMAIN = (
    "['&', ('company_id', 'in', company_ids), '|', "
    "('state', '=', 'published'), '|', '|', "
    "('instance_ids.requester_id', '=', user.id), "
    "('instance_ids.participant_user_ids', 'in', user.id), "
    "('instance_ids.task_ids.user_id', '=', user.id)]"
)

VERSION_USER_DOMAIN = (
    "['&', ('company_id', 'in', company_ids), '|', "
    "('workflow_id.state', '=', 'published'), '|', '|', "
    "('instance_ids.requester_id', '=', user.id), "
    "('instance_ids.participant_user_ids', 'in', user.id), "
    "('instance_ids.task_ids.user_id', '=', user.id)]"
)

LEGACY_ACCESS_XMLIDS = (
    "occ_approval.access_occ_approval_instance",
    "occ_approval.access_occ_approval_instance_node",
)

LEGACY_CRON_XMLIDS = (
    "occ_approval.ir_cron_occ_auto_approval",
    "occ_approval.ir_cron_occ_reminder",
)

LEGACY_VIEW_XMLIDS = (
    "occ_approval.res_config_settings_view_form",
    "occ_approval.occ_approval_instance_list_view",
    "occ_approval.occ_approval_instance_form_view",
    "occ_approval.occ_approval_instance_search_view",
    "occ_approval.occ_approval_instance_node_form_view",
    "occ_approval.occ_approval_instance_node_list_view",
    "occ_approval.occ_approval_model_list_view",
    "occ_approval.occ_approval_model_form_view",
    "occ_approval.occ_approval_model_search_view",
    "occ_approval.occ_approval_res_users_list_view",
    "occ_approval.occ_approval_res_users_search_view",
    "occ_approval.occ_approval_groups_list_view",
    "occ_approval.occ_approval_groups_search_view",
    "occ_approval.occ_approval_category_list_view",
    "occ_approval.occ_approval_category_form_view",
    "occ_approval.occ_approval_category_search_view",
)

LEGACY_MENU_XMLIDS = (
    "occ_approval.menu_occ_approval_management",
    "occ_approval.menu_occ_approval_category",
    "occ_approval.menu_occ_approval_model",
    "occ_approval.menu_occ_approval_apprval",
    "occ_approval.menu_occ_approval_instance",
    "occ_approval.menu_occ_approval_structure",
    "occ_approval.menu_occ_approval_groups",
    "occ_approval.menu_occ_approval_users",
)


def _deactivate_legacy_metadata(cr):
    """Disable obsolete records without asking the new registry to validate them.

    In an in-place upgrade the old views still target the legacy model fields.  An
    ORM write on ``ir.ui.view`` validates their architecture against the newly
    registered models before changing ``active`` and therefore aborts the
    migration.  These are fixed, trusted table names and XML IDs, so a narrow SQL
    update is both deterministic and safe during the migration transaction.
    """
    targets = (
        ("ir.model.access", "ir_model_access", LEGACY_ACCESS_XMLIDS),
        ("ir.cron", "ir_cron", LEGACY_CRON_XMLIDS),
        ("ir.ui.view", "ir_ui_view", LEGACY_VIEW_XMLIDS),
        ("ir.ui.menu", "ir_ui_menu", LEGACY_MENU_XMLIDS),
    )
    for model_name, table_name, xmlids in targets:
        names = [xmlid.split(".", 1)[1] for xmlid in xmlids]
        cr.execute(
            f"""
            UPDATE {table_name} AS record
               SET active = FALSE
              FROM ir_model_data AS data
             WHERE data.module = 'occ_approval'
               AND data.model = %s
               AND data.name = ANY(%s)
               AND data.res_id = record.id
               AND record.active
            """,
            (model_name, names),
        )


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute(
        """
        UPDATE occ_approval_workflow_version
           SET checksum_schema = 1
         WHERE checksum_schema IS NULL
        """
    )
    cr.execute(
        """
        ALTER TABLE occ_approval_workflow_version
        ALTER COLUMN checksum_schema SET NOT NULL
        """
    )
    cr.execute(
        "DROP INDEX IF EXISTS occ_approval_v2_instance_active_source_workflow_unique"
    )
    env.ref("occ_approval.rule_approval_workflow_user").domain_force = (
        WORKFLOW_USER_DOMAIN
    )
    env.ref("occ_approval.rule_approval_workflow_version_user").domain_force = (
        VERSION_USER_DOMAIN
    )
    env["ir.model.data"].search(
        [
            ("module", "=", "occ_approval"),
            ("model", "=", "ir.rule"),
        ]
    ).write({"noupdate": False})
    _deactivate_legacy_metadata(cr)
