from lxml import etree

from odoo.addons.http_routing.tests.common import MockRequest
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged

from ..models.website_filing import (
    DEFAULT_ICP_FILING_URL,
    DEFAULT_PUBLIC_SECURITY_FILING_URL,
    is_valid_filing_url,
)


@tagged("post_install", "-at_install")
class TestWebsiteFiling(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Website = cls.env["website"]

    def _render_filing(self, website):
        with MockRequest(
            self.env,
            context={"lang": website.default_lang_id.code},
            website=website,
            url_root="https://example.test/",
        ) as request:
            request.is_frontend = True
            request.is_frontend_multilang = True
            return str(
                request.env["ir.qweb"]._render(
                    "occ_website_cn.website_filing"
                )
            )

    def _render_layout(self, website, **values):
        with MockRequest(
            self.env,
            context={"lang": website.default_lang_id.code},
            website=website,
            url_root="https://example.test/",
        ) as request:
            request.is_frontend = True
            request.is_frontend_multilang = True
            return str(
                request.env["ir.qweb"]._render(
                    "website.layout",
                    {
                        "main_object": self.env.ref("website.homepage"),
                        **values,
                    },
                )
            )

    def test_new_website_receives_official_default_links(self):
        website = self.Website.create({"name": "备案默认链接测试"})

        self.assertEqual(website.occ_icp_filing_url, DEFAULT_ICP_FILING_URL)
        self.assertEqual(
            website.occ_public_security_filing_url,
            DEFAULT_PUBLIC_SECURITY_FILING_URL,
        )

    def test_existing_default_website_received_defaults_on_install(self):
        website = self.env.ref("website.default_website")

        self.assertEqual(website.occ_icp_filing_url, DEFAULT_ICP_FILING_URL)
        self.assertEqual(
            website.occ_public_security_filing_url,
            DEFAULT_PUBLIC_SECURITY_FILING_URL,
        )

    def test_filing_values_are_isolated_per_website(self):
        website_a = self.Website.create({"name": "备案网站 A"})
        website_b = self.Website.create({"name": "备案网站 B"})
        website_a.write(
            {
                "occ_icp_filing_text": "鲁ICP备测试A号",
                "occ_icp_filing_url": "https://example.test/icp/a?from=footer#record",
            }
        )

        self.assertEqual(website_a.occ_icp_filing_text, "鲁ICP备测试A号")
        self.assertEqual(
            website_a.occ_icp_filing_url,
            "https://example.test/icp/a?from=footer#record",
        )
        self.assertFalse(website_b.occ_icp_filing_text)
        self.assertEqual(website_b.occ_icp_filing_url, DEFAULT_ICP_FILING_URL)

    def test_url_validator_allows_empty_and_complete_http_urls(self):
        valid_urls = (
            False,
            "",
            "http://example.test",
            "https://example.test:8443/filing?id=1#result",
            "https://例子.公司/备案",
            "https://[2001:db8::1]/filing",
        )

        for value in valid_urls:
            with self.subTest(value=value):
                self.assertTrue(is_valid_filing_url(value))

    def test_url_validator_rejects_unsafe_or_ambiguous_values(self):
        invalid_urls = (
            "/filing",
            "//example.test/filing",
            "javascript:alert(1)",
            "data:text/html,test",
            "ftp://example.test/filing",
            "https://user@example.test/filing",
            "https://user:password@example.test/filing",
            "https://example.test\\@evil.test/filing",
            "https://exa mple.test/filing",
            "https://example.test/filing\x00",
            "https://example.test:bad/filing",
            "https://example..test/filing",
            "https://999.999.999.999/filing",
        )

        for value in invalid_urls:
            with self.subTest(value=value):
                self.assertFalse(is_valid_filing_url(value))

    def test_constraint_allows_blank_url_but_rejects_non_http_url(self):
        website = self.Website.create({"name": "备案 URL 约束测试"})
        website.write(
            {
                "occ_icp_filing_text": "鲁ICP备测试号",
                "occ_icp_filing_url": False,
            }
        )
        self.assertFalse(website.occ_icp_filing_url)

        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            website.occ_icp_filing_url = "javascript:alert(1)"

    def test_settings_related_fields_write_selected_website(self):
        website_a = self.Website.create({"name": "备案设置网站 A"})
        website_b = self.Website.create({"name": "备案设置网站 B"})
        settings = self.env["res.config.settings"].create(
            {"website_id": website_a.id}
        )
        settings.write(
            {
                "occ_icp_filing_text": "鲁ICP备设置测试号",
                "occ_public_security_filing_text": "鲁公网安备设置测试号",
            }
        )

        self.assertEqual(website_a.occ_icp_filing_text, "鲁ICP备设置测试号")
        self.assertEqual(
            website_a.occ_public_security_filing_text,
            "鲁公网安备设置测试号",
        )
        self.assertFalse(website_b.occ_icp_filing_text)
        self.assertFalse(website_b.occ_public_security_filing_text)

    def test_website_designer_cannot_bypass_settings_to_write_filing_fields(self):
        designer = new_test_user(
            self.env,
            login="occ_website_cn_filing_designer",
            groups="website.group_website_designer",
        )
        website = self.Website.create({"name": "备案字段权限测试"})

        with self.assertRaises(AccessError), self.env.cr.savepoint():
            website.with_user(designer).write(
                {"occ_icp_filing_text": "不应写入的备案号"}
            )

        self.assertFalse(website.occ_icp_filing_text)

    def test_footer_renders_configured_items_and_escapes_text(self):
        website = self.Website.create(
            {
                "name": "备案页脚渲染测试",
                "occ_icp_filing_text": "鲁ICP备测试<script>号",
                "occ_icp_filing_url": "https://example.test/icp?id=1#record",
                "occ_public_security_filing_text": "鲁公网安备测试号",
                "occ_public_security_filing_url": False,
            }
        )
        document = etree.fromstring(self._render_filing(website).encode())

        self.assertEqual(document.get("aria-label"), "网站备案信息")
        icp_link = document.xpath(".//span[contains(@class, 'o_occ_icp_filing')]/a")
        self.assertEqual(len(icp_link), 1)
        self.assertEqual(
            icp_link[0].get("href"),
            "https://example.test/icp?id=1#record",
        )
        self.assertEqual(icp_link[0].get("rel"), "noopener noreferrer")
        self.assertIn("鲁ICP备测试<script>号", "".join(icp_link[0].itertext()))
        self.assertFalse(icp_link[0].xpath(".//script"))

        public_security_links = document.xpath(
            ".//span[contains(@class, 'o_occ_public_security_filing')]/a"
        )
        self.assertFalse(public_security_links)
        self.assertIn("鲁公网安备测试号", "".join(document.itertext()))

    def test_footer_is_absent_when_both_display_texts_are_blank(self):
        website = self.Website.create(
            {
                "name": "空备案页脚测试",
                "occ_icp_filing_text": "   ",
                "occ_public_security_filing_text": False,
            }
        )

        self.assertEqual(self._render_filing(website).strip(), "")

    def test_each_filing_item_can_render_independently(self):
        combinations = (
            ("鲁ICP备单项测试号", False, "o_occ_icp_filing"),
            (False, "鲁公网安备单项测试号", "o_occ_public_security_filing"),
        )
        for icp_text, public_security_text, expected_class in combinations:
            with self.subTest(expected_class=expected_class):
                website = self.Website.create(
                    {
                        "name": f"备案单项渲染 {expected_class}",
                        "occ_icp_filing_text": icp_text,
                        "occ_public_security_filing_text": public_security_text,
                    }
                )
                document = etree.fromstring(self._render_filing(website).encode())
                self.assertEqual(
                    len(document.xpath(f".//span[contains(@class, '{expected_class}')]")),
                    1,
                )
                self.assertNotIn("·", "".join(document.itertext()))

    def test_layout_inserts_filing_after_footer_content_before_copyright(self):
        layout_view = self.env.ref("occ_website_cn.layout_website_filing")
        arch = etree.fromstring(layout_view.arch_db)
        xpath_node = arch.xpath("./xpath")[0]

        self.assertEqual(
            xpath_node.get("expr"),
            "//footer[@id='bottom']/div[@id='footer']",
        )
        self.assertEqual(xpath_node.get("position"), "after")
        self.assertEqual(
            xpath_node.xpath("./t")[0].get("t-call"),
            "occ_website_cn.website_filing",
        )

        combined_layout = self.env.ref("website.layout").get_combined_arch()
        combined_document = etree.fromstring(combined_layout.encode())
        filing_call = combined_document.xpath(
            "//footer[@id='bottom']/t[@t-call='occ_website_cn.website_filing']"
        )
        self.assertEqual(len(filing_call), 1)
        self.assertEqual(filing_call[0].getparent().tag, "footer")

    def test_layout_keeps_filing_inside_all_footer_templates(self):
        footer_templates = (
            "website.footer_custom",
            "website.template_footer_descriptive",
        )
        for xmlid in footer_templates:
            with self.subTest(xmlid=xmlid):
                combined_arch = self.env.ref(xmlid).get_combined_arch()
                document = etree.fromstring(combined_arch.encode())
                filing_call = document.xpath(
                    "//footer[@id='bottom']/t[@t-call='occ_website_cn.website_filing']"
                )
                self.assertEqual(len(filing_call), 1)

    def test_footer_visibility_and_no_footer_conditions_wrap_filing(self):
        combined_arch = self.env.ref("website.layout").get_combined_arch()
        document = etree.fromstring(combined_arch.encode())
        footer = document.xpath("//footer[@id='bottom']")[0]
        filing_call = footer.xpath("./t[@t-call='occ_website_cn.website_filing']")

        self.assertEqual(len(filing_call), 1)
        self.assertEqual(footer.get("t-if"), "not no_footer")
        self.assertIn("footer_visible", footer.get("t-attf-class", ""))

    def test_filing_is_independent_from_copyright_template(self):
        layout_view = self.env.ref("occ_website_cn.layout_website_filing")
        no_copyright_view = self.env.ref("website.footer_no_copyright")

        self.assertNotIn("o_footer_copyright", layout_view.arch_db)
        self.assertIn("no_copyright", no_copyright_view.arch_db)

    def test_layout_runtime_visibility_contract(self):
        website = self.Website.create(
            {
                "name": "备案页脚运行时显隐测试",
                "occ_icp_filing_text": "鲁ICP备运行时测试号",
            }
        )

        visible = etree.HTML(self._render_layout(website))
        self.assertEqual(
            len(visible.xpath("//footer[@id='bottom']//*[@aria-label='网站备案信息']")),
            1,
        )
        self.assertEqual(
            len(visible.xpath("//footer[@id='bottom']/*[contains(@class, 'o_footer_copyright')]")),
            1,
        )

        no_footer = etree.HTML(self._render_layout(website, no_footer=True))
        self.assertFalse(no_footer.xpath("//footer[@id='bottom']"))
        self.assertFalse(no_footer.xpath("//*[@aria-label='网站备案信息']"))

        no_copyright = etree.HTML(self._render_layout(website, no_copyright=True))
        self.assertEqual(
            len(no_copyright.xpath("//footer[@id='bottom']//*[@aria-label='网站备案信息']")),
            1,
        )
        self.assertFalse(
            no_copyright.xpath("//footer[@id='bottom']/*[contains(@class, 'o_footer_copyright')]")
        )

    def test_page_footer_visible_false_hides_filing_at_runtime(self):
        website = self.Website.create(
            {
                "name": "页面级页脚隐藏测试",
                "occ_icp_filing_text": "鲁ICP备页面隐藏测试号",
            }
        )
        page = self.env["website.page"].create(
            {
                "name": "页面级页脚隐藏测试",
                "type": "qweb",
                "key": "occ_website_cn.test_page_footer_hidden",
                "url": "/occ-website-cn-test-page-footer-hidden",
                "arch": """
                    <t t-call="website.layout">
                        <main id="occ_website_cn_test_page_footer_hidden"/>
                    </t>
                """,
                "website_id": website.id,
                "footer_visible": False,
                "is_published": True,
            }
        )

        with MockRequest(
            self.env,
            context={"lang": website.default_lang_id.code},
            website=website,
            url_root="https://example.test/",
        ) as request:
            request.is_frontend = True
            request.is_frontend_multilang = True
            rendered = str(
                request.env["ir.qweb"]._render(
                    page.view_id.id,
                    {"main_object": page},
                )
            )

        document = etree.HTML(rendered)
        footer = document.xpath("//footer[@id='bottom']")[0]
        footer_classes = footer.get("class", "").split()
        filing = footer.xpath(".//*[@aria-label='网站备案信息']")

        self.assertIn("d-none", footer_classes)
        self.assertIn("o_snippet_invisible", footer_classes)
        self.assertEqual(footer.get("data-invisible"), "1")
        self.assertEqual(len(filing), 1)
