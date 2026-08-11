"""Shared constants for OdooCC WeChat authentication and email verification."""

WECHAT_LOGIN_STATE_SESSION_KEY = "occ_wechat_login_states"
WECHAT_LOGIN_GRANT_SESSION_KEY = "occ_wechat_login_grant"
WECHAT_POST_LOGIN_REDIRECT_SESSION_KEY = "occ_wechat_post_login_redirect"
WECHAT_USERNAME_SUGGESTION_SESSION_KEY = "occ_wechat_username_suggestion"

# New WeChat accounts and the onboarding flow use Simplified Chinese by
# default. Existing users keep any language preference they choose later.
NEW_WECHAT_USER_LANGUAGE = "zh_CN"
ONBOARDING_UI_LANGUAGE = NEW_WECHAT_USER_LANGUAGE

NEW_USER_TYPE_INTERNAL = "internal"
NEW_USER_TYPE_PORTAL = "portal"
NEW_USER_TYPES = {NEW_USER_TYPE_INTERNAL, NEW_USER_TYPE_PORTAL}

WECHAT_LOGIN_STATE_TTL_SECONDS = 10 * 60
WECHAT_LOGIN_STATE_LIMIT = 5

EMAIL_VERIFICATION_SCOPE = "occ_wechat_email_verification"
EMAIL_VERIFICATION_EXPIRATION_HOURS = 24
EMAIL_VERIFICATION_COOLDOWN_SECONDS = 60
EMAIL_VERIFICATION_WINDOW_SECONDS = 60 * 60
EMAIL_VERIFICATION_WINDOW_LIMIT = 5

COMMUNITY_USERNAME_MIN_LENGTH = 2
COMMUNITY_USERNAME_MAX_LENGTH = 32

INITIAL_PASSWORD_LENGTH = 16
INITIAL_PASSWORD_LOWERCASE = "abcdefghijkmnopqrstuvwxyz"
INITIAL_PASSWORD_UPPERCASE = "ABCDEFGHJKLMNPQRSTUVWXYZ"
INITIAL_PASSWORD_DIGITS = "23456789"
INITIAL_PASSWORD_SYMBOLS = "!@#$%"
INITIAL_PASSWORD_ALPHABET = (
    INITIAL_PASSWORD_LOWERCASE
    + INITIAL_PASSWORD_UPPERCASE
    + INITIAL_PASSWORD_DIGITS
    + INITIAL_PASSWORD_SYMBOLS
)

# Verification and initial-credential messages are sent before the new user
# has a usable email address of their own. Keep a project-owned, explicit
# sender so Odoo never falls back to an empty From header.
OCC_EMAIL_FROM = "Odoo Chinese Community <odoocc@126.com>"

# Context values arrive from RPC as JSON-compatible data. An identity-checked
# object sentinel cannot be forged by a client and is therefore safe for the
# module's narrowly scoped email write during verification confirmation.
EMAIL_VERIFICATION_WRITE_SENTINEL = object()
