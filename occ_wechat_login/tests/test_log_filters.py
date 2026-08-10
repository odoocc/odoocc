import logging

from odoo.addons.occ_wechat_login.logging_filters import (
    OccWechatUrllib3Filter,
    OccWechatWerkzeugFilter,
    post_load,
)
from odoo.tests import BaseCase, tagged


def _record(name, message, args=()):
    return logging.LogRecord(name, logging.INFO, __file__, 1, message, args, None)


@tagged("post_install", "-at_install")
class TestOccWechatLogFilters(BaseCase):
    def test_werkzeug_filter_redacts_only_sensitive_occ_routes(self):
        callback = _record(
            "werkzeug",
            '"%s" %s %s',
            (
                "GET /occ/wechat/callback?code=wechat-code&state=session-state&safe=1 HTTP/1.1",
                "303",
                "-",
            ),
        )
        OccWechatWerkzeugFilter().filter(callback)
        message = callback.getMessage()
        self.assertNotIn("wechat-code", message)
        self.assertNotIn("session-state", message)
        self.assertIn("code=[REDACTED]", message)
        self.assertIn("state=[REDACTED]", message)
        self.assertIn("safe=1", message)

        verification = _record(
            "werkzeug",
            '"%s" %s %s',
            (
                "GET /occ/wechat/email/verify/?token=signed-email-token HTTP/1.1",
                "200",
                "-",
            ),
        )
        OccWechatWerkzeugFilter().filter(verification)
        self.assertNotIn("signed-email-token", verification.getMessage())
        self.assertIn("token=[REDACTED]", verification.getMessage())

        unrelated = _record(
            "werkzeug",
            '"%s" %s %s',
            ("GET /other/callback?code=keep-me HTTP/1.1", "200", "-"),
        )
        OccWechatWerkzeugFilter().filter(unrelated)
        self.assertIn("code=keep-me", unrelated.getMessage())

    def test_urllib3_filter_is_limited_to_wechat_api_endpoints(self):
        token_request = _record(
            "urllib3.connectionpool",
            '%s://%s:%s "%s %s %s" %s %s',
            (
                "https",
                "api.weixin.qq.com",
                443,
                "GET",
                "/sns/oauth2/access_token?appid=wx123&secret=app-secret&code=wechat-code",
                "HTTP/1.1",
                200,
                128,
            ),
        )
        OccWechatUrllib3Filter().filter(token_request)
        message = token_request.getMessage()
        self.assertNotIn("app-secret", message)
        self.assertNotIn("wechat-code", message)
        self.assertIn("appid=wx123", message)
        self.assertIn("secret=[REDACTED]", message)
        self.assertIn("code=[REDACTED]", message)

        profile_request = _record(
            "urllib3.connectionpool",
            '%s://%s:%s "%s %s %s" %s %s',
            (
                "https",
                "api.weixin.qq.com",
                443,
                "GET",
                "/sns/userinfo?access_token=access-value&refresh_token=refresh-value&openid=o1",
                "HTTP/1.1",
                200,
                64,
            ),
        )
        OccWechatUrllib3Filter().filter(profile_request)
        message = profile_request.getMessage()
        self.assertNotIn("access-value", message)
        self.assertNotIn("refresh-value", message)
        self.assertIn("openid=o1", message)

        other_host = _record(
            "urllib3.connectionpool",
            '%s://%s:%s "%s %s %s" %s %s',
            (
                "https",
                "example.com",
                443,
                "GET",
                "/sns/userinfo?access_token=keep-me",
                "HTTP/1.1",
                200,
                64,
            ),
        )
        OccWechatUrllib3Filter().filter(other_host)
        self.assertIn("access_token=keep-me", other_host.getMessage())

        other_endpoint = _record(
            "urllib3.connectionpool",
            '%s://%s:%s "%s %s %s" %s %s',
            (
                "https",
                "api.weixin.qq.com",
                443,
                "GET",
                "/cgi-bin/example?access_token=keep-me",
                "HTTP/1.1",
                200,
                64,
            ),
        )
        OccWechatUrllib3Filter().filter(other_endpoint)
        self.assertIn("access_token=keep-me", other_endpoint.getMessage())

    def test_post_load_installation_is_idempotent(self):
        post_load()
        post_load()

        cases = (
            ("werkzeug", OccWechatWerkzeugFilter.marker),
            ("urllib3.connectionpool", OccWechatUrllib3Filter.marker),
        )
        for logger_name, marker in cases:
            matching = [
                item
                for item in logging.getLogger(logger_name).filters
                if getattr(item, "marker", None) == marker
            ]
            self.assertEqual(len(matching), 1)
