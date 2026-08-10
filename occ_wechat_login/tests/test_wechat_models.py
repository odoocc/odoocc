"""Model and service tests for OCC WeChat authentication."""

import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import requests
from psycopg2 import IntegrityError

from odoo import Command, fields, tools
from odoo.exceptions import AccessDenied, AccessError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.occ_wechat_login.const import (
    EMAIL_VERIFICATION_COOLDOWN_SECONDS,
    EMAIL_VERIFICATION_SCOPE,
    EMAIL_VERIFICATION_WINDOW_LIMIT,
    EMAIL_VERIFICATION_WINDOW_SECONDS,
    INITIAL_PASSWORD_DIGITS,
    INITIAL_PASSWORD_LENGTH,
    INITIAL_PASSWORD_LOWERCASE,
    INITIAL_PASSWORD_SYMBOLS,
    INITIAL_PASSWORD_UPPERCASE,
    WECHAT_LOGIN_GRANT_SESSION_KEY,
)
from odoo.addons.occ_wechat_login.models import res_users as res_users_module
from odoo.addons.occ_wechat_login.services import WeChatClient, WeChatLoginError
from odoo.addons.occ_wechat_login.services import wechat_client as wechat_client_module


def _json_response(payload, status_code=200):
    """Return UTF-8 JSON with the misleading headers used by WeChat."""
    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    response.headers["Content-Type"] = "text/plain"
    response.encoding = "ISO-8859-1"
    return response


@tagged("post_install", "-at_install")
class TestWechatClient(TransactionCase):
    """Verify QRConnect URL generation and all remote API trust boundaries."""

    def test_authorization_url_contains_only_expected_parameters(self):
        """The authorization URL must use QRConnect and preserve callback encoding."""
        client = WeChatClient("wx-app-id", "top-secret")
        url = client.authorization_url(
            "https://odoocc.com/occ/wechat/callback", "state-value"
        )
        parsed = urlsplit(url)

        self.assertEqual(
            f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
            WeChatClient.AUTHORIZATION_ENDPOINT,
        )
        self.assertEqual(parsed.fragment, "wechat_redirect")
        self.assertEqual(
            parse_qs(parsed.query),
            {
                "appid": ["wx-app-id"],
                "redirect_uri": ["https://odoocc.com/occ/wechat/callback"],
                "response_type": ["code"],
                "scope": ["snsapi_login"],
                "state": ["state-value"],
                "lang": ["cn"],
            },
        )
        self.assertNotIn("top-secret", url)

    def test_identity_success_uses_unionid_and_does_not_store_tokens(self):
        """A successful exchange returns only stable identity information."""
        token_response = _json_response(
            {
                "access_token": "temporary-access-token",
                "refresh_token": "temporary-refresh-token",
                "openid": "openid-1",
                "unionid": "unionid-1",
            }
        )
        profile_response = _json_response(
            {
                "openid": "openid-1",
                "unionid": "unionid-1",
                "nickname": "Odoo老赵😀",
            }
        )

        with patch.object(
            wechat_client_module.requests,
            "get",
            side_effect=[token_response, profile_response],
        ) as mocked_get:
            identity = WeChatClient("wx-app-id", "app-secret").identity_from_code(
                "authorization-code"
            )

        self.assertEqual(
            identity,
            {
                "unionid": "unionid-1",
                "openid": "openid-1",
                "nickname": "Odoo老赵😀",
            },
        )
        self.assertNotIn("access_token", identity)
        self.assertNotIn("refresh_token", identity)
        self.assertEqual(mocked_get.call_count, 2)
        token_call, profile_call = mocked_get.call_args_list
        self.assertEqual(token_call.args[0], WeChatClient.TOKEN_ENDPOINT)
        self.assertEqual(token_call.kwargs["timeout"], WeChatClient.TIMEOUT)
        self.assertFalse(token_call.kwargs["allow_redirects"])
        self.assertEqual(profile_call.args[0], WeChatClient.USERINFO_ENDPOINT)
        self.assertEqual(
            profile_call.kwargs["params"],
            {
                "access_token": "temporary-access-token",
                "openid": "openid-1",
                "lang": "zh_CN",
            },
        )

    def test_identity_rejects_remote_failures_and_inconsistent_identity(self):
        """Timeouts, invalid payloads, missing UnionID and mismatches are categorized."""
        client = WeChatClient("wx-app-id", "app-secret")

        scenarios = [
            (
                [requests.Timeout("offline")],
                "service_unavailable",
            ),
            (
                [_json_response({}, status_code=503)],
                "service_unavailable",
            ),
            (
                [_json_response({"errcode": 40029})],
                "authorization_failed",
            ),
            (
                [_json_response({"errcode": 40125})],
                "misconfigured",
            ),
            (
                [
                    _json_response(
                        {
                            "access_token": "token",
                            "openid": "openid-1",
                            "unionid": "unionid-1",
                        }
                    ),
                    _json_response(
                        {
                            "openid": "openid-2",
                            "unionid": "unionid-1",
                        }
                    ),
                ],
                "identity_mismatch",
            ),
            (
                [
                    _json_response(
                        {
                            "access_token": "token",
                            "openid": "openid-1",
                            "unionid": "unionid-1",
                        }
                    ),
                    _json_response(
                        {
                            "openid": "openid-1",
                            "unionid": "unionid-2",
                        }
                    ),
                ],
                "identity_mismatch",
            ),
            (
                [
                    _json_response(
                        {"access_token": "token", "openid": "openid-1"}
                    ),
                    _json_response({"openid": "openid-1"}),
                ],
                "unionid_missing",
            ),
            (
                [
                    _json_response(
                        {"access_token": "token", "openid": "openid-1"}
                    ),
                    _json_response(
                        {
                            "openid": "openid-1",
                            "unionid": "unionid-1",
                        }
                    ),
                ],
                "unionid_missing",
            ),
            (
                [
                    _json_response(
                        {
                            "access_token": "token",
                            "openid": "openid-1",
                            "unionid": "unionid-1",
                        }
                    ),
                    _json_response({"openid": "openid-1"}),
                ],
                "unionid_missing",
            ),
            (
                [
                    _json_response(
                        {
                            "access_token": "token",
                            "openid": "openid-1",
                            "unionid": "unionid-1",
                        }
                    ),
                    _json_response({"unionid": "unionid-1"}),
                ],
                "identity_unavailable",
            ),
        ]
        invalid_json = requests.Response()
        invalid_json.status_code = 200
        invalid_json._content = b"<html>not JSON</html>"
        invalid_json.encoding = "ISO-8859-1"
        scenarios.append(([invalid_json], "service_unavailable"))
        invalid_utf8 = requests.Response()
        invalid_utf8.status_code = 200
        invalid_utf8._content = b'{"nickname":"\xff"}'
        invalid_utf8.encoding = "ISO-8859-1"
        scenarios.append(([invalid_utf8], "service_unavailable"))

        for mocked_responses, expected_code in scenarios:
            with self.subTest(expected_code=expected_code), patch.object(
                wechat_client_module.requests,
                "get",
                side_effect=mocked_responses,
            ):
                with self.assertRaises(WeChatLoginError) as raised:
                    client.identity_from_code("authorization-code")
                self.assertEqual(raised.exception.code, expected_code)


@tagged("post_install", "-at_install")
class TestWechatUsers(TransactionCase):
    """Verify UnionID binding, the one-use credential and email promotion."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Users = cls.env["res.users"].sudo()
        cls.internal_group = cls.env.ref("base.group_user")
        cls.portal_group = cls.env.ref("base.group_portal")

    def _new_wechat_user(self, suffix, nickname="WeChat Tester"):
        return self.Users._occ_find_or_create_wechat_user(
            f"unionid-{suffix}", f"openid-{suffix}", nickname
        )[0]

    def _prepare_token(self, user, email, community_username=None):
        community_username = community_username or f"member{user.id}"
        normalized_email, token = user._occ_prepare_email_verification(
            email, community_username
        )
        self.assertEqual(normalized_email, tools.email_normalize(email))
        return token

    def test_configuration_requires_credentials_and_builds_fixed_callback(self):
        """Enabled settings require both credentials and derive callback from base URL."""
        Settings = self.env["res.config.settings"].sudo()
        incomplete = Settings.create(
            {
                "occ_wechat_enabled": True,
                "occ_wechat_app_id": "wx-config-test",
                "occ_wechat_app_secret": False,
            }
        )
        with self.assertRaises(ValidationError):
            incomplete.set_values()

        parameters = self.env["ir.config_parameter"].sudo()
        parameters.set_param("web.base.url", "https://odoocc.com/")
        parameters.set_param("occ_wechat_login.enabled", "True")
        parameters.set_param("occ_wechat_login.app_id", " wx-config-test ")
        parameters.set_param("occ_wechat_login.app_secret", " config-secret ")
        parameters.set_param("occ_wechat_login.new_user_type", "portal")
        self.assertEqual(
            Settings._occ_wechat_get_config(),
            {
                "enabled": True,
                "app_id": "wx-config-test",
                "app_secret": "config-secret",
                "new_user_type": "portal",
                "callback_url": "https://odoocc.com/occ/wechat/callback",
            },
        )

        parameters.set_param("occ_wechat_login.new_user_type", "unsupported")
        self.assertEqual(Settings._occ_wechat_get_new_user_type(), "internal")
        parameters.set_param("occ_wechat_login.new_user_type", False)
        self.assertEqual(Settings._occ_wechat_get_new_user_type(), "internal")

    def test_find_or_create_binds_unionid_and_grants_configured_internal_group(self):
        """The default/internal option creates one internal user and reuses it."""
        self.env["ir.config_parameter"].sudo().set_param(
            "occ_wechat_login.new_user_type", "internal"
        )
        unionid = "unionid-create"
        user, created = self.Users._occ_find_or_create_wechat_user(
            unionid, "openid-old", "Initial Nickname"
        )

        self.assertTrue(created)
        self.assertEqual(user.name, "Initial Nickname")
        self.assertEqual(user.occ_wechat_unionid, unionid)
        self.assertEqual(user.occ_wechat_openid, "openid-old")
        self.assertEqual(user.lang, "zh_CN")
        self.assertEqual(
            user.login, self.Users._occ_wechat_login_for_unionid(unionid)
        )
        self.assertNotIn(unionid, user.login)
        self.assertEqual(user.group_ids, self.internal_group)
        self.assertIn(self.internal_group, user.all_group_ids)
        self.assertNotIn(self.portal_group, user.all_group_ids)
        self.assertTrue(user._occ_requires_email_verification())

        self.env["ir.config_parameter"].sudo().set_param(
            "occ_wechat_login.new_user_type", "portal"
        )
        user.lang = "en_US"
        same_user, created = self.Users._occ_find_or_create_wechat_user(
            unionid, "openid-new", "Changed Nickname"
        )
        self.assertFalse(created)
        self.assertEqual(same_user, user)
        self.assertEqual(same_user.name, "Initial Nickname")
        self.assertEqual(same_user.occ_wechat_openid, "openid-new")
        self.assertEqual(same_user.lang, "en_US")
        self.assertEqual(same_user.group_ids, self.internal_group)

    def test_portal_new_user_stays_portal_after_email_verification(self):
        """Email confirmation preserves the configured portal user type."""
        self.env["ir.config_parameter"].sudo().set_param(
            "occ_wechat_login.new_user_type", "portal"
        )
        user = self._new_wechat_user("portal-preserved")

        self.assertEqual(user.lang, "zh_CN")
        self.assertEqual(user.group_ids, self.portal_group)
        self.assertIn(self.portal_group, user.all_group_ids)
        self.assertNotIn(self.internal_group, user.all_group_ids)

        user.write({"email": "portal-changed@example.com"})
        self.assertEqual(user.group_ids, self.portal_group)
        self.assertIn(self.portal_group, user.all_group_ids)
        self.assertNotIn(self.internal_group, user.all_group_ids)

        token = self._prepare_token(
            user,
            "portal-preserved@example.com",
            "PortalPreserved",
        )
        confirmed, initial_password = self.Users._occ_confirm_email_verification(token)

        self.assertEqual(confirmed, user)
        self.assertTrue(initial_password)
        self.assertEqual(user.group_ids, self.portal_group)
        self.assertIn(self.portal_group, user.all_group_ids)
        self.assertNotIn(self.internal_group, user.all_group_ids)

    def test_unionid_is_unique_and_disabled_user_is_never_recreated(self):
        """The SQL identity invariant includes archived users."""
        user = self._new_wechat_user("disabled")
        user.active = False

        with self.assertRaises(AccessDenied):
            self.Users._occ_find_or_create_wechat_user(
                "unionid-disabled", "openid-retry", "Retry"
            )
        self.assertEqual(
            self.Users.with_context(active_test=False).search_count(
                [("occ_wechat_unionid", "=", "unionid-disabled")]
            ),
            1,
        )

        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.Users.with_context(no_reset_password=True).create(
                {
                    "name": "Duplicate UnionID",
                    "login": "duplicate-unionid@example.invalid",
                    "occ_wechat_unionid": "unionid-disabled",
                    "occ_wechat_openid": "openid-other",
                    "group_ids": [Command.set([self.internal_group.id])],
                }
            )

    def test_session_credential_is_interactive_session_bound_and_one_use(self):
        """Only the exact grant in the current interactive session authenticates."""
        user = self._new_wechat_user("credential")
        checked_user = user.with_user(user).sudo()
        credential = {
            "login": user.login,
            "type": "occ_wechat",
            "token": "one-time-token",
        }
        fake_request = SimpleNamespace(
            session={
                WECHAT_LOGIN_GRANT_SESSION_KEY: {
                    "uid": user.id,
                    "token": "one-time-token",
                }
            }
        )

        with patch.object(res_users_module, "request", fake_request):
            auth_info = checked_user._check_credentials(
                credential, {"interactive": True}
            )
            self.assertEqual(
                auth_info,
                {"uid": user.id, "auth_method": "occ_wechat", "mfa": "default"},
            )
            self.assertNotIn(WECHAT_LOGIN_GRANT_SESSION_KEY, fake_request.session)
            with self.assertRaises(AccessDenied):
                checked_user._check_credentials(credential, {"interactive": True})

        fake_request.session[WECHAT_LOGIN_GRANT_SESSION_KEY] = {
            "uid": user.id,
            "token": "one-time-token",
        }
        with patch.object(res_users_module, "request", fake_request):
            with self.assertRaises(AccessDenied):
                checked_user._check_credentials(
                    {**credential, "token": "forged-token"},
                    {"interactive": True},
                )
            self.assertNotIn(WECHAT_LOGIN_GRANT_SESSION_KEY, fake_request.session)

        fake_request.session[WECHAT_LOGIN_GRANT_SESSION_KEY] = {
            "uid": user.id,
            "token": "one-time-token",
        }
        with patch.object(res_users_module, "request", fake_request):
            with self.assertRaises(AccessDenied):
                checked_user._check_credentials(
                    credential, {"interactive": False}
                )
            self.assertIn(WECHAT_LOGIN_GRANT_SESSION_KEY, fake_request.session)

        self.assertIn("occ_wechat_unionid", user._get_session_token_fields())

    def test_signed_email_token_is_single_use_and_preserves_internal_user(self):
        """Confirmation writes the official email without changing user type."""
        user = self._new_wechat_user("verify")
        token = self._prepare_token(user, "Member.Name@Example.COM")

        self.assertFalse(user.email)
        self.assertEqual(user.occ_pending_email, tools.email_normalize("Member.Name@Example.COM"))
        self.assertEqual(self.Users._occ_get_email_verification_user(token), user)

        technical_login = user.login
        original_group_ids = user.group_ids
        confirmed, initial_password = self.Users._occ_confirm_email_verification(token)
        self.assertEqual(confirmed, user)
        self.assertEqual(user.email, tools.email_normalize("Member.Name@Example.COM"))
        self.assertEqual(user.occ_verified_email, user.email)
        self.assertEqual(user.login, user.email)
        self.assertNotEqual(user.login, technical_login)
        self.assertTrue(initial_password)
        self.assertFalse(user.occ_pending_email)
        self.assertFalse(user.occ_email_verification_nonce)
        self.assertTrue(user.occ_email_verified_at)
        self.assertEqual(user.group_ids, original_group_ids)
        self.assertIn(self.internal_group, user.all_group_ids)
        self.assertNotIn(self.portal_group, user.all_group_ids)
        self.assertFalse(user._occ_requires_email_verification())

        self.assertFalse(self.Users._occ_get_email_verification_user(token))
        with self.assertRaises(ValidationError):
            self.Users._occ_confirm_email_verification(token)

    def test_initial_credentials_replace_technical_login_and_are_not_plaintext(self):
        """First verification creates a usable password without retaining its plaintext."""
        user = self._new_wechat_user("initial-credentials")
        technical_login = user.login
        token = self._prepare_token(
            user,
            " Login.Member@Example.COM ",
            community_username="LoginMember",
        )

        confirmed, initial_password = self.Users._occ_confirm_email_verification(token)

        self.assertEqual(confirmed, user)
        self.assertTrue(initial_password)
        self.assertEqual(len(initial_password), INITIAL_PASSWORD_LENGTH)
        self.assertTrue(
            any(character in INITIAL_PASSWORD_LOWERCASE for character in initial_password)
        )
        self.assertTrue(
            any(character in INITIAL_PASSWORD_UPPERCASE for character in initial_password)
        )
        self.assertTrue(
            any(character in INITIAL_PASSWORD_DIGITS for character in initial_password)
        )
        self.assertTrue(
            any(character in INITIAL_PASSWORD_SYMBOLS for character in initial_password)
        )
        self.assertNotEqual(initial_password, technical_login)
        self.assertEqual(user.login, "login.member@example.com")
        self.assertFalse(
            self.Users.with_context(active_test=False).search(
                [("login", "=", technical_login)], limit=1
            )
        )
        auth_info = self.Users.authenticate(
            {
                "type": "password",
                "login": user.login,
                "password": initial_password,
            },
            {"interactive": True},
        )
        self.assertEqual(auth_info["uid"], user.id)
        self.assertEqual(auth_info["auth_method"], "password")
        with self.assertRaises(AccessDenied):
            self.Users.authenticate(
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
        self.assertTrue(stored_password)
        self.assertNotEqual(stored_password, initial_password)
        self.assertNotIn(initial_password, stored_password)
        self.assertNotEqual(
            self.Users._crypt_context().identify(stored_password), "plaintext"
        )

    def test_reverification_changes_login_without_issuing_another_password(self):
        """Only the first promotion from a technical login yields initial credentials."""
        user = self._new_wechat_user("repeat-credentials")
        first_token = self._prepare_token(
            user, "first-login@example.com", "RepeatMember"
        )
        _confirmed, initial_password = self.Users._occ_confirm_email_verification(
            first_token
        )
        self.assertTrue(initial_password)

        user.write({"email": "changed-before-reverify@example.com"})
        user.occ_email_verification_sent_at = fields.Datetime.now() - timedelta(
            seconds=EMAIL_VERIFICATION_COOLDOWN_SECONDS + 1
        )
        second_token = self._prepare_token(
            user, "second-login@example.com", "RepeatMember"
        )
        confirmed, repeated_password = self.Users._occ_confirm_email_verification(
            second_token
        )

        self.assertEqual(confirmed, user)
        self.assertFalse(repeated_password)
        self.assertEqual(user.login, "second-login@example.com")
        auth_info = self.Users.authenticate(
            {
                "type": "password",
                "login": user.login,
                "password": initial_password,
            },
            {"interactive": True},
        )
        self.assertEqual(auth_info["uid"], user.id)

    def test_community_username_nfkc_unicode_validation_and_promotion(self):
        """Usernames accept bounded Unicode letters/digits and canonical separators."""
        user = self._new_wechat_user("username-normalization")
        token = self._prepare_token(
            user,
            "unicode-name@example.com",
            "  Ａlice－１２  ",
        )
        self.assertEqual(user.occ_pending_community_username, "Alice-12")
        self.assertFalse(user.occ_community_username)

        confirmed, _initial_password = self.Users._occ_confirm_email_verification(
            token
        )
        self.assertEqual(confirmed.occ_community_username, "Alice-12")
        self.assertEqual(confirmed.occ_community_username_normalized, "alice-12")
        self.assertFalse(confirmed.occ_pending_community_username)
        self.assertEqual(confirmed.name, "Alice-12")
        self.assertEqual(confirmed.partner_id.name, "Alice-12")
        self.assertEqual(str(confirmed.signature), "<div>Alice-12</div>")

        confirmed.write({"occ_community_username": "Alice-Changed"})
        self.assertEqual(confirmed.occ_community_username, "Alice-Changed")
        self.assertEqual(confirmed.name, "Alice-Changed")
        self.assertEqual(confirmed.partner_id.name, "Alice-Changed")
        self.assertEqual(str(confirmed.signature), "<div>Alice-Changed</div>")

        chinese = self._new_wechat_user("username-chinese")
        chinese_token = self._prepare_token(
            chinese,
            "chinese-name@example.com",
            "  中文社区１２  ",
        )
        self.assertEqual(chinese.occ_pending_community_username, "中文社区12")
        chinese, _initial_password = self.Users._occ_confirm_email_verification(
            chinese_token
        )
        self.assertEqual(chinese.occ_community_username, "中文社区12")
        self.assertEqual(chinese.occ_community_username_normalized, "中文社区12")
        self.assertEqual(chinese.name, "中文社区12")
        self.assertEqual(chinese.partner_id.name, "中文社区12")
        self.assertEqual(str(chinese.signature), "<div>中文社区12</div>")

        minimum = self._new_wechat_user("username-minimum")
        self._prepare_token(minimum, "minimum-name@example.com", "用户")
        self.assertEqual(minimum.occ_pending_community_username, "用户")

        maximum = self._new_wechat_user("username-maximum")
        max_name = "界" * 32
        self._prepare_token(maximum, "maximum-name@example.com", max_name)
        self.assertEqual(maximum.occ_pending_community_username, max_name)

        invalid_names = (
            "A",
            "a" * 33,
            "_leading",
            "trailing-",
            "has space",
            "punctuation!",
            "用户🙂",
            "＜script＞",
        )
        for index, invalid_name in enumerate(invalid_names):
            invalid_user = self._new_wechat_user(f"username-invalid-{index}")
            with self.subTest(invalid_name=invalid_name), self.assertRaises(
                ValidationError
            ):
                invalid_user._occ_prepare_email_verification(
                    f"invalid-name-{index}@example.com", invalid_name
                )

    def test_wechat_nickname_username_suggestion_is_safe_and_available(self):
        """Only valid, unique WeChat nicknames are offered as usernames."""
        user = self._new_wechat_user("nickname-suggestion")
        self.assertEqual(
            user._occ_community_username_suggestion("  Ｏｄｏｏ老赵１２  "),
            "Odoo老赵12",
        )

        owner = self._new_wechat_user("nickname-owner")
        owner.write({"occ_community_username": "ExistingName"})
        self.assertFalse(
            user._occ_community_username_suggestion("ｅｘｉｓｔｉｎｇｎａｍｅ")
        )

        for nickname in (
            None,
            "",
            "A",
            "a" * 33,
            "WeChat User",
            "用户🙂",
            "_leading",
            "trailing-",
            "<script>",
        ):
            with self.subTest(nickname=nickname):
                self.assertFalse(
                    user._occ_community_username_suggestion(nickname)
                )

    def test_legacy_mojibake_display_name_is_repaired_from_verified_username(self):
        """Only provably corrupted WeChat display names are repaired."""
        user = self._new_wechat_user("legacy-display-name")
        user.write({"occ_community_username": "Odoo老赵"})
        mojibake_name = "Odoo老赵".encode("utf-8").decode("latin-1")
        user.partner_id.write({"name": mojibake_name})
        untouched = self._new_wechat_user("custom-display-name")
        untouched.write({"occ_community_username": "社区用户"})
        untouched.partner_id.write({"name": "Different\u0080manual name"})

        repaired = self.Users._occ_repair_legacy_mojibake_display_names()

        self.assertIn(user, repaired)
        self.assertEqual(user.name, "Odoo老赵")
        self.assertEqual(user.partner_id.name, "Odoo老赵")
        self.assertNotIn(untouched, repaired)
        self.assertEqual(untouched.name, "Different\u0080manual name")

    def test_community_username_casefold_duplicate_and_confirm_race_are_rejected(self):
        """NFKC/casefold uniqueness is checked before send, at confirm and in SQL."""
        owner = self._new_wechat_user("username-owner")
        owner_token = self._prepare_token(
            owner, "username-owner@example.com", "Ｎａｍｅ"
        )
        self.Users._occ_confirm_email_verification(owner_token)
        self.assertEqual(owner.occ_community_username_normalized, "name")

        duplicate = self._new_wechat_user("username-duplicate")
        with self.assertRaises(ValidationError):
            duplicate._occ_prepare_email_verification(
                "username-duplicate@example.com", "name"
            )

        racer = self._new_wechat_user("username-racer")
        racer_token = self._prepare_token(
            racer, "username-racer@example.com", "OtherName"
        )
        racer.occ_pending_community_username = "ＮＡＭＥ"
        with self.assertRaises(ValidationError):
            self.Users._occ_confirm_email_verification(racer_token)
        self.assertFalse(racer.occ_community_username)

        sql_racer = self._new_wechat_user("username-sql-racer")
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            sql_racer.write(
                {
                    "occ_community_username": "NAME",
                    "occ_community_username_normalized": "name",
                }
            )

    def test_tampered_expired_and_rotated_email_tokens_are_rejected(self):
        """Signature, expiry and current nonce must all match at confirmation time."""
        user = self._new_wechat_user("token-security")
        old_token = self._prepare_token(user, "old@example.com")

        tampered = old_token[:-1] + ("A" if old_token[-1] != "A" else "B")
        self.assertFalse(self.Users._occ_get_email_verification_user(tampered))
        with self.assertRaises(ValidationError):
            self.Users._occ_confirm_email_verification(tampered)

        expired_token = tools.hash_sign(
            self.env,
            EMAIL_VERIFICATION_SCOPE,
            [user.id, user.occ_email_verification_nonce],
            expiration=fields.Datetime.now() - timedelta(seconds=1),
        )
        self.assertFalse(self.Users._occ_get_email_verification_user(expired_token))

        user.occ_email_verification_sent_at = fields.Datetime.now() - timedelta(
            seconds=EMAIL_VERIFICATION_COOLDOWN_SECONDS + 1
        )
        new_token = self._prepare_token(user, "new@example.com")
        self.assertFalse(self.Users._occ_get_email_verification_user(old_token))
        self.assertEqual(self.Users._occ_get_email_verification_user(new_token), user)

    def test_email_duplicate_check_includes_inactive_users_and_is_rechecked(self):
        """No active or archived account may already own the candidate address."""
        inactive_owner = new_test_user(
            self.env,
            login="inactive-email-owner",
            email="claimed@example.com",
        )
        inactive_owner.active = False
        user = self._new_wechat_user("duplicate-inactive")
        with self.assertRaises(ValidationError):
            user._occ_prepare_email_verification(
                "CLAIMED@example.com", "claimed-member"
            )

        user = self._new_wechat_user("duplicate-race")
        token = self._prepare_token(user, "race@example.com")
        new_test_user(
            self.env,
            login="new-email-owner",
            email="race@example.com",
        )
        with self.assertRaises(ValidationError):
            self.Users._occ_confirm_email_verification(token)
        self.assertFalse(user.email)
        self.assertIn(self.internal_group, user.all_group_ids)

    def test_email_change_keeps_internal_access_and_requires_reverification(self):
        """A changed address stays pending and cannot become an official mail target."""
        user = self._new_wechat_user("change-email")
        token = self._prepare_token(user, "verified@example.com")
        self.Users._occ_confirm_email_verification(token)
        self.assertIn(self.internal_group, user.all_group_ids)
        original_login = user.login

        user.write({"email": "changed@example.com"})

        self.assertFalse(user.email)
        self.assertEqual(user.login, original_login)
        self.assertFalse(user.occ_verified_email)
        self.assertFalse(user.occ_email_verified_at)
        self.assertEqual(user.occ_pending_email, "changed@example.com")
        self.assertIn(self.internal_group, user.all_group_ids)
        self.assertNotIn(self.portal_group, user.all_group_ids)
        self.assertTrue(user.active)
        self.assertTrue(user._occ_requires_email_verification())

    def test_unverified_wechat_user_cannot_write_an_official_email_directly(self):
        """RPC/model writes stage an address until signed email confirmation."""
        user = self._new_wechat_user("direct-email-write")

        user.write(
            {
                "email": "Direct.Pending@Example.COM",
                "name": "Updated WeChat Name",
            }
        )

        self.assertFalse(user.email)
        self.assertEqual(user.occ_pending_email, "direct.pending@example.com")
        self.assertFalse(user.occ_verified_email)
        self.assertEqual(user.name, "Updated WeChat Name")
        self.assertIn(self.internal_group, user.all_group_ids)

    def test_regular_user_email_write_keeps_standard_odoo_behavior(self):
        """The WeChat safeguard must not intercept unrelated Odoo users."""
        user = new_test_user(
            self.env,
            login="regular-email-write",
            email=False,
        )

        user.write({"email": "regular.user@example.com"})

        self.assertEqual(user.email, "regular.user@example.com")
        self.assertFalse(user.occ_wechat_unionid)
        self.assertFalse(user.occ_pending_email)

    def test_wechat_user_can_stage_own_email_but_cannot_change_another_user(self):
        """Self-service email writes retain Odoo's original access boundary."""
        user = self._new_wechat_user("self-email-write")
        attacker = new_test_user(
            self.env,
            login="other-user-email-write",
            email=False,
            groups="base.group_user",
        )

        user.with_user(user).write({"email": "self.pending@example.com"})

        self.assertFalse(user.email)
        self.assertEqual(user.occ_pending_email, "self.pending@example.com")

        with self.assertRaises(AccessError):
            user.with_user(attacker).write({"email": "forbidden@example.com"})

        self.assertFalse(user.email)
        self.assertEqual(user.occ_pending_email, "self.pending@example.com")

    def test_client_context_cannot_bypass_verified_email_reset(self):
        """A JSON-forgeable truthy context value must not impersonate the sentinel."""
        user = self._new_wechat_user("forged-reset-context")
        token = self._prepare_token(user, "context-verified@example.com")
        self.Users._occ_confirm_email_verification(token)
        self.assertIn(self.internal_group, user.all_group_ids)

        user.with_context(occ_skip_email_verification_reset=True).write(
            {"email": "context-changed@example.com"}
        )

        self.assertFalse(user.email)
        self.assertEqual(user.occ_pending_email, "context-changed@example.com")
        self.assertFalse(user.occ_verified_email)
        self.assertFalse(user.occ_email_verified_at)
        self.assertIn(self.internal_group, user.all_group_ids)
        self.assertNotIn(self.portal_group, user.all_group_ids)
        self.assertTrue(user._occ_requires_email_verification())

    def test_email_format_cooldown_and_hourly_window_are_enforced(self):
        """Invalid addresses and excessive sends are rejected before mail delivery."""
        user = self._new_wechat_user("rate-limit")
        with self.assertRaises(ValidationError):
            user._occ_prepare_email_verification("not-an-email", "rate-member")

        self._prepare_token(user, "rate@example.com")
        with self.assertRaises(ValidationError):
            user._occ_prepare_email_verification("rate@example.com", "rate-member")

        user.write(
            {
                "occ_email_verification_sent_at": fields.Datetime.now()
                - timedelta(seconds=EMAIL_VERIFICATION_COOLDOWN_SECONDS + 1),
                "occ_email_send_window_start": fields.Datetime.now(),
                "occ_email_send_window_count": EMAIL_VERIFICATION_WINDOW_LIMIT,
            }
        )
        with self.assertRaises(ValidationError):
            user._occ_prepare_email_verification("rate@example.com", "rate-member")

        user.occ_email_send_window_start = fields.Datetime.now() - timedelta(
            seconds=EMAIL_VERIFICATION_WINDOW_SECONDS + 1
        )
        token = self._prepare_token(user, "rate@example.com")
        self.assertTrue(token)
        self.assertEqual(user.occ_email_send_window_count, 1)

    def test_prepare_email_verification_locks_user_for_rate_limit_update(self):
        """Preparing a token must serialize concurrent nonce and rate-limit updates."""
        user = self._new_wechat_user("prepare-lock")

        with patch.object(
            type(user), "lock_for_update", autospec=True
        ) as mocked_lock:
            token = self._prepare_token(user, "locked@example.com")

        self.assertTrue(token)
        mocked_lock.assert_called_once()
        lock_args, lock_kwargs = mocked_lock.call_args
        self.assertEqual(lock_args[0], user)
        self.assertTrue(lock_kwargs.get("allow_referencing"))
