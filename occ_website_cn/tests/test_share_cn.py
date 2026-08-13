from lxml import etree

from odoo.addons.http_routing.tests.common import MockRequest
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestShareCnTemplate(TransactionCase):
    def test_cn_and_native_share_templates_have_independent_contracts(self):
        coexistence_view = self.env["ir.ui.view"].create(
            {
                "name": "OdooCC Share Template Coexistence Test",
                "type": "qweb",
                "key": "occ_website_cn.test_share_template_coexistence",
                "arch": """
                    <div id="occ_website_cn_share_contract">
                        <t t-call="website.s_share"/>
                        <t t-call="occ_website_cn.s_share_cn"/>
                    </div>
                """,
            }
        )
        website = self.env.ref("website.default_website")

        with MockRequest(
            self.env,
            website=website,
            url_root="https://example.test/",
        ) as request:
            request.is_frontend = True
            request.is_frontend_multilang = True
            rendered = str(
                request.env["ir.qweb"]._render(
                    coexistence_view.id,
                    {
                        "_classes": "",
                        "_exclude_share_links": (),
                        "_link_classes": "",
                        "_no_title": False,
                    },
                )
            )

        document = etree.fromstring(rendered.encode())
        class_token = "contains(concat(' ', normalize-space(@class), ' '), ' %s ')"
        native_share = document.xpath(f".//*[{class_token % 's_share'}]")
        cn_share = document.xpath(f".//*[{class_token % 's_share_cn'}]")

        self.assertEqual(len(native_share), 1)
        self.assertEqual(len(cn_share), 1)
        self.assertTrue(
            native_share[0].xpath(f".//*[{class_token % 's_share_facebook'}]")
        )
        self.assertNotIn("s_share_cn", native_share[0].get("class", "").split())
        self.assertNotIn("s_share", cn_share[0].get("class", "").split())

        actions = cn_share[0].xpath(
            f".//*[{class_token % 's_share_cn_action'}][@data-platform]"
        )
        self.assertEqual(
            [action.get("data-platform") for action in actions],
            ["wechat", "qq", "qzone", "weibo", "copy"],
        )
