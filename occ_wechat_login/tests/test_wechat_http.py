"""HTTP flow tests for OCC WeChat login and email verification."""

import json
import re
from html import unescape
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import odoo.http

from odoo import Command
from odoo.exceptions import AccessDenied
from odoo.tests import HttpCase, tagged

from odoo.addons.mail.models.mail_template import MailTemplate
from odoo.addons.occ_wechat_login import const
from odoo.addons.occ_wechat_login.controllers.main import OccWechatController
from odoo.addons.occ_wechat_login.services import WeChatClient
from odoo.addons.occ_wechat_login.services import wechat_client as wechat_client_module


def _json_response(payload):
    response = Mock(status_code=200)
    response.content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    response.encoding = "ISO-8859-1"
    return response


@tagged("post_install", "-at_install")
class TestWechatHttp(HttpCase):
    """Exercise state-bound login, real sessions, CSRF forms and the web gate."""

    def setUp(self):
        super().setUp()
        self.authenticate(None, None)
        self.parameters = self.env["ir.config_parameter"].sudo()
        self.parameters.set_param("occ_wechat_login.enabled", "True")
        self.parameters.set_param("occ_wechat_login.app_id", "wx-http-test")
        self.parameters.set_param("occ_wechat_login.app_secret", "http-secret")
        self.parameters.set_param("occ_wechat_login.new_user_type", "internal")
        self.internal_group = self.env.ref("base.group_user")
        self.portal_group = self.env.ref("base.group_portal")

    def test_email_routes_initialize_website_context(self):
        """Login-layout pages must render when ``website`` is installed."""
        for endpoint in (
            OccWechatController.email_verification,
            OccWechatController.verify_email,
        ):
            routing = endpoint.original_routing
            self.assertTrue(routing["website"])
            self.assertFalse(routing["multilang"])

    def _start(self, redirect="/odoo"):
        response = self.url_open(
            "/occ/wechat/start",
            params={"redirect": redirect},
            allow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
        parsed = urlsplit(response.headers["Location"])
        self.assertEqual(
            f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
            WeChatClient.AUTHORIZATION_ENDPOINT,
        )
        self.assertEqual(parsed.fragment, "wechat_redirect")
        query = parse_qs(parsed.query)
        self.assertEqual(query["appid"], ["wx-http-test"])
        self.assertEqual(query["scope"], ["snsapi_login"])
        self.assertEqual(
            query["redirect_uri"], [f"{self.base_url()}/occ/wechat/callback"]
        )
        self.assertNotIn("http-secret", response.headers["Location"])
        return query["state"][0]

    def _wechat_responses(self, suffix="http", nickname=None):
        if nickname is None:
            nickname = f"HTTP User {suffix}"
        return [
            _json_response(
                {
                    "access_token": f"access-{suffix}",
                    "refresh_token": f"refresh-{suffix}",
                    "openid": f"openid-{suffix}",
                    "unionid": f"unionid-{suffix}",
                }
            ),
            _json_response(
                {
                    "openid": f"openid-{suffix}",
                    "unionid": f"unionid-{suffix}",
                    "nickname": nickname,
                }
            ),
        ]

    def _csrf(self, response):
        match = re.search(
            r'name=["\']csrf_token["\'][^>]*value=["\']([^"\']+)',
            response.text,
        )
        self.assertIsNotNone(match, response.text)
        return match.group(1)

    def _hidden_token(self, response):
        match = re.search(
            r'name=["\']token["\'][^>]*value=["\']([^"\']+)',
            response.text,
        )
        self.assertIsNotNone(match, response.text)
        return match.group(1)

    def _input_value(self, response, name):
        input_tag = re.search(
            rf'<input\b[^>]*\bname=["\']{re.escape(name)}["\'][^>]*>',
            response.text,
        )
        self.assertIsNotNone(input_tag, response.text)
        value = re.search(r'\bvalue=["\']([^"\']*)', input_tag.group(0))
        return unescape(value.group(1)) if value else ""

    def _embedded_qr_url(self, response):
        iframe = re.search(
            r'<iframe\b[^>]*\bid=["\']occ_wechat_qr_frame["\'][^>]*>',
            response.text,
        )
        self.assertIsNotNone(iframe, response.text)
        source = re.search(r'\bsrc=["\']([^"\']+)', iframe.group(0))
        self.assertIsNotNone(source, iframe.group(0))
        return unescape(source.group(1))

    def _csp_directives(self, response):
        policy = response.headers.get("Content-Security-Policy")
        self.assertTrue(policy, response.headers)
        directives = {}
        for directive in policy.split(";"):
            parts = directive.strip().split()
            if parts:
                directives[parts[0]] = parts[1:]
        return directives

    def _assert_unframeable(self, response):
        self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(
            self._csp_directives(response).get("frame-ancestors"), ["'none'"]
        )

    def _session_from_cookie(self):
        sid = self.opener.cookies.get("session_id")
        self.assertTrue(sid)
        return odoo.http.root.session_store.get(sid)

    def _new_user(self, login, *, unionid=False, verified=False):
        values = {
            "name": login,
            "login": login,
            "password": "test-password",
            "group_ids": [Command.set([self.internal_group.id])],
        }
        if unionid:
            values.update(
                {
                    "occ_wechat_unionid": unionid,
                    "occ_wechat_openid": f"openid-{unionid}",
                }
            )
        if verified:
            values.update(
                {
                    "email": f"{login}@example.com",
                    "occ_verified_email": f"{login}@example.com",
                    "occ_community_username": login,
                    "group_ids": [Command.set([self.internal_group.id])],
                }
            )
        return self.env["res.users"].with_context(no_reset_password=True).create(values)

    def _new_wechat_user(self, suffix):
        user, created = self.env["res.users"].sudo()._occ_find_or_create_wechat_user(
            f"unionid-{suffix}", f"openid-{suffix}", f"HTTP User {suffix}"
        )
        self.assertTrue(created)
        user.password = "test-password"
        return user

    def test_login_button_and_authorization_state_configuration(self):
        """The login button and QRConnect redirect require complete enabled config."""
        self.parameters.set_param("occ_wechat_login.enabled", "False")
        response = self.url_open("/web/login")
        self.assertNotIn("/occ/wechat/start", response.text)
        self.assertNotIn('id="occ_wechat_qr_frame"', response.text)

        self.parameters.set_param("occ_wechat_login.enabled", "True")
        self.parameters.set_param("occ_wechat_login.app_secret", "")
        response = self.url_open("/web/login")
        self.assertNotIn("/occ/wechat/start", response.text)
        self.assertNotIn('id="occ_wechat_qr_frame"', response.text)

        self.parameters.set_param("occ_wechat_login.app_secret", "http-secret")
        response = self.url_open("/web/login", params={"redirect": "/odoo/action-7"})
        self.assertIn("/occ/wechat/start", response.text)
        self.assertIn("o_occ_wechat_login", response.text)

        state = self._start("/odoo/action-7?view_type=list")
        self.assertGreaterEqual(len(state), 32)
        self.assertNotIn("action-7", state)

    def test_embedded_qr_keeps_password_form_and_uses_expiring_one_use_state(self):
        """The embedded QR uses the session state machinery without replacing passwords."""
        with patch(
            "odoo.addons.occ_wechat_login.controllers.main.time.time",
            return_value=1000,
        ):
            login_page = self.url_open(
                "/web/login", params={"redirect": "/odoo/action-embedded"}
            )

        self.assertRegex(login_page.text, r'<input\b[^>]*\bname=["\']login["\']')
        self.assertRegex(login_page.text, r'<input\b[^>]*\bname=["\']password["\']')
        self.assertIn("o_occ_login_split_page", login_page.text)
        qr_url = self._embedded_qr_url(login_page)
        parsed = urlsplit(qr_url)
        self.assertEqual(
            f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
            WeChatClient.AUTHORIZATION_ENDPOINT,
        )
        self.assertEqual(parsed.fragment, "wechat_redirect")
        query = parse_qs(parsed.query)
        self.assertEqual(query["appid"], ["wx-http-test"])
        self.assertEqual(query["scope"], ["snsapi_login"])
        self.assertEqual(query["login_type"], ["jssdk"])
        self.assertEqual(query["self_redirect"], ["false"])
        self.assertEqual(
            query["redirect_uri"], [f"{self.base_url()}/occ/wechat/callback"]
        )
        self.assertNotIn("http-secret", qr_url)
        self.assertIn(
            "https://open.weixin.qq.com",
            self._csp_directives(login_page).get("frame-src", []),
        )
        embedded_state = query["state"][0]
        self.assertGreaterEqual(len(embedded_state), 32)
        stored_states = self._session_from_cookie()[
            const.WECHAT_LOGIN_STATE_SESSION_KEY
        ]
        stored_state = next(
            state for state in stored_states if state["nonce"] == embedded_state
        )
        self.assertEqual(stored_state["redirect"], "/odoo/action-embedded")

        with (
            patch(
                "odoo.addons.occ_wechat_login.controllers.main.time.time",
                return_value=1001,
            ),
            patch.object(
                wechat_client_module.requests,
                "get",
                side_effect=self._wechat_responses("embedded"),
            ),
        ):
            callback = self.url_open(
                "/occ/wechat/callback",
                params={"code": "embedded-code", "state": embedded_state},
                allow_redirects=False,
            )
        self.assertEqual(callback.status_code, 303)
        self.assertURLEqual(callback.headers["Location"], "/occ/wechat/email")

        with patch.object(wechat_client_module.requests, "get") as mocked_get:
            replay = self.url_open(
                "/occ/wechat/callback",
                params={"code": "replayed-code", "state": embedded_state},
                allow_redirects=False,
            )
        self.assertIn("occ_wechat_error=state_invalid", replay.headers["Location"])
        mocked_get.assert_not_called()

        self.authenticate(None, None)
        with patch(
            "odoo.addons.occ_wechat_login.controllers.main.time.time",
            return_value=2000,
        ):
            expiring_page = self.url_open("/web/login")
        expiring_state = parse_qs(
            urlsplit(self._embedded_qr_url(expiring_page)).query
        )["state"][0]
        with (
            patch(
                "odoo.addons.occ_wechat_login.controllers.main.time.time",
                return_value=2000 + const.WECHAT_LOGIN_STATE_TTL_SECONDS + 1,
            ),
            patch.object(wechat_client_module.requests, "get") as mocked_get,
        ):
            expired = self.url_open(
                "/occ/wechat/callback",
                params={"code": "expired-code", "state": expiring_state},
                allow_redirects=False,
            )
        self.assertIn("occ_wechat_error=state_invalid", expired.headers["Location"])
        mocked_get.assert_not_called()

    def test_state_expiry_replay_limit_and_open_redirect_protection(self):
        """State is session-bound, expires, is one-use and retains at most five tabs."""
        with patch(
            "odoo.addons.occ_wechat_login.controllers.main.time.time",
            return_value=1000,
        ):
            expired_state = self._start("/odoo/action-1")
        with (
            patch(
                "odoo.addons.occ_wechat_login.controllers.main.time.time",
                return_value=1000 + const.WECHAT_LOGIN_STATE_TTL_SECONDS + 1,
            ),
            patch.object(wechat_client_module.requests, "get") as mocked_get,
        ):
            response = self.url_open(
                "/occ/wechat/callback",
                params={"code": "expired-code", "state": expired_state},
                allow_redirects=False,
            )
        self.assertEqual(response.status_code, 303)
        self.assertIn("occ_wechat_error=state_invalid", response.headers["Location"])
        mocked_get.assert_not_called()

        states = [self._start(f"/odoo/action-{index}") for index in range(6)]
        with patch.object(wechat_client_module.requests, "get") as mocked_get:
            response = self.url_open(
                "/occ/wechat/callback",
                params={"code": "evicted-code", "state": states[0]},
                allow_redirects=False,
            )
        self.assertIn("occ_wechat_error=state_invalid", response.headers["Location"])
        mocked_get.assert_not_called()

        valid_state = self._start("https://evil.example/phishing")
        sid_before = self.opener.cookies.get("session_id")
        captured_credentials = []
        original_authenticate = odoo.http.Session.authenticate

        def capture_authenticate(session, env, credential):
            captured_credentials.append(dict(credential))
            return original_authenticate(session, env, credential)

        with (
            patch.object(
                wechat_client_module.requests,
                "get",
                side_effect=self._wechat_responses("state"),
            ),
            patch.object(
                odoo.http.Session,
                "authenticate",
                new=capture_authenticate,
            ),
        ):
            response = self.url_open(
                "/occ/wechat/callback",
                params={"code": "valid-code", "state": valid_state},
                allow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertURLEqual(response.headers["Location"], "/occ/wechat/email")
        self.assertEqual(len(captured_credentials), 1)
        self.assertEqual(captured_credentials[0]["type"], "occ_wechat")
        self.assertTrue(captured_credentials[0]["token"])
        self.assertNotEqual(sid_before, self.opener.cookies.get("session_id"))
        persisted_session = self._session_from_cookie()
        self.assertNotIn(const.WECHAT_LOGIN_GRANT_SESSION_KEY, persisted_session)
        self.assertEqual(
            persisted_session[const.WECHAT_POST_LOGIN_REDIRECT_SESSION_KEY], "/odoo"
        )

        user = self.env["res.users"].with_context(active_test=False).search(
            [("occ_wechat_unionid", "=", "unionid-state")]
        )
        self.assertEqual(len(user), 1)
        self.assertEqual(user.group_ids, self.internal_group)
        self.assertNotIn("access-state", str(user.read()))
        self.assertNotIn("refresh-state", str(user.read()))

        with patch.object(wechat_client_module.requests, "get") as mocked_get:
            replay = self.url_open(
                "/occ/wechat/callback",
                params={"code": "valid-code", "state": valid_state},
                allow_redirects=False,
            )
        self.assertIn("occ_wechat_error=state_invalid", replay.headers["Location"])
        mocked_get.assert_not_called()

    def test_suspicious_redirect_spellings_are_normalized_before_state_storage(self):
        """Backslashes and nested external redirects must never survive in state."""
        suspicious_redirects = (
            r"/\evil.example",
            "/odoo?redirect=https://evil.example",
            "/%5C%5Cevil.example",
        )

        for redirect in suspicious_redirects:
            with self.subTest(redirect=redirect):
                state = self._start(redirect)
                session = self._session_from_cookie()
                stored_state = next(
                    item
                    for item in session[const.WECHAT_LOGIN_STATE_SESSION_KEY]
                    if item["nonce"] == state
                )
                self.assertEqual(stored_state["redirect"], "/odoo")

    def test_wechat_api_success_creates_user_and_disabled_binding_is_denied(self):
        """Callback creates once, reuses an active identity and rejects its archive."""
        state = self._start()
        with patch.object(
            wechat_client_module.requests,
            "get",
            side_effect=self._wechat_responses("account"),
        ):
            response = self.url_open(
                "/occ/wechat/callback",
                params={"code": "first-code", "state": state},
                allow_redirects=False,
            )
        self.assertURLEqual(response.headers["Location"], "/occ/wechat/email")
        user = self.env["res.users"].with_context(active_test=False).search(
            [("occ_wechat_unionid", "=", "unionid-account")]
        )
        self.assertEqual(len(user), 1)

        self.authenticate(None, None)
        self.parameters.set_param("occ_wechat_login.enabled", "True")
        self.parameters.set_param("occ_wechat_login.app_id", "wx-http-test")
        self.parameters.set_param("occ_wechat_login.app_secret", "http-secret")
        state = self._start()
        with patch.object(
            wechat_client_module.requests,
            "get",
            side_effect=self._wechat_responses("account"),
        ):
            self.url_open(
                "/occ/wechat/callback",
                params={"code": "second-code", "state": state},
                allow_redirects=False,
            )
        self.assertEqual(
            self.env["res.users"].with_context(active_test=False).search_count(
                [("occ_wechat_unionid", "=", "unionid-account")]
            ),
            1,
        )

        self.authenticate(None, None)
        user.active = False
        state = self._start()
        with patch.object(
            wechat_client_module.requests,
            "get",
            side_effect=self._wechat_responses("account"),
        ):
            denied = self.url_open(
                "/occ/wechat/callback",
                params={"code": "disabled-code", "state": state},
                allow_redirects=False,
            )
        self.assertIn("occ_wechat_error=account_disabled", denied.headers["Location"])
        self.assertEqual(
            self.env["res.users"].with_context(active_test=False).search_count(
                [("occ_wechat_unionid", "=", "unionid-account")]
            ),
            1,
        )

    def test_portal_configuration_callback_creates_portal_and_opens_email_page(self):
        """A portal callback authenticates the new user into the email guide."""
        self.parameters.set_param("occ_wechat_login.new_user_type", "portal")
        state = self._start()

        with patch.object(
            wechat_client_module.requests,
            "get",
            side_effect=self._wechat_responses("portal-account"),
        ):
            callback = self.url_open(
                "/occ/wechat/callback",
                params={"code": "portal-code", "state": state},
                allow_redirects=False,
            )

        self.assertEqual(callback.status_code, 303)
        self.assertURLEqual(callback.headers["Location"], "/occ/wechat/email")
        user = self.env["res.users"].with_context(active_test=False).search(
            [("occ_wechat_unionid", "=", "unionid-portal-account")]
        )
        self.assertEqual(len(user), 1)
        self.assertEqual(user.group_ids, self.portal_group)
        self.assertIn(self.portal_group, user.all_group_ids)
        self.assertNotIn(self.internal_group, user.all_group_ids)

        email_page = self.url_open("/occ/wechat/email", allow_redirects=False)
        self.assertEqual(email_page.status_code, 200)
        self.assertRegex(
            email_page.text,
            r'<input\b[^>]*\bname=["\']community_username["\']',
        )
        self.assertEqual(self._input_value(email_page, "community_username"), "")

    def test_new_user_email_page_prefills_valid_wechat_nickname(self):
        """A valid, available WeChat nickname is a session-only suggestion."""
        state = self._start()
        with patch.object(
            wechat_client_module.requests,
            "get",
            side_effect=self._wechat_responses(
                "nickname-suggestion",
                nickname="  Ｏｄｏｏ老赵１２  ",
            ),
        ):
            callback = self.url_open(
                "/occ/wechat/callback",
                params={"code": "nickname-code", "state": state},
                allow_redirects=False,
            )

        self.assertEqual(callback.status_code, 303)
        self.assertURLEqual(callback.headers["Location"], "/occ/wechat/email")
        page = self.url_open("/occ/wechat/email")
        self.assertEqual(
            self._input_value(page, "community_username"),
            "Odoo老赵12",
        )
        session = self._session_from_cookie()
        self.assertEqual(
            session[const.WECHAT_USERNAME_SUGGESTION_SESSION_KEY]["value"],
            "Odoo老赵12",
        )

        edited_username = "自定义名字12"

        def fake_send_mail(_template, _res_id, **_kwargs):
            return 1

        with patch.object(MailTemplate, "send_mail", new=fake_send_mail):
            sent = self.url_open(
                "/occ/wechat/email",
                data={
                    "csrf_token": self._csrf(page),
                    "email": "nickname-suggestion@example.com",
                    "community_username": edited_username,
                },
            )

        self.assertEqual(sent.status_code, 200)
        self.assertEqual(
            self._input_value(sent, "community_username"),
            edited_username,
        )
        self.assertNotIn(
            const.WECHAT_USERNAME_SUGGESTION_SESSION_KEY,
            self._session_from_cookie(),
        )
        user = self.env["res.users"].search(
            [("occ_wechat_unionid", "=", "unionid-nickname-suggestion")]
        )
        self.assertEqual(user.occ_pending_community_username, edited_username)

    def test_unverified_user_rescan_restores_wechat_nickname_suggestion(self):
        """A later scan still suggests the nickname until binding is started."""
        responses = self._wechat_responses(
            "nickname-rescan",
            nickname="微信新用12",
        )
        state = self._start()
        with patch.object(
            wechat_client_module.requests,
            "get",
            side_effect=responses,
        ):
            first_callback = self.url_open(
                "/occ/wechat/callback",
                params={"code": "first-nickname-code", "state": state},
                allow_redirects=False,
            )
        self.assertEqual(first_callback.status_code, 303)
        self.assertEqual(
            self._input_value(self.url_open("/occ/wechat/email"), "community_username"),
            "微信新用12",
        )

        self.authenticate(None, None)
        state = self._start()
        with patch.object(
            wechat_client_module.requests,
            "get",
            side_effect=self._wechat_responses(
                "nickname-rescan",
                nickname="微信新用12",
            ),
        ):
            second_callback = self.url_open(
                "/occ/wechat/callback",
                params={"code": "second-nickname-code", "state": state},
                allow_redirects=False,
            )

        self.assertEqual(second_callback.status_code, 303)
        self.assertEqual(
            self._input_value(self.url_open("/occ/wechat/email"), "community_username"),
            "微信新用12",
        )
        self.assertEqual(
            self.env["res.users"].with_context(active_test=False).search_count(
                [("occ_wechat_unionid", "=", "unionid-nickname-rescan")]
            ),
            1,
        )

    def test_email_form_confirmation_and_web_client_gate(self):
        """GET confirmation is inert; POST verifies without changing user type."""
        user = self._new_wechat_user("http-unverified")
        user.lang = "en_US"
        technical_login = user.login
        self.authenticate(technical_login, "test-password")
        self.opener.cookies.set("frontend_lang", "en_US")

        gated = self.url_open(
            "/odoo", params={"debug": "1"}, allow_redirects=False
        )
        self.assertEqual(gated.status_code, 303)
        self.assertURLEqual(gated.headers["Location"], "/occ/wechat/email")

        page = self.url_open("/occ/wechat/email")
        self.assertEqual(page.headers["Cache-Control"], "no-store")
        self.assertEqual(page.headers["Referrer-Policy"], "no-referrer")
        self._assert_unframeable(page)
        self.assertIn("验证您的邮箱地址", page.text)
        self.assertIn("社区用户名", page.text)
        self.assertIn("发送验证邮件", page.text)
        self.assertNotIn("Verify your email address", page.text)
        self.assertRegex(
            page.text,
            r'<input\b[^>]*\bname=["\']community_username["\']',
        )
        binding_form = re.search(
            r'<form\b[^>]*\baction=["\']/occ/wechat/email["\'][^>]*>',
            page.text,
        )
        self.assertIsNotNone(binding_form, page.text)
        self.assertRegex(
            binding_form.group(0),
            r'\baccept-charset=["\']UTF-8["\']',
        )
        csrf_token = self._csrf(page)
        sent_messages = []
        submitted_community_username = "  中文社区１２  "
        community_username = "中文社区12"

        def fake_send_mail(template, res_id, **kwargs):
            rendered = template._generate_template([res_id], ("body_html",))
            sent_messages.append(
                {
                    "template_id": template.id,
                    "context": dict(template.env.context),
                    "res_id": res_id,
                    "email_values": kwargs.get("email_values"),
                    "body_html": str(rendered[res_id]["body_html"]),
                }
            )
            return len(sent_messages)

        with patch.object(MailTemplate, "send_mail", new=fake_send_mail):
            sent = self.url_open(
                "/occ/wechat/email",
                data={
                    "csrf_token": csrf_token,
                    "email": "HTTP.Member@Example.COM",
                    "community_username": submitted_community_username,
                    "next": "/odoo",
                },
            )
            self.assertEqual(sent.status_code, 200)
            self._assert_unframeable(sent)
            self.assertIn("charset=utf-8", sent.headers["Content-Type"].lower())
            self.assertIn(community_username, sent.text)
            self.assertIn(community_username.encode("utf-8"), sent.content)
            self.assertNotIn(b"\xef\xbf\xbd", sent.content)
            self.assertEqual(len(sent_messages), 1)
            verification_message = sent_messages[0]
            self.assertEqual(
                verification_message["template_id"],
                self.env.ref(
                    "occ_wechat_login.mail_template_email_verification"
                ).id,
            )
            self.assertEqual(verification_message["res_id"], user.id)
            self.assertEqual(
                verification_message["email_values"],
                {
                    "email_to": "http.member@example.com",
                    "email_from": const.OCC_EMAIL_FROM,
                },
            )
            verification_url = verification_message["context"]["verification_url"]
            self.assertIn("/occ/wechat/email/verify?token=", verification_url)
            user.invalidate_recordset()
            self.assertFalse(user.email)
            self.assertEqual(user.occ_pending_email, "http.member@example.com")
            self.assertEqual(
                user.occ_pending_community_username, community_username
            )
            self.assertIn(self.internal_group, user.all_group_ids)
            self.assertNotIn(self.portal_group, user.all_group_ids)

            confirmation = self.url_open(verification_url)
            self.assertEqual(confirmation.status_code, 200)
            self._assert_unframeable(confirmation)
            self.assertIn("charset=utf-8", confirmation.headers["Content-Type"].lower())
            self.assertIn("确认邮箱验证", confirmation.text)
            self.assertIn("确认验证", confirmation.text)
            self.assertNotIn("Confirm email verification", confirmation.text)
            self.assertIn(community_username, confirmation.text)
            self.assertIn(
                community_username.encode("utf-8"), confirmation.content
            )
            self.assertNotIn(b"\xef\xbf\xbd", confirmation.content)
            self.assertIn('action="/occ/wechat/email/verify"', confirmation.text)
            user.invalidate_recordset()
            self.assertFalse(user.email, "GET must not confirm scanner-fetched links")
            verification_csrf = self._csrf(confirmation)
            form_token = self._hidden_token(confirmation)

            confirmed = self.url_open(
                "/occ/wechat/email/verify",
                data={"csrf_token": verification_csrf, "token": form_token},
                allow_redirects=False,
            )
        self.assertEqual(confirmed.status_code, 303)
        self.assertURLEqual(confirmed.headers["Location"], "/odoo?debug=1")
        self.assertEqual(len(sent_messages), 2)
        credentials_message = sent_messages[1]
        self.assertEqual(
            credentials_message["template_id"],
            self.env.ref(
                "occ_wechat_login.mail_template_initial_credentials"
            ).id,
        )
        self.assertEqual(credentials_message["res_id"], user.id)
        self.assertEqual(
            credentials_message["email_values"],
            {
                "email_to": "http.member@example.com",
                "email_from": const.OCC_EMAIL_FROM,
            },
        )
        credentials_context = credentials_message["context"]
        self.assertEqual(credentials_context["initial_login"], "http.member@example.com")
        self.assertEqual(
            credentials_context["community_username"], community_username
        )
        initial_password = credentials_context["initial_password"]
        self.assertTrue(initial_password)
        credentials_body = credentials_message["body_html"]
        self.assertIn(community_username, credentials_body)
        self.assertIn(
            community_username.encode("utf-8"), credentials_body.encode("utf-8")
        )
        self.assertNotIn(b"\xef\xbf\xbd", credentials_body.encode("utf-8"))
        user.invalidate_recordset()
        self.assertEqual(user.email, "http.member@example.com")
        self.assertEqual(user.occ_verified_email, user.email)
        self.assertEqual(user.login, user.email)
        self.assertNotEqual(user.login, technical_login)
        self.assertEqual(user.occ_community_username, community_username)
        self.assertEqual(
            user.occ_community_username_normalized, community_username
        )
        self.assertEqual(user.name, community_username)
        self.assertEqual(user.partner_id.name, community_username)
        self.assertEqual(str(user.signature), f"<div>{community_username}</div>")
        self.assertFalse(user.occ_pending_community_username)
        self.assertIn(self.internal_group, user.all_group_ids)
        self.assertNotIn(self.portal_group, user.all_group_ids)

        auth_info = self.env["res.users"].sudo().authenticate(
            {
                "type": "password",
                "login": user.login,
                "password": initial_password,
            },
            {"interactive": True},
        )
        self.assertEqual(auth_info["uid"], user.id)
        with self.assertRaises(AccessDenied):
            self.env["res.users"].sudo().authenticate(
                {
                    "type": "password",
                    "login": technical_login,
                    "password": initial_password,
                },
                {"interactive": True},
            )

        self.env.cr.execute(
            "SELECT password FROM res_users WHERE id = %s", [user.id]
        )
        (stored_password,) = self.env.cr.fetchone()
        self.assertNotEqual(stored_password, initial_password)
        self.assertNotIn(initial_password, stored_password)

        fresh_login_page = self.url_open("/web/login")
        replay = self.url_open(
            "/occ/wechat/email/verify",
            data={
                "csrf_token": self._csrf(fresh_login_page),
                "token": form_token,
            },
            allow_redirects=False,
        )
        self.assertEqual(replay.status_code, 400)
        self.assertIn("验证失败", replay.text)
        self.assertIn("该验证链接无效或已过期", replay.text)
        self.assertNotIn("Verification failed", replay.text)

        expired_link = self.url_open(verification_url)
        self.assertEqual(expired_link.status_code, 400)
        self._assert_unframeable(expired_link)
        self.assertIn("确认邮箱验证", expired_link.text)
        self.assertIn("该验证链接无效或已过期", expired_link.text)
        self.assertNotIn("Confirm email verification", expired_link.text)

        user.invalidate_recordset(["lang"])
        self.assertEqual(user.lang, "en_US")

        webclient = self.url_open("/odoo", allow_redirects=False)
        self.assertEqual(webclient.status_code, 200)

    def test_email_binding_form_rejects_invalid_and_duplicate_community_names(self):
        """The binding route validates the submitted username before sending mail."""
        owner = self._new_wechat_user("http-name-owner")
        _normalized_email, owner_token = owner._occ_prepare_email_verification(
            "http-name-owner@example.com", "CommunityName"
        )
        owner, _initial_password = self.env[
            "res.users"
        ].sudo()._occ_confirm_email_verification(owner_token)
        self.assertEqual(owner.occ_community_username_normalized, "communityname")

        claimant = self._new_wechat_user("http-name-claimant")
        self.authenticate(claimant.login, "test-password")
        page = self.url_open("/occ/wechat/email")
        csrf_token = self._csrf(page)

        with patch.object(MailTemplate, "send_mail") as mocked_send:
            invalid = self.url_open(
                "/occ/wechat/email",
                data={
                    "csrf_token": csrf_token,
                    "email": "http-name-claimant@example.com",
                    "community_username": "x",
                },
            )
            self.assertEqual(invalid.status_code, 200)
            self.assertIn("社区用户名长度必须为 2 到 32 个字符", invalid.text)
            mocked_send.assert_not_called()
            claimant.invalidate_recordset()
            self.assertFalse(claimant.occ_pending_email)
            self.assertFalse(claimant.occ_pending_community_username)

            duplicate = self.url_open(
                "/occ/wechat/email",
                data={
                    "csrf_token": csrf_token,
                    "email": "http-name-claimant@example.com",
                    "community_username": "ｃｏｍｍｕｎｉｔｙｎａｍｅ",
                },
            )
            self.assertEqual(duplicate.status_code, 200)
            self.assertIn("该社区用户名已被使用", duplicate.text)
            mocked_send.assert_not_called()
            claimant.invalidate_recordset()
            self.assertFalse(claimant.occ_pending_email)
            self.assertFalse(claimant.occ_pending_community_username)

    def test_web_client_gate_does_not_affect_normal_or_verified_users(self):
        """Only an unverified WeChat-linked internal user is redirected."""
        normal = self._new_user("http-normal")
        verified = self._new_user(
            "http-verified", unionid="unionid-http-verified", verified=True
        )

        self.authenticate(normal.login, "test-password")
        normal_response = self.url_open("/odoo", allow_redirects=False)
        self.assertEqual(normal_response.status_code, 200)

        self.authenticate(verified.login, "test-password")
        verified_response = self.url_open("/odoo", allow_redirects=False)
        self.assertEqual(verified_response.status_code, 200)
