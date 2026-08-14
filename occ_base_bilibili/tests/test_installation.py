from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestOccBaseBilibiliInstallation(TransactionCase):
    def test_module_is_installed(self):
        module = self.env["ir.module.module"].search(
            [("name", "=", "occ_base_bilibili")],
            limit=1,
        )

        self.assertTrue(module)
        self.assertEqual(module.state, "installed")

