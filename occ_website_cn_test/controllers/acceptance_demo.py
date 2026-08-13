from odoo import http
from odoo.http import request


class OccWebsiteCnAcceptanceDemo(http.Controller):
    """Fixed public page used to exercise published-page privacy behavior."""

    @http.route(
        "/occ_website_cn_test/demo",
        type="http",
        auth="public",
        methods=["GET"],
        website=True,
        sitemap=False,
    )
    def acceptance_demo(self, **_kwargs):
        response = request.render("occ_website_cn_test.acceptance_demo")
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response
