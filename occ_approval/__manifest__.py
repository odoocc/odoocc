{
    "name": "OCC Approval",
    "version": "19.0.1.1.0",
    "category": "OCC/Operations",
    "summary": "Secure, versioned and visual approval workflows for Odoo",
    "description": """
OCC Approval provides a visual workflow designer, versioned workflow
definitions, strict server-side authorization, auditable approval instances,
multi-company isolation and reusable business-action adapters.
    """,
    "author": "OCC",
    "license": "LGPL-3",
    "depends": ["mail", "web"],
    "data": [
        "security/approval_groups.xml",
        "security/ir.model.access.csv",
        "security/approval_rules.xml",
        "data/ir_cron_data.xml",
        "views/approval_client_actions.xml",
        "views/approval_workflow_views.xml",
        "views/approval_role_views.xml",
        "views/approval_instance_views.xml",
        "views/res_users_views.xml",
        "views/approval_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "occ_approval/static/src/**/*.js",
            "occ_approval/static/src/**/*.xml",
            "occ_approval/static/src/**/*.scss",
        ],
        "web.assets_unit_tests": [
            "occ_approval/static/tests/**/*.js",
        ],
    },
    "application": True,
    "installable": True,
}
