from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestOccWebsiteCnInstallation(TransactionCase):
    def test_module_is_installed(self):
        module = self.env["ir.module.module"].search(
            [("name", "=", "occ_website_cn")],
            limit=1,
        )

        self.assertTrue(module)
        self.assertEqual(module.state, "installed")

