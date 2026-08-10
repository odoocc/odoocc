import json
from urllib.parse import urlencode

import requests


class WeChatLoginError(Exception):
    """Safe, categorized error raised by the WeChat API adapter."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class WeChatClient:
    AUTHORIZATION_ENDPOINT = "https://open.weixin.qq.com/connect/qrconnect"
    TOKEN_ENDPOINT = "https://api.weixin.qq.com/sns/oauth2/access_token"
    USERINFO_ENDPOINT = "https://api.weixin.qq.com/sns/userinfo"
    TIMEOUT = (3.05, 10)

    def __init__(self, app_id, app_secret):
        self.app_id = app_id
        self.app_secret = app_secret

    def authorization_url(self, callback_url, state):
        query = urlencode(
            {
                "appid": self.app_id,
                "redirect_uri": callback_url,
                "response_type": "code",
                "scope": "snsapi_login",
                "state": state,
                "lang": "cn",
            }
        )
        return f"{self.AUTHORIZATION_ENDPOINT}?{query}#wechat_redirect"

    def embedded_authorization_url(self, callback_url, state):
        """Build the official QRConnect iframe URL used on Odoo's login page.

        ``self_redirect=false`` makes WeChat navigate the top-level window to
        the callback after confirmation. That preserves Odoo's SameSite=Lax
        session cookie, which would otherwise be omitted for a callback loaded
        inside a cross-site iframe.
        """
        query = urlencode(
            {
                "appid": self.app_id,
                "redirect_uri": callback_url,
                "response_type": "code",
                "scope": "snsapi_login",
                "state": state,
                "lang": "cn",
                "login_type": "jssdk",
                "self_redirect": "false",
            }
        )
        return f"{self.AUTHORIZATION_ENDPOINT}?{query}#wechat_redirect"

    def _get_json(self, endpoint, params, error_code):
        try:
            response = requests.get(
                endpoint,
                params=params,
                timeout=self.TIMEOUT,
                allow_redirects=False,
            )
        except requests.RequestException as error:
            raise WeChatLoginError("service_unavailable") from error
        if response.status_code != 200:
            raise WeChatLoginError("service_unavailable")
        try:
            # WeChat may return UTF-8 JSON as ``text/plain`` without a
            # charset. Requests then defaults to ISO-8859-1 and corrupts
            # Chinese text before ``Response.json()`` parses it. Decode the
            # raw response with WeChat's documented encoding instead.
            payload = json.loads(response.content.decode("utf-8-sig"))
        except (TypeError, ValueError) as error:
            raise WeChatLoginError("service_unavailable") from error
        if not isinstance(payload, dict):
            raise WeChatLoginError("service_unavailable")
        if payload.get("errcode"):
            errcode = payload.get("errcode")
            if errcode in {40029, 40163}:
                raise WeChatLoginError("authorization_failed")
            if errcode in {40013, 40125}:
                raise WeChatLoginError("misconfigured")
            raise WeChatLoginError(error_code)
        return payload

    def identity_from_code(self, code):
        token_payload = self._get_json(
            self.TOKEN_ENDPOINT,
            {
                "appid": self.app_id,
                "secret": self.app_secret,
                "code": code,
                "grant_type": "authorization_code",
            },
            "authorization_failed",
        )
        access_token = token_payload.get("access_token")
        openid = token_payload.get("openid")
        if (
            not isinstance(access_token, str)
            or not access_token
            or not isinstance(openid, str)
            or not openid
        ):
            raise WeChatLoginError("authorization_failed")

        profile_payload = self._get_json(
            self.USERINFO_ENDPOINT,
            {
                "access_token": access_token,
                "openid": openid,
                "lang": "zh_CN",
            },
            "identity_unavailable",
        )
        profile_openid = profile_payload.get("openid")
        if not isinstance(profile_openid, str) or not profile_openid:
            raise WeChatLoginError("identity_unavailable")
        if profile_openid != openid:
            raise WeChatLoginError("identity_mismatch")

        token_unionid = token_payload.get("unionid")
        profile_unionid = profile_payload.get("unionid")
        if (
            not isinstance(token_unionid, str)
            or not token_unionid
            or not isinstance(profile_unionid, str)
            or not profile_unionid
        ):
            raise WeChatLoginError("unionid_missing")
        if token_unionid != profile_unionid:
            raise WeChatLoginError("identity_mismatch")

        return {
            "unionid": token_unionid,
            "openid": openid,
            "nickname": profile_payload.get("nickname") or None,
        }
