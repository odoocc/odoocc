import logging
import re
from html import escape

from lxml import html as lxml_html

from odoo import _, api, models
from odoo.exceptions import ValidationError
from odoo.tools import html_sanitize

from odoo.addons.occ_base_bilibili.services import (
    BilibiliVideo,
    parse_bilibili_video,
)

_logger = logging.getLogger(__name__)

EMOJI_PATTERN = re.compile(
    "[\U0001f600-\U0001f64f\U0001f300-\U0001f5ff\U0001f680-\U0001f6ff"
    "\U0001f1e0-\U0001f1ff\U00002702-\U000027b0\U0001f900-\U0001f9ff"
    "\U0001fa00-\U0001fa6f\U0001fa70-\U0001faff\U00002600-\U000026ff"
    "\U0000fe00-\U0000fe0f\U0000200d]+",
    flags=re.UNICODE,
)
BILIBILI_MARKER_PATTERN = re.compile(
    r"^\s*\{\{bilibili:(?P<video_id>BV[A-Za-z0-9]{10}|av[1-9][0-9]*)"
    r"(?:\|page=(?P<page>(?:[1-9][0-9]{0,3}|10000)))?\}\}\s*$",
    flags=re.MULTILINE,
)
STRIKETHROUGH_PATTERN = re.compile(r"~~(?P<text>[^~\n]+)~~")
MERMAID_FENCE_PATTERN = re.compile(
    r"^```mermaid[ \t]*\n(?P<source>.*?)[ \t]*\n```[ \t]*(?=\n|$)",
    flags=re.MULTILINE | re.DOTALL | re.IGNORECASE,
)
MERMAID_HEADER_PATTERN = re.compile(
    r"^flowchart[ \t]+(?:TD|TB|BT|LR|RL)\b", flags=re.IGNORECASE
)
MERMAID_FORBIDDEN_PATTERN = re.compile(
    r"(?:javascript:|<\s*script\b|^\s*click\b|^\s*%%\{)",
    flags=re.MULTILINE | re.IGNORECASE,
)
MERMAID_MAX_LENGTH = 50000
TOKEN_PREFIX = "OCCMARKDOWNPROTECTED"
ALLOWED_OPTIONS = frozenset({"strip_emoji", "create_toc", "allow_bilibili"})


class OccMarkdownService(models.AbstractModel):
    _name = "occ.markdown.service"
    _description = "OdooCC Markdown 转换服务"

    @api.model
    def convert_markdown(self, markdown_text, options=None):
        if not isinstance(markdown_text, str):
            raise ValidationError(_("Markdown 内容必须是文本。"))
        options = self._validate_options(options)
        source = markdown_text
        if options["strip_emoji"]:
            source = EMOJI_PATTERN.sub("", source)

        protected = {}
        source = MERMAID_FENCE_PATTERN.sub(
            lambda match: self._protect_mermaid(match, protected), source
        )
        if options["allow_bilibili"]:
            source = self._normalize_bilibili_url_lines(source)
            source = BILIBILI_MARKER_PATTERN.sub(
                lambda match: self._protect_bilibili(match, protected),
                source,
            )
        source = STRIKETHROUGH_PATTERN.sub(
            lambda match: self._protect_html(
                f"<del>{escape(match.group('text'))}</del>", protected
            ),
            source,
        )

        try:
            import markdown
        except ImportError as error:
            raise ValidationError(
                _("缺少 Python Markdown 依赖，请先安装后再转换。")
            ) from error

        try:
            converter = markdown.Markdown(
                extensions=[
                    "markdown.extensions.extra",
                    "markdown.extensions.codehilite",
                    "markdown.extensions.nl2br",
                    "markdown.extensions.sane_lists",
                    "markdown.extensions.smarty",
                    "markdown.extensions.toc",
                ],
                output_format="html5",
            )
            html_content = converter.convert(source)
        except Exception as error:
            _logger.exception("Markdown conversion failed")
            raise ValidationError(
                _("Markdown 转换失败，请检查正文语法。")
            ) from error

        html_content = html_sanitize(
            html_content,
            sanitize_attributes=True,
            sanitize_style=True,
            strip_style=True,
            strip_classes=False,
        )
        if options["create_toc"] and converter.toc:
            toc = html_sanitize(
                converter.toc,
                sanitize_attributes=True,
                sanitize_style=True,
                strip_style=True,
                strip_classes=False,
            )
            html_content = f'<nav class="o_occ_markdown_toc"><h2>目录</h2>{toc}</nav>{html_content}'
        html_content = self._apply_semantic_classes(html_content)
        for token, trusted_html in protected.items():
            html_content = html_content.replace(f"<p>{token}</p>", trusted_html)
            html_content = html_content.replace(token, trusted_html)
        return html_content

    @api.model
    def _validate_options(self, options):
        if options is None:
            options = {}
        if not isinstance(options, dict):
            raise ValidationError(_("Markdown 转换选项必须是对象。"))
        unknown = set(options) - ALLOWED_OPTIONS
        if unknown:
            raise ValidationError(
                _("包含不支持的 Markdown 转换选项：%s", ", ".join(sorted(unknown)))
            )
        values = {}
        for name in ALLOWED_OPTIONS:
            value = options.get(name, name == "allow_bilibili")
            if not isinstance(value, bool):
                raise ValidationError(_("Markdown 转换选项必须使用布尔值。"))
            values[name] = value
        return values

    @api.model
    def _normalize_bilibili_url_lines(self, source):
        normalized = []
        for line in source.splitlines(keepends=True):
            candidate = line.strip()
            video = parse_bilibili_video(candidate) if candidate else None
            if not video:
                normalized.append(line)
                continue
            marker = self._bilibili_marker(video)
            suffix = "\n" if line.endswith("\n") else ""
            normalized.append(f"{marker}{suffix}")
        return "".join(normalized)

    @api.model
    def _bilibili_marker(self, video):
        video_id = video.video_id if video.video_id.startswith("BV") else f"av{video.video_id}"
        page = f"|page={video.page}" if video.page != 1 else ""
        return f"{{{{bilibili:{video_id}{page}}}}}"

    @api.model
    def _protect_bilibili(self, match, protected):
        video_id = match.group("video_id")
        page = int(match.group("page") or 1)
        normalized_id = video_id if video_id.startswith("BV") else str(int(video_id[2:]))
        video = BilibiliVideo(video_id=normalized_id, page=page)
        return self._protect_html(self._bilibili_html(video), protected)

    @api.model
    def _protect_mermaid(self, match, protected):
        source = match.group("source").strip()
        if (
            not MERMAID_HEADER_PATTERN.match(source)
            or len(source) > MERMAID_MAX_LENGTH
            or MERMAID_FORBIDDEN_PATTERN.search(source)
        ):
            raise ValidationError(
                _("流程图仅支持安全的 Mermaid flowchart 语法。")
            )
        diagram = escape(source)
        return self._protect_html(
            '<pre class="mermaid o_occ_markdown_mermaid" '
            'data-occ-mermaid-state="pending">%s</pre>' % diagram,
            protected,
        )

    @api.model
    def _protect_html(self, trusted_html, protected):
        token = f"{TOKEN_PREFIX}{len(protected)}TOKEN"
        protected[token] = trusted_html
        return token

    @api.model
    def _bilibili_html(self, video):
        embed_url = escape(video.embed_url, quote=True)
        return (
            '<div class="media_iframe_video occ_bilibili_embedded_video '
            'o_occ_markdown_bilibili" data-oe-expression="%s">'
            '<iframe src="%s" title="B站视频" loading="lazy" frameborder="0" '
            'allowfullscreen="allowfullscreen" referrerpolicy="strict-origin-when-cross-origin">'
            "</iframe></div>"
        ) % (embed_url, embed_url)

    @api.model
    def _apply_semantic_classes(self, html_content):
        if not html_content.strip():
            return html_content
        try:
            document = lxml_html.fragment_fromstring(html_content, create_parent="div")
        except (ValueError, TypeError):
            return html_content
        for table in document.iter("table"):
            table.set("class", "table table-bordered table-hover o_table")
        for blockquote in document.iter("blockquote"):
            blockquote.set("class", "border-start border-4 ps-3 text-muted")
        for pre in document.iter("pre"):
            pre.set("class", "bg-light border rounded p-3 overflow-auto")
        for image in document.iter("img"):
            image.set("class", "img-fluid o_occ_markdown_zoomable")
            image.set("loading", "lazy")
        for link in document.iter("a"):
            link.set("rel", "noopener noreferrer")
        result = lxml_html.tostring(document, encoding="unicode")
        return result[5:-6] if result.startswith("<div>") and result.endswith("</div>") else result
