import logging
import re


_REDACTED = "[REDACTED]"

_INBOUND_SENSITIVE_QUERY = re.compile(
    r"(?P<prefix>[?&](?:code|state|token)=)[^&#\s\"']*",
    re.IGNORECASE,
)
_INBOUND_SENSITIVE_PATH = re.compile(
    r"/occ/wechat/(?:callback|email/verify)/?\?",
)

_WECHAT_API_SENSITIVE_QUERY = re.compile(
    r"(?P<prefix>[?&](?:secret|code|access_token|refresh_token)=)[^&#\s\"']*",
    re.IGNORECASE,
)
_WECHAT_API_HOST = re.compile(
    r"https://api\.weixin\.qq\.com(?::\d+)?",
    re.IGNORECASE,
)
_WECHAT_API_ENDPOINT = re.compile(
    r"/sns/(?:oauth2/access_token|userinfo)(?:\?|[\s\"'])",
    re.IGNORECASE,
)


def _redact_record(record, pattern):
    """Replace sensitive URL query values without dropping log metadata."""
    try:
        message = record.getMessage()
    except Exception:  # pragma: no cover - logging must never break the caller
        return True

    redacted = pattern.sub(lambda match: f"{match.group('prefix')}{_REDACTED}", message)
    if redacted != message:
        # Store the already formatted message so percent-encoded URLs cannot be
        # interpreted as logging placeholders on the second formatting pass.
        record.msg = redacted
        record.args = ()
    return True


class OccWechatWerkzeugFilter(logging.Filter):
    """Redact credentials from OdooCC callback and verification access logs."""

    marker = "occ_wechat_login.werkzeug_sensitive_query.v1"

    def filter(self, record):
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - logging must never break the caller
            return True
        if _INBOUND_SENSITIVE_PATH.search(message):
            return _redact_record(record, _INBOUND_SENSITIVE_QUERY)
        return True


class OccWechatUrllib3Filter(logging.Filter):
    """Redact credentials from urllib3's WeChat API request diagnostics."""

    marker = "occ_wechat_login.urllib3_sensitive_query.v1"

    def filter(self, record):
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - logging must never break the caller
            return True
        if _WECHAT_API_HOST.search(message) and _WECHAT_API_ENDPOINT.search(message):
            return _redact_record(record, _WECHAT_API_SENSITIVE_QUERY)
        return True


def _install_filter(logger_name, filter_class):
    logger = logging.getLogger(logger_name)
    marker = filter_class.marker
    if any(getattr(existing, "marker", None) == marker for existing in logger.filters):
        return
    logger.addFilter(filter_class())


def post_load():
    """Install process-wide, narrowly scoped log redaction filters once."""
    _install_filter("werkzeug", OccWechatWerkzeugFilter)
    # urllib3 emits request URLs from this child logger. A filter installed
    # only on its parent logger would not process propagated child records.
    _install_filter("urllib3.connectionpool", OccWechatUrllib3Filter)
