import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit

from odoo.tools.translate import LazyTranslate


BILIBILI_PLAYER_HOST = "player.bilibili.com"
BILIBILI_VIDEO_HOSTS = frozenset(
    {
        "bilibili.com",
        "www.bilibili.com",
        "m.bilibili.com",
    }
)
MAX_INPUT_LENGTH = 4096
MAX_PAGE = 10_000

_lt = LazyTranslate(__name__)

_BVID_RE = re.compile(r"^BV[A-Za-z0-9]{10}$")
_AID_RE = re.compile(r"^[1-9][0-9]*$")
_VIDEO_ID_RE = re.compile(r"^(?P<bvid>BV[A-Za-z0-9]{10})$|^(?:av)(?P<aid>[1-9][0-9]*)$", re.I)
_ALLOWED_IFRAME_ATTRIBUTES = frozenset(
    {
        "allowfullscreen",
        "border",
        "frameborder",
        "framespacing",
        "height",
        "scrolling",
        "src",
        "width",
    }
)
_ALLOWED_PLAYER_QUERY_KEYS = frozenset(
    {
        "aid",
        "autoplay",
        "bvid",
        "cid",
        "isoutside",
        "p",
        "page",
    }
)


@dataclass(frozen=True, slots=True)
class BilibiliVideo:
    """A normalized Bilibili player reference without remote metadata."""

    video_id: str
    page: int = 1

    def __post_init__(self):
        if not (_BVID_RE.fullmatch(self.video_id) or _AID_RE.fullmatch(self.video_id)):
            raise ValueError(_lt("B站视频号无效。"))
        if not isinstance(self.page, int) or isinstance(self.page, bool) or not 1 <= self.page <= MAX_PAGE:
            raise ValueError(_lt("B站视频分P必须是 1 到 10000 之间的整数。"))

    @property
    def id_parameter(self):
        return "bvid" if _BVID_RE.fullmatch(self.video_id) else "aid"

    @property
    def embed_url(self):
        query = urlencode(
            {
                self.id_parameter: self.video_id,
                "page": self.page,
                "autoplay": 0,
            }
        )
        return f"https://{BILIBILI_PLAYER_HOST}/player.html?{query}"

    def as_video_url_data(self):
        return {
            "platform": "bilibili",
            "embed_url": self.embed_url,
            "video_id": self.video_id,
            "params": {"page": self.page, "autoplay": 0},
        }


class _SingleIframeParser(HTMLParser):
    """Extract one inert iframe and reject all surrounding active markup."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.attributes = None
        self.claim_src = None
        self.closed = False
        self.invalid = False

    def handle_starttag(self, tag, attrs):
        if tag.casefold() != "iframe" or self.attributes is not None or self.closed:
            self.invalid = True
            return
        src_values = [
            value
            for name, value in attrs
            if name.casefold() == "src" and isinstance(value, str) and value.strip()
        ]
        if src_values:
            # Keep the declared authority for provider classification even
            # when another iframe attribute makes the embed itself invalid.
            self.claim_src = src_values[0].strip()
        names = [name.casefold() for name, _value in attrs]
        if len(names) != len(set(names)) or not set(names) <= _ALLOWED_IFRAME_ATTRIBUTES:
            self.invalid = True
            return
        self.attributes = {name.casefold(): value for name, value in attrs}

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if not self.invalid:
            self.closed = True

    def handle_endtag(self, tag):
        if tag.casefold() != "iframe" or self.attributes is None or self.closed:
            self.invalid = True
            return
        self.closed = True

    def handle_data(self, data):
        if data.strip():
            self.invalid = True

    def handle_comment(self, _data):
        self.invalid = True

    def handle_decl(self, _decl):
        self.invalid = True


def _extract_iframe_src(value):
    if not value.lstrip().lower().startswith("<iframe"):
        return None
    parser = _SingleIframeParser()
    try:
        parser.feed(value)
        parser.close()
    except (UnicodeError, ValueError):
        return False
    if parser.invalid or not parser.closed or parser.attributes is None:
        return False
    src = parser.attributes.get("src")
    return src.strip() if isinstance(src, str) and src.strip() else False


def _normalize_url(value):
    if value.startswith("//"):
        value = f"https:{value}"
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (UnicodeError, ValueError):
        return None
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.fragment
    ):
        return None
    return parsed


def _parse_query(query, allowed_keys):
    try:
        pairs = parse_qsl(
            query,
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=16,
        ) if query else []
    except ValueError:
        return None
    values = {}
    for key, value in pairs:
        normalized_key = key.casefold()
        if normalized_key not in allowed_keys or normalized_key in values:
            return None
        values[normalized_key] = value
    return values


def _parse_page(query_values):
    raw_page = query_values.get("page")
    raw_p = query_values.get("p")
    if raw_page is not None and raw_p is not None and raw_page != raw_p:
        return None
    value = raw_page if raw_page is not None else raw_p
    if value is None:
        return 1
    if not _AID_RE.fullmatch(value):
        return None
    page = int(value)
    return page if page <= MAX_PAGE else None


def _parse_video_page(parsed):
    if parsed.hostname.casefold() not in BILIBILI_VIDEO_HOSTS:
        return None
    match = re.fullmatch(r"/video/(?P<video_id>[^/]+)/?", parsed.path)
    if not match:
        return None
    video_id_match = _VIDEO_ID_RE.fullmatch(match.group("video_id"))
    if not video_id_match:
        return None
    query_values = _parse_query(parsed.query, frozenset({"p", "page"}))
    if query_values is None or (page := _parse_page(query_values)) is None:
        return None
    if bvid := video_id_match.group("bvid"):
        # The BV prefix is deliberately canonical and case-sensitive.
        if not _BVID_RE.fullmatch(bvid):
            return None
        video_id = bvid
    else:
        video_id = str(int(video_id_match.group("aid")))
    return BilibiliVideo(video_id=video_id, page=page)


def _parse_player(parsed):
    if parsed.hostname.casefold() != BILIBILI_PLAYER_HOST or parsed.path != "/player.html":
        return None
    query_values = _parse_query(parsed.query, _ALLOWED_PLAYER_QUERY_KEYS)
    if query_values is None or (page := _parse_page(query_values)) is None:
        return None

    bvid = query_values.get("bvid")
    aid = query_values.get("aid")
    cid = query_values.get("cid")
    autoplay = query_values.get("autoplay")
    is_outside = query_values.get("isoutside")
    if bvid is not None and not _BVID_RE.fullmatch(bvid):
        return None
    if aid is not None and not _AID_RE.fullmatch(aid):
        return None
    if cid is not None and not _AID_RE.fullmatch(cid):
        return None
    if autoplay is not None and autoplay != "0":
        return None
    if is_outside is not None and is_outside.casefold() not in {"0", "1", "false", "true"}:
        return None
    if not bvid and not aid:
        # A cid identifies media internals, not a stable public video.
        return None
    # Bilibili's official iframe commonly carries bvid, aid and cid together.
    # A valid bvid is the stable public identity, so prefer it and deliberately
    # discard the redundant aid/cid when producing the canonical URL.
    return BilibiliVideo(video_id=bvid or str(int(aid)), page=page)


def parse_bilibili_video(value, *, allow_bare_bvid=False):
    """Return a canonical Bilibili reference, or ``None`` for unsafe input.

    Parsing is intentionally offline and allowlist-based. It never follows a
    short link and never propagates arbitrary player parameters.
    """

    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > MAX_INPUT_LENGTH or any(ord(char) < 32 for char in value):
        return None

    iframe_src = _extract_iframe_src(value)
    if iframe_src is False:
        return None
    if iframe_src is not None:
        value = iframe_src

    video_id_match = _VIDEO_ID_RE.fullmatch(value)
    if video_id_match:
        if video_id_match.group("aid"):
            return BilibiliVideo(video_id=str(int(video_id_match.group("aid"))))
        if allow_bare_bvid and video_id_match.group("bvid"):
            return BilibiliVideo(video_id=video_id_match.group("bvid"))

    parsed = _normalize_url(value)
    if parsed is None:
        return None
    return _parse_video_page(parsed) or _parse_player(parsed)


def is_bilibili_video_input(value, *, allow_bare_bvid=False):
    """Identify input that claims to be Bilibili, including invalid forms."""

    if not isinstance(value, str):
        return False
    candidate = value.strip()
    if re.fullmatch(r"av[1-9][0-9]*", candidate, re.I) or (
        allow_bare_bvid and _BVID_RE.fullmatch(candidate)
    ):
        return True

    if candidate.lstrip().lower().startswith("<iframe"):
        parser = _SingleIframeParser()
        try:
            parser.feed(candidate)
            parser.close()
        except (UnicodeError, ValueError):
            return False
        if not parser.claim_src:
            return False
        candidate = parser.claim_src

    if candidate.startswith("//"):
        candidate = f"https:{candidate}"
    elif "://" not in candidate:
        # Recognize a scheme-less Bilibili authority as a claimed but invalid
        # URL. Do not reinterpret arbitrary paths or query values as hosts.
        candidate = f"https://{candidate}"
    try:
        hostname = urlsplit(candidate).hostname
    except (UnicodeError, ValueError):
        return False
    if not hostname:
        return False
    hostname = hostname.casefold().rstrip(".")
    wrapped_hostname = f".{hostname}."
    return (
        ".bilibili.com." in wrapped_hostname
        or ".b23.tv." in wrapped_hostname
    )


def get_bilibili_video_url_data(value, *, allow_bare_bvid=False):
    video = parse_bilibili_video(value, allow_bare_bvid=allow_bare_bvid)
    if video:
        return video.as_video_url_data()
    return {
        "error": True,
        "message": _lt("提供的B站视频地址无效或暂不支持。"),
    }
