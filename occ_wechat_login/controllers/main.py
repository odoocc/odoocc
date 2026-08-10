import logging
import secrets
import time
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit

from odoo import SUPERUSER_ID, _, http
from odoo.addons.base.models.ir_mail_server import MailDeliveryException
from odoo.addons.web.controllers.home import Home
from odoo.addons.web.controllers.utils import _get_login_redirect_url, ensure_db
from odoo.exceptions import AccessDenied, UserError, ValidationError
from odoo.http import request
from odoo.tools.misc import get_lang
from odoo.tools.translate import LazyTranslate

from ..const import (
    COMMUNITY_USERNAME_MAX_LENGTH,
    COMMUNITY_USERNAME_MIN_LENGTH,
    OCC_EMAIL_FROM,
    ONBOARDING_UI_LANGUAGE,
    WECHAT_LOGIN_GRANT_SESSION_KEY,
    WECHAT_LOGIN_STATE_LIMIT,
    WECHAT_LOGIN_STATE_SESSION_KEY,
    WECHAT_LOGIN_STATE_TTL_SECONDS,
    WECHAT_POST_LOGIN_REDIRECT_SESSION_KEY,
    WECHAT_USERNAME_SUGGESTION_SESSION_KEY,
)
from ..services import WeChatClient, WeChatLoginError


_logger = logging.getLogger(__name__)
_lt = LazyTranslate(__name__)


LOGIN_ERROR_MESSAGES = {
    "not_configured": _lt("WeChat login is not configured."),
    "state_invalid": _lt("The WeChat login request has expired. Please try again."),
    "authorization_failed": _lt("WeChat authorization failed. Please scan the code again."),
    "service_unavailable": _lt("WeChat login is temporarily unavailable. Please try again later."),
    "misconfigured": _lt("WeChat login is not configured correctly. Please contact the administrator."),
    "identity_unavailable": _lt("WeChat could not provide the account identity required for login."),
    "identity_mismatch": _lt("WeChat returned inconsistent account identity information."),
    "unionid_missing": _lt("This WeChat account has no available UnionID. Please contact the administrator."),
    "account_disabled": _lt("This account has been disabled. Please contact the administrator."),
    "login_failed": _lt("WeChat login failed. Please try again."),
}


def _safe_redirect(value, default="/odoo"):
    if not isinstance(value, str):
        return default
    value = value.strip()
    if not value or any(ord(character) < 32 or ord(character) == 127 for character in value):
        return default

    try:
        decoded_value = unquote(value)
        parsed = urlsplit(value)
        query_items = parse_qsl(parsed.query, keep_blank_values=True)
    except (UnicodeError, ValueError):
        return default

    # Only Web client targets are needed after login. Reject backslashes and
    # nested ``redirect`` parameters because browsers/Odoo may reinterpret
    # either form as a second, external redirect.
    valid_webclient_path = parsed.path == "/odoo" or parsed.path.startswith(
        "/odoo/"
    )
    path_segments = unquote(parsed.path).split("/")
    if (
        "\\" in value
        or "\\" in decoded_value
        or parsed.scheme
        or parsed.netloc
        or not valid_webclient_path
        or any(segment in {".", ".."} for segment in path_segments)
        or any(key.casefold() == "redirect" for key, _value in query_items)
    ):
        return default
    return value


def _with_private_headers(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _extend_csp_directive(response, directive, sources):
    """Add CSP sources without discarding policy supplied by Odoo or addons."""
    policy = response.headers.get("Content-Security-Policy", "")
    directives = [item.strip() for item in policy.split(";") if item.strip()]
    updated = False
    for index, item in enumerate(directives):
        parts = item.split()
        if parts and parts[0] == directive:
            current_sources = parts[1:]
            if "'none'" in current_sources and sources:
                current_sources.remove("'none'")
            directives[index] = " ".join(
                [directive]
                + current_sources
                + [source for source in sources if source not in current_sources]
            )
            updated = True
            break
    if not updated:
        directives.append(" ".join([directive, *sources]))
    response.headers["Content-Security-Policy"] = "; ".join(directives)
    return response


def _masked_email(email):
    local, separator, domain = (email or "").partition("@")
    if not separator:
        return "***"
    visible = local[:1]
    return f"{visible}{'*' * max(3, len(local) - 1)}@{domain}"


def _use_onboarding_language():
    """Render OCC account activation pages in Simplified Chinese.

    ``get_lang`` safely falls back to an installed request/company language
    when ``zh_CN`` is unavailable, so the module remains installable on a
    database that has not activated Simplified Chinese yet.
    """
    request.update_context(
        lang=get_lang(request.env, ONBOARDING_UI_LANGUAGE).code
    )


def _store_username_suggestion(user, nickname):
    request.session.pop(WECHAT_USERNAME_SUGGESTION_SESSION_KEY, None)
    suggestion = user._occ_community_username_suggestion(nickname)
    if suggestion:
        request.session[WECHAT_USERNAME_SUGGESTION_SESSION_KEY] = {
            "uid": user.id,
            "value": suggestion,
        }


def _get_username_suggestion(user):
    suggestion = request.session.get(WECHAT_USERNAME_SUGGESTION_SESSION_KEY)
    if (
        not isinstance(suggestion, dict)
        or suggestion.get("uid") != user.id
        or not isinstance(suggestion.get("value"), str)
    ):
        request.session.pop(WECHAT_USERNAME_SUGGESTION_SESSION_KEY, None)
        return ""
    return suggestion["value"]


def _issue_login_state(redirect=None):
    """Store and return a fresh session-bound, one-use QRConnect state."""
    now = int(time.time())
    states = request.session.get(WECHAT_LOGIN_STATE_SESSION_KEY) or []
    states = [
        state
        for state in states
        if isinstance(state, dict)
        and isinstance(state.get("issued_at"), int)
        and now - state["issued_at"] <= WECHAT_LOGIN_STATE_TTL_SECONDS
    ]
    nonce = secrets.token_urlsafe(32)
    states.append(
        {
            "nonce": nonce,
            "issued_at": now,
            "redirect": _safe_redirect(redirect),
        }
    )
    request.session[WECHAT_LOGIN_STATE_SESSION_KEY] = states[-WECHAT_LOGIN_STATE_LIMIT:]
    return nonce


class OccWechatHome(Home):
    @http.route()
    def web_login(self, *args, **kwargs):
        ensure_db()
        response = super().web_login(*args, **kwargs)
        if not getattr(response, "is_qweb", False):
            return response

        error_code = request.params.get("occ_wechat_error")
        if error_code in LOGIN_ERROR_MESSAGES:
            response.qcontext["error"] = LOGIN_ERROR_MESSAGES[error_code]

        config = request.env["res.config.settings"].sudo()._occ_wechat_get_config()
        if config["enabled"] and config["app_id"] and config["app_secret"]:
            redirect = _safe_redirect(request.params.get("redirect"))
            client = WeChatClient(config["app_id"], config["app_secret"])
            qr_state = _issue_login_state(redirect)
            response.qcontext["occ_wechat_qr_url"] = client.embedded_authorization_url(
                config["callback_url"], qr_state
            )
            response.qcontext["occ_wechat_auth_link"] = (
                "/occ/wechat/start?" + urlencode({"redirect": redirect})
            )
        else:
            response.qcontext["occ_wechat_qr_url"] = False
            response.qcontext["occ_wechat_auth_link"] = False
        response = _with_private_headers(response)
        response = _extend_csp_directive(
            response,
            "frame-src",
            [
                "'self'",
                "https://open.weixin.qq.com",
                "https://www.recaptcha.net",
                "https://www.google.com",
            ],
        )
        return response

    @http.route()
    def web_client(self, s_action=None, **kwargs):
        if request.session.uid:
            user = (
                request.env["res.users"]
                .sudo()
                .with_context(active_test=False)
                .browse(request.session.uid)
                .exists()
            )
            if user and user.active and user._occ_requires_email_verification():
                request.session[WECHAT_POST_LOGIN_REDIRECT_SESSION_KEY] = _safe_redirect(
                    request.httprequest.full_path
                )
                return request.redirect("/occ/wechat/email", 303)
        return super().web_client(s_action=s_action, **kwargs)


class OccWechatController(http.Controller):
    def _config(self):
        return request.env["res.config.settings"].sudo()._occ_wechat_get_config()

    def _login_error(self, code):
        safe_code = code if code in LOGIN_ERROR_MESSAGES else "login_failed"
        response = request.redirect(
            "/web/login?" + urlencode({"occ_wechat_error": safe_code}),
            303,
        )
        return _with_private_headers(response)

    def _consume_state(self, supplied_state):
        now = int(time.time())
        states = request.session.get(WECHAT_LOGIN_STATE_SESSION_KEY) or []
        remaining = []
        matched = None
        for state in states:
            if not isinstance(state, dict):
                continue
            nonce = state.get("nonce")
            issued_at = state.get("issued_at")
            if not isinstance(nonce, str) or not isinstance(issued_at, int):
                continue
            if now - issued_at > WECHAT_LOGIN_STATE_TTL_SECONDS:
                continue
            if (
                matched is None
                and isinstance(supplied_state, str)
                and secrets.compare_digest(nonce, supplied_state)
            ):
                matched = state
                continue
            remaining.append(state)
        request.session[WECHAT_LOGIN_STATE_SESSION_KEY] = remaining[-WECHAT_LOGIN_STATE_LIMIT:]
        return matched

    def _post_verification_redirect(self):
        redirect = request.session.pop(WECHAT_POST_LOGIN_REDIRECT_SESSION_KEY, None)
        return _safe_redirect(redirect)

    def _render(self, template, values, status=200):
        response = request.render(template, values, status=status)
        response = _with_private_headers(response)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
        return response

    @http.route(
        "/occ/wechat/start",
        type="http",
        auth="none",
        methods=["GET"],
        readonly=False,
        sitemap=False,
    )
    def wechat_start(self, redirect=None, **kwargs):
        ensure_db()
        if request.session.uid:
            return _with_private_headers(
                request.redirect(_safe_redirect(redirect), 303)
            )

        config = self._config()
        if not config["enabled"] or not config["app_id"] or not config["app_secret"]:
            return self._login_error("not_configured")

        nonce = _issue_login_state(redirect)

        client = WeChatClient(config["app_id"], config["app_secret"])
        response = request.redirect(
            client.authorization_url(config["callback_url"], nonce),
            303,
            local=False,
        )
        return _with_private_headers(response)

    @http.route(
        "/occ/wechat/callback",
        type="http",
        auth="none",
        methods=["GET"],
        readonly=False,
        sitemap=False,
    )
    def wechat_callback(self, code=None, state=None, **kwargs):
        ensure_db()
        login_state = self._consume_state(state)
        if not login_state or not isinstance(code, str) or not code or len(code) > 1024:
            return self._login_error("state_invalid")

        config = self._config()
        if not config["enabled"] or not config["app_id"] or not config["app_secret"]:
            return self._login_error("not_configured")

        try:
            identity = WeChatClient(
                config["app_id"], config["app_secret"]
            ).identity_from_code(code)
            # ``auth='none'`` has no default user/company. Updating the request
            # environment also updates the transaction default environment,
            # which Odoo uses while flushing delegated partner/avatar fields
            # during ``res.users.create()``.
            request.update_env(user=SUPERUSER_ID, su=True)
            user, created = request.env["res.users"].sudo()._occ_find_or_create_wechat_user(
                identity["unionid"],
                identity["openid"],
                identity.get("nickname"),
            )
            request.env.cr.commit()

            grant_token = secrets.token_urlsafe(32)
            request.session[WECHAT_LOGIN_GRANT_SESSION_KEY] = {
                "uid": user.id,
                "token": grant_token,
            }
            credential = {
                "login": user.login,
                "type": "occ_wechat",
                "token": grant_token,
            }
            auth_info = request.session.authenticate(request.env, credential)
            request.session.pop(WECHAT_LOGIN_GRANT_SESSION_KEY, None)
            if (
                user._occ_requires_email_verification()
                and not user.occ_pending_community_username
                and not user.occ_community_username
            ):
                _store_username_suggestion(user, identity.get("nickname"))
            else:
                request.session.pop(
                    WECHAT_USERNAME_SUGGESTION_SESSION_KEY, None
                )

            target = _safe_redirect(login_state.get("redirect"))
            if user._occ_requires_email_verification():
                request.session[WECHAT_POST_LOGIN_REDIRECT_SESSION_KEY] = target
                target = "/occ/wechat/email"
            response = request.redirect(
                _get_login_redirect_url(auth_info["uid"], target),
                303,
            )
            _logger.info(
                "OCC WeChat login succeeded for user id %s (%s)",
                user.id,
                "created" if created else "existing",
            )
            return _with_private_headers(response)
        except WeChatLoginError as error:
            _logger.warning("OCC WeChat API login failed with category %s", error.code)
            return self._login_error(error.code)
        except AccessDenied:
            request.session.pop(WECHAT_LOGIN_GRANT_SESSION_KEY, None)
            _logger.warning("OCC WeChat login denied")
            return self._login_error("account_disabled")
        except Exception:
            request.session.pop(WECHAT_LOGIN_GRANT_SESSION_KEY, None)
            _logger.exception("Unexpected OCC WeChat login failure")
            return self._login_error("login_failed")

    @http.route(
        "/occ/wechat/email",
        type="http",
        auth="user",
        methods=["GET", "POST"],
        readonly=False,
        website=True,
        multilang=False,
        sitemap=False,
    )
    def email_verification(self, email=None, community_username=None, **kwargs):
        _use_onboarding_language()
        user = request.env.user.sudo()
        if not user.occ_wechat_unionid or not user._occ_requires_email_verification():
            request.session.pop(WECHAT_USERNAME_SUGGESTION_SESSION_KEY, None)
            return _with_private_headers(
                request.redirect(self._post_verification_redirect(), 303)
            )

        error = None
        message = None
        mail_sent = False
        if request.httprequest.method == "POST":
            try:
                with request.env.cr.savepoint():
                    normalized_email, token = user._occ_prepare_email_verification(
                        email, community_username
                    )
                    base_url = (
                        request.env["ir.config_parameter"].sudo().get_base_url().rstrip("/")
                    )
                    verification_url = (
                        f"{base_url}/occ/wechat/email/verify?" + urlencode({"token": token})
                    )
                    template = request.env.ref(
                        "occ_wechat_login.mail_template_email_verification",
                        raise_if_not_found=False,
                    )
                    if not template:
                        raise UserError(_("The verification email template is missing."))
                    template.sudo().with_context(
                        verification_url=verification_url,
                        email_to=normalized_email,
                    ).send_mail(
                        user.id,
                        force_send=True,
                        raise_exception=True,
                        email_values={
                            "email_to": normalized_email,
                            "email_from": OCC_EMAIL_FROM,
                        },
                    )
                request.session.pop(WECHAT_USERNAME_SUGGESTION_SESSION_KEY, None)
                mail_sent = True
                message = _("A verification email has been sent. Please check your inbox.")
            except (ValidationError, UserError, MailDeliveryException) as exception:
                error = exception.args[0] if exception.args else _("Unable to send the verification email.")
            except Exception:
                _logger.exception("Unexpected OCC email verification send failure")
                error = _("Unable to send the verification email. Please try again later.")

        return self._render(
            "occ_wechat_login.email_page",
            {
                "error": error,
                "message": message,
                "pending_email": (
                    email
                    if error and request.httprequest.method == "POST"
                    else user.occ_pending_email
                ),
                "community_username": (
                    community_username
                    if error and request.httprequest.method == "POST"
                    else (
                        user.occ_pending_community_username
                        or user.occ_community_username
                        or _get_username_suggestion(user)
                    )
                ),
                "community_username_min_length": COMMUNITY_USERNAME_MIN_LENGTH,
                "community_username_max_length": COMMUNITY_USERNAME_MAX_LENGTH,
                "mail_sent": mail_sent,
                "next_url": "/odoo",
            },
        )

    @http.route(
        "/occ/wechat/email/verify",
        type="http",
        auth="public",
        methods=["GET", "POST"],
        readonly=False,
        website=True,
        multilang=False,
        sitemap=False,
    )
    def verify_email(self, token=None, **kwargs):
        _use_onboarding_language()
        users = request.env["res.users"].sudo()
        if request.httprequest.method == "GET":
            user = users._occ_get_email_verification_user(token)
            if not user:
                return self._render(
                    "occ_wechat_login.verify_confirm",
                    {
                        "token": False,
                        "masked_email": False,
                        "error": _("This verification link is invalid or has expired."),
                    },
                    status=400,
                )
            return self._render(
                "occ_wechat_login.verify_confirm",
                {
                    "token": token,
                    "masked_email": _masked_email(user.occ_pending_email),
                    "community_username": user.occ_pending_community_username,
                    "error": False,
                },
            )

        initial_password = None
        refreshed_session_token = None
        refreshed_session_login = None
        try:
            with request.env.cr.savepoint():
                user, initial_password = users._occ_confirm_email_verification(token)
                request.env.flush_all()
                if request.session.uid == user.id:
                    user.invalidate_recordset(["login", "password"])
                    refreshed_session_login = user.login
                    refreshed_session_token = user._compute_session_token(
                        request.session.sid
                    )
                if initial_password:
                    template = request.env.ref(
                        "occ_wechat_login.mail_template_initial_credentials",
                        raise_if_not_found=False,
                    )
                    if not template:
                        raise UserError(_("The initial password email template is missing."))
                    template.sudo().with_context(
                        initial_login=user.login,
                        initial_password=initial_password,
                        community_username=user.occ_community_username,
                    ).send_mail(
                        user.id,
                        force_send=True,
                        raise_exception=True,
                        email_values={
                            "email_to": user.occ_verified_email,
                            "email_from": OCC_EMAIL_FROM,
                        },
                    )
        except (ValidationError, UserError, MailDeliveryException) as exception:
            return self._render(
                "occ_wechat_login.verify_result",
                {
                    "success": False,
                    "message": exception.args[0],
                    "logged_in": bool(request.session.uid),
                },
                status=400,
            )
        except Exception:
            _logger.exception("Unexpected OCC email verification confirmation failure")
            return self._render(
                "occ_wechat_login.verify_result",
                {
                    "success": False,
                    "message": _("Unable to verify this email address. Please try again later."),
                    "logged_in": bool(request.session.uid),
                },
                status=500,
            )

        if request.session.uid == user.id:
            # Login and password are part of Odoo's session-token material.
            # Refresh the already authenticated WeChat session after changing
            # them without assigning session.uid directly.
            request.session.login = refreshed_session_login
            request.session.session_token = refreshed_session_token
            request.session.should_rotate = True
            return _with_private_headers(
                request.redirect(self._post_verification_redirect(), 303)
            )
        return self._render(
            "occ_wechat_login.verify_result",
            {
                "success": True,
                "message": (
                    _(
                        "Your email address has been verified. Your email is now your login, and the initial password has been sent to it."
                    )
                    if initial_password
                    else _(
                        "Your email address has been verified and is now your login. Your existing password has not changed."
                    )
                ),
                "logged_in": False,
            },
        )
