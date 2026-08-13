from unittest.mock import MagicMock, patch

from odoo.addons.http_routing.tests.common import MockRequest
from odoo.tests import TransactionCase, tagged

from ..controllers.acceptance_demo import OccWebsiteCnAcceptanceDemo


@tagged("post_install", "-at_install")
class TestOccWebsiteCnAcceptanceDemo(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.controller = OccWebsiteCnAcceptanceDemo()
        cls.website = cls.env.ref("website.default_website")

    def test_demo_template_is_fixed_sanitized_and_covers_three_capabilities(self):
        view = self.env.ref("occ_website_cn_test.acceptance_demo")

        self.assertIn("BV1xx411c7mD", view.arch_db)
        self.assertIn("occ_website_cn.s_share_cn", view.arch_db)
        self.assertIn("ICP 与公安备案", view.arch_db)
        self.assertNotIn("b23.tv", view.arch_db)
        self.assertNotIn("appsecret", view.arch_db.casefold())

    def test_public_visitor_can_render_demo_for_cookie_acceptance(self):
        env = self.env(user=self.env.ref("base.public_user"))
        with MockRequest(env, website=self.website) as mock_request:
            response = MagicMock()
            response.headers = {}
            with patch.object(
                mock_request,
                "render",
                return_value=response,
            ) as render:
                result = type(self.controller).acceptance_demo.original_endpoint(
                    self.controller
                )

        self.assertIs(result, response)
        self.assertEqual(result.headers["X-Robots-Tag"], "noindex, nofollow")
        render.assert_called_once_with("occ_website_cn_test.acceptance_demo")

    def test_demo_route_is_public_get_only_and_not_in_sitemap(self):
        routing = type(self.controller).acceptance_demo.original_routing

        self.assertEqual(routing["auth"], "public")
        self.assertEqual(routing["methods"], ["GET"])
        self.assertIs(routing["sitemap"], False)
