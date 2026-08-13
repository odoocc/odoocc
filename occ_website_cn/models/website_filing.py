import ipaddress
import re
from urllib.parse import urlsplit

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


DEFAULT_ICP_FILING_URL = "https://beian.miit.gov.cn/"
DEFAULT_PUBLIC_SECURITY_FILING_URL = "https://beian.mps.gov.cn/"
FILING_FIELDS = frozenset(
    {
        "occ_icp_filing_text",
        "occ_icp_filing_url",
        "occ_public_security_filing_text",
        "occ_public_security_filing_url",
    }
)

_HOST_LABEL_RE = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)


def _is_valid_hostname(hostname):
    """Return whether ``hostname`` is an unambiguous DNS name or IP address."""

    if ":" in hostname:
        try:
            ipaddress.IPv6Address(hostname)
        except ValueError:
            return False
        return True

    try:
        ascii_hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError:
        return False

    # A final dot is valid DNS notation. Empty intermediate labels are not.
    ascii_hostname = ascii_hostname.removesuffix(".")
    if not ascii_hostname or len(ascii_hostname) > 253:
        return False

    if re.fullmatch(r"[0-9.]+", ascii_hostname):
        try:
            ipaddress.IPv4Address(ascii_hostname)
        except ValueError:
            return False
        return True

    return all(
        _HOST_LABEL_RE.fullmatch(label)
        for label in ascii_hostname.split(".")
    )


def is_valid_filing_url(value):
    """Validate a filing link without following it or resolving its hostname."""

    if not value:
        return True
    if not isinstance(value, str) or value != value.strip() or "\\" in value:
        return False
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return False
    if any(character.isspace() for character in value):
        return False

    try:
        parsed = urlsplit(value)
        # Accessing ``port`` also rejects non-numeric and out-of-range ports.
        parsed.port
    except (UnicodeError, ValueError):
        return False

    return bool(
        parsed.scheme.casefold() in {"http", "https"}
        and parsed.netloc
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
        and _is_valid_hostname(parsed.hostname)
    )


class Website(models.Model):
    _inherit = "website"

    occ_icp_filing_text = fields.Char(
        string="ICP备案号",
        help="在网站页脚展示的 ICP 备案号；留空则不展示该项。",
    )
    occ_icp_filing_url = fields.Char(
        string="ICP备案链接",
        default=DEFAULT_ICP_FILING_URL,
        help="ICP 备案号的完整 HTTP(S) 链接；留空则只展示备案号文本。",
    )
    occ_public_security_filing_text = fields.Char(
        string="公安备案号",
        help="在网站页脚展示的公安机关互联网备案号；留空则不展示该项。",
    )
    occ_public_security_filing_url = fields.Char(
        string="公安备案链接",
        default=DEFAULT_PUBLIC_SECURITY_FILING_URL,
        help="公安备案号的完整 HTTP(S) 链接；留空则只展示备案号文本。",
    )

    @api.model_create_multi
    def create(self, vals_list):
        context_defaults = {
            field_name
            for field_name in FILING_FIELDS
            if f"default_{field_name}" in self.env.context
        }
        if not self.env.is_system() and (
            context_defaults or any(FILING_FIELDS.intersection(vals) for vals in vals_list)
        ):
            raise AccessError(_("只有系统管理员可以设置网站备案信息。"))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.is_system() and FILING_FIELDS.intersection(vals):
            raise AccessError(_("只有系统管理员可以设置网站备案信息。"))
        return super().write(vals)

    @api.constrains("occ_icp_filing_url", "occ_public_security_filing_url")
    def _check_occ_filing_urls(self):
        url_fields = (
            "occ_icp_filing_url",
            "occ_public_security_filing_url",
        )
        for website in self:
            for field_name in url_fields:
                if not is_valid_filing_url(website[field_name]):
                    raise ValidationError(
                        _(
                            "“%(field)s”必须留空或填写完整的 HTTP(S) 地址。"
                            "地址必须包含有效主机，且不能包含账号密码、"
                            "反斜杠、"
                            "控制字符或未编码的空白字符。",
                            field=website._fields[field_name].string,
                        )
                    )
