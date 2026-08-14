#!/usr/bin/env python3
"""Discover OdooCC modules and enforce the repository module standard."""

from __future__ import annotations

import argparse
import ast
import csv
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator
from urllib.parse import unquote
from xml.etree import ElementTree


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MODULE_NAME_PATTERN = re.compile(r"^occ_[a-z0-9]+(?:_[a-z0-9]+)*$")
VERSION_PATTERN = re.compile(r"^19\.0\.\d+\.\d+\.\d+$")
XMLID_PATTERN = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*\.[a-z0-9]+(?:_[a-z0-9]+)*$")
CHINESE_PATTERN = re.compile(r"[\u3400-\u9fff]")
MARKDOWN_LINK_PATTERN = re.compile(r"!?\[[^\]]*]\(([^)]+)\)")
HTML_ASSET_PATTERN = re.compile(r"""(?:src|href)=["']([^"']+)["']""", re.IGNORECASE)
HOOT_TAG_CALL_START_PATTERN = re.compile(r"\bdescribe\.current\.tags\s*\(")

EXPECTED_METADATA = {
    "author": "Odoo老赵",
    "website": "https://odoocc.com",
    "support": "156277468@qq.com",
    "license": "AGPL-3",
}
ODOOCC_DEMO_MODULE = "occ_odoocc_demo"
ODOOCC_DEMO_SCHEMA_VERSION = 1
ODOOCC_DEMO_CATEGORIES = {
    "foundation_localization": "基础与本地化",
    "customer_operations": "客户、销售与服务",
    "supply_manufacturing": "采购、库存与制造",
    "finance_compliance": "财税与合规",
    "collaboration_integration": "协同与平台集成",
    "data_ai_automation": "数据、自动化与 AI",
    "developer_tools": "开发者工具",
}
ODOOCC_DEMO_KEYS = {
    "schema_version",
    "category",
    "sequence",
    "menu_xmlid",
    "entry_menu_xmlid",
    "keywords",
}
ODOOCC_DEMO_REQUIRED_KEYS = ODOOCC_DEMO_KEYS - {"keywords"}
ODOOCC_DEMO_SEQUENCE_MIN = 1
ODOOCC_DEMO_SEQUENCE_MAX = 9999
ODOOCC_DEMO_KEYWORD_MAX_COUNT = 12
ODOOCC_DEMO_KEYWORD_MAX_LENGTH = 40
REQUIRED_MANIFEST_KEYS = {
    "name",
    "version",
    "category",
    "summary",
    "description",
    "author",
    "website",
    "support",
    "license",
    "depends",
    "application",
    "installable",
}
REQUIRED_REPOSITORY_FILES = {
    ".editorconfig",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "README.md",
    "SECURITY.md",
    "docs/ODOO_MODULE_STANDARD.md",
}
PROHIBITED_SUFFIXES = {
    ".db",
    ".backup",
    ".bak",
    ".dump",
    ".key",
    ".log",
    ".p12",
    ".pfx",
    ".pyc",
    ".pyo",
    ".sqlite",
    ".sqlite3",
}
PROHIBITED_FILENAMES = {
    ".env",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
}
HIGH_CONFIDENCE_SECRET_PATTERNS = {
    "private key": re.compile(
        r"-----BEGIN (?:RSA |DSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"
    ),
    "PGP private key": re.compile(r"-----BEGIN PGP PRIVATE KEY BLOCK-{5}"),
    "PostgreSQL database dump": re.compile(r"^-- PostgreSQL database dump", re.MULTILINE),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(
        r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{70,})\b"
    ),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "Stripe live key": re.compile(r"\bsk_live_[A-Za-z0-9]{20,}\b"),
}
SECRET_NAME_FRAGMENT = (
    r"(?:app_?secret|client_?secret|api_?key|access_?token|refresh_?token|password)"
)
SECRET_VALUE_FRAGMENT = r"[A-Za-z0-9/+_.=@%:-]{20,}"
SECRET_ASSIGNMENT_PATTERN = re.compile(
    rf"""(?ix)
    \b{SECRET_NAME_FRAGMENT}\b
    ["']?\s*[:=]\s*["']
    (?P<value>{SECRET_VALUE_FRAGMENT})["']
    """
)
UNQUOTED_SECRET_ASSIGNMENT_PATTERN = re.compile(
    rf"""(?ix)
    \b{SECRET_NAME_FRAGMENT}\b
    \s*[:=]\s*
    (?P<value>{SECRET_VALUE_FRAGMENT})
    (?![A-Za-z0-9/+_.=@%:-])
    """
)
UNQUOTED_SECRET_TEXT_SUFFIXES = {
    "",
    ".bash",
    ".cfg",
    ".conf",
    ".ini",
    ".md",
    ".rst",
    ".sh",
    ".txt",
    ".yaml",
    ".yml",
    ".zsh",
}
SET_PARAM_LITERAL_PATTERN = re.compile(
    rf"""(?ix)
    \bset_param\s*\(
    \s*["'](?P<key>[^"'\r\n]+)["']\s*,\s*
    ["'](?P<value>{SECRET_VALUE_FRAGMENT})["']
    """
)
SECRET_CONFIG_KEY_PATTERN = re.compile(
    r"(?i)(?:secret|api[_-]?key|access[_-]?token|refresh[_-]?token|password)"
)
PLACEHOLDER_MARKERS = {
    "changeme",
    "dummy",
    "example",
    "fake",
    "placeholder",
    "sample",
    "temporary",
    "test",
    "your_",
}


class StandardError(RuntimeError):
    """Raised when discovery cannot safely produce module output."""


@dataclass(frozen=True)
class ModuleInfo:
    """A discovered module and its literal Manifest."""

    name: str
    path: Path
    manifest: dict

    @property
    def is_test(self) -> bool:
        return self.name.endswith("_test")

    @property
    def counterpart_name(self) -> str:
        return self.name.removesuffix("_test") if self.is_test else f"{self.name}_test"

    @property
    def version(self) -> str:
        return str(self.manifest.get("version", ""))

    @property
    def has_hoot_tests(self) -> bool:
        assets = self.manifest.get("assets")
        return (
            isinstance(assets, dict)
            and bool(assets.get("web.assets_unit_tests"))
            and any((self.path / "static" / "tests").rglob("*.js"))
        )


@dataclass(frozen=True)
class _MenuDefinition:
    """Static menu information required by the public demo-registration contract."""

    xmlid: str
    parent_xmlid: str | None
    has_action: bool


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def discover_module_paths(root: Path) -> tuple[list[Path], list[str]]:
    """Find only direct child OdooCC modules from the working tree."""

    errors: list[str] = []
    paths: list[Path] = []
    if not root.is_dir():
        return [], [f"仓库目录不存在：{root}"]

    for child in sorted(root.iterdir(), key=lambda item: item.name):
        if not child.name.startswith("occ_"):
            continue
        if child.is_symlink():
            errors.append(f"{child.name}: 模块目录不得是符号链接")
            continue
        if not child.is_dir():
            continue
        manifest_path = child / "__manifest__.py"
        if manifest_path.is_file():
            paths.append(child)
        else:
            errors.append(f"{child.name}: occ_* 目录缺少 __manifest__.py")
    if not paths:
        errors.append("仓库根目录没有发现任何 OdooCC 模块")
    return paths, errors


def parse_manifest(path: Path) -> dict:
    """Read a Manifest without executing repository code."""

    try:
        value = ast.literal_eval(_read_text(path))
    except (OSError, SyntaxError, ValueError) as exc:
        raise StandardError(f"{path}: Manifest 无法解析：{exc}") from exc
    if not isinstance(value, dict):
        raise StandardError(f"{path}: Manifest 顶层必须是字典")
    return value


def load_modules_for_output(root: Path) -> list[ModuleInfo]:
    """Load enough validated data to produce shell-safe CI values."""

    paths, errors = discover_module_paths(root)
    modules: list[ModuleInfo] = []
    for path in paths:
        if not MODULE_NAME_PATTERN.fullmatch(path.name):
            errors.append(f"{path.name}: 技术名不符合 {MODULE_NAME_PATTERN.pattern}")
            continue
        try:
            manifest = parse_manifest(path / "__manifest__.py")
        except StandardError as exc:
            errors.append(str(exc))
            continue
        module = ModuleInfo(path.name, path, manifest)
        modules.append(module)
        dependencies = manifest.get("depends")
        if manifest.get("installable") is not True:
            errors.append(f"{path.name}: installable 必须为 True")
        if not isinstance(dependencies, list):
            errors.append(f"{path.name}: depends 必须是列表")
        elif module.is_test and module.counterpart_name not in dependencies:
            errors.append(
                f"{path.name}: _test 模块必须直接依赖 {module.counterpart_name}"
            )
        elif not module.is_test and any(
            dependency.endswith("_test")
            for dependency in dependencies
            if isinstance(dependency, str)
        ):
            errors.append(f"{path.name}: 正式模块不得依赖 _test 模块")
        if isinstance(dependencies, list) and ODOOCC_DEMO_MODULE in dependencies:
            errors.append(
                f"{path.name}: 不得依赖可选部署模块 {ODOOCC_DEMO_MODULE}"
            )
    errors.extend(_check_module_pairs(modules))
    if errors:
        raise StandardError("\n".join(errors))
    return modules


def _check_manifest(module: ModuleInfo, root: Path) -> list[str]:
    errors: list[str] = []
    manifest = module.manifest
    label = f"{module.name}/__manifest__.py"

    missing = sorted(REQUIRED_MANIFEST_KEYS - manifest.keys())
    if missing:
        errors.append(f"{label}: 缺少字段 {', '.join(missing)}")

    display_name = manifest.get("name")
    if not isinstance(display_name, str) or not display_name.strip().startswith("OdooCC"):
        errors.append(f"{label}: name 必须是以 OdooCC 开头的非空字符串")

    for key in ("category", "summary", "description"):
        value = manifest.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{label}: {key} 必须是非空字符串")
    summary = manifest.get("summary")
    if isinstance(summary, str) and len(summary.strip()) > 120:
        errors.append(f"{label}: summary 不应超过 120 个字符")

    if not VERSION_PATTERN.fullmatch(str(manifest.get("version", ""))):
        errors.append(f"{label}: version 必须匹配 19.0.x.y.z")
    for key, expected in EXPECTED_METADATA.items():
        if manifest.get(key) != expected:
            errors.append(f"{label}: {key} 必须为 {expected!r}")

    dependencies = manifest.get("depends")
    if not isinstance(dependencies, list) or not dependencies:
        errors.append(f"{label}: depends 必须是非空列表")
        dependencies = []
    else:
        seen_dependencies: set[str] = set()
        for dependency in dependencies:
            if not isinstance(dependency, str) or not re.fullmatch(
                r"[a-z0-9]+(?:_[a-z0-9]+)*", dependency
            ):
                errors.append(f"{label}: 无效依赖名 {dependency!r}")
            elif dependency in seen_dependencies:
                errors.append(f"{label}: depends 包含重复项 {dependency!r}")
            else:
                seen_dependencies.add(dependency)

    if manifest.get("installable") is not True:
        errors.append(f"{label}: installable 必须为 True")
    if not isinstance(manifest.get("application"), bool):
        errors.append(f"{label}: application 必须显式使用布尔值")

    if module.is_test:
        if module.counterpart_name not in dependencies:
            errors.append(
                f"{label}: _test 模块必须直接依赖 {module.counterpart_name!r}"
            )
        if manifest.get("auto_install") is not False:
            errors.append(f"{label}: _test 模块的 auto_install 必须为 False")
        if manifest.get("application") is not False:
            errors.append(f"{label}: _test 模块的 application 必须为 False")
    elif any(
        isinstance(dependency, str) and dependency.endswith("_test")
        for dependency in dependencies
    ):
        errors.append(f"{label}: 正式模块不得依赖 _test 模块")

    if ODOOCC_DEMO_MODULE in dependencies:
        errors.append(
            f"{label}: 不得依赖可选部署模块 {ODOOCC_DEMO_MODULE}"
        )

    for section in ("data", "demo"):
        entries = manifest.get(section, [])
        if not isinstance(entries, list):
            errors.append(f"{label}: {section} 必须是列表")
            continue
        seen_entries: set[str] = set()
        for entry in entries:
            if not isinstance(entry, str):
                errors.append(f"{label}: {section} 路径必须是字符串：{entry!r}")
                continue
            if entry in seen_entries:
                errors.append(f"{label}: {section} 包含重复路径 {entry!r}")
            seen_entries.add(entry)
            candidate = module.path / entry
            if Path(entry).is_absolute() or ".." in Path(entry).parts:
                errors.append(f"{label}: {section} 路径不得越出模块：{entry!r}")
            elif not candidate.is_file():
                errors.append(f"{label}: {section} 文件不存在：{entry!r}")

    assets = manifest.get("assets", {})
    if assets and not isinstance(assets, dict):
        errors.append(f"{label}: assets 必须是字典")
    elif isinstance(assets, dict):
        for bundle, entries in assets.items():
            if not isinstance(bundle, str) or not isinstance(entries, list):
                errors.append(f"{label}: asset bundle {bundle!r} 必须映射到列表")
                continue
            if _references_optional_demo_asset(bundle):
                errors.append(
                    f"{label}: asset bundle 不得引用可选部署模块 "
                    f"{ODOOCC_DEMO_MODULE}：{bundle!r}"
                )
            seen_assets: set[str] = set()
            for reference in _asset_references(entries):
                if reference in seen_assets:
                    errors.append(f"{label}: asset 重复引用 {reference!r}")
                seen_assets.add(reference)
                if _references_optional_demo_asset(reference):
                    errors.append(
                        f"{label}: asset 不得引用可选部署模块 "
                        f"{ODOOCC_DEMO_MODULE}：{reference!r}"
                    )
                if not reference.startswith(f"{module.name}/"):
                    continue
                relative_pattern = reference.removeprefix(f"{module.name}/")
                if ".." in Path(relative_pattern).parts:
                    errors.append(f"{label}: asset 路径不得越出模块：{reference!r}")
                elif not any(module.path.glob(relative_pattern)):
                    errors.append(f"{label}: asset 路径未匹配文件：{reference!r}")

    hoot_test_paths = sorted((module.path / "static" / "tests").rglob("*.js"))
    unit_test_assets = (
        assets.get("web.assets_unit_tests", [])
        if isinstance(assets, dict)
        else []
    )
    if hoot_test_paths:
        covered_paths: set[Path] = set()
        if isinstance(unit_test_assets, list):
            if any(not isinstance(entry, str) for entry in unit_test_assets):
                errors.append(
                    f"{label}: web.assets_unit_tests 只允许直接字符串路径或 glob，"
                    "不得使用 include/remove/replace 等指令"
                )
            for reference in (
                entry for entry in unit_test_assets if isinstance(entry, str)
            ):
                if not reference.startswith(f"{module.name}/"):
                    continue
                relative_pattern = reference.removeprefix(f"{module.name}/")
                covered_paths.update(
                    path.resolve()
                    for path in module.path.glob(relative_pattern)
                    if path.is_file()
                )
        for test_path in hoot_test_paths:
            if test_path.resolve() not in covered_paths:
                errors.append(
                    f"{label}: web.assets_unit_tests 未包含 "
                    f"{_relative(test_path, root)}"
                )
            source = _read_text(test_path)
            valid_tag_call = any(
                module.name in tags
                and len({"headless", "desktop"} & tags) == 1
                for tags in _javascript_describe_tag_calls(source)
            )
            if not valid_tag_call:
                errors.append(
                    f"{_relative(test_path, root)}: Hoot 测试必须在同一个 "
                    "describe.current.tags 调用中包含 'headless' 或 'desktop'，"
                    f"以及 {module.name!r}"
                )
    elif unit_test_assets:
        errors.append(
            f"{label}: 声明了 web.assets_unit_tests，"
            "但 static/tests 没有 JavaScript"
        )

    errors.extend(_check_demo_metadata(module))

    return errors


def _normalized_xmlid(module_name: str, value: str | None) -> str | None:
    if not value:
        return None
    return value if "." in value else f"{module_name}.{value}"


def _manifest_menu_definitions(module: ModuleInfo) -> dict[str, _MenuDefinition]:
    """Return menus loaded unconditionally by the module's Manifest data list."""

    definitions: dict[str, _MenuDefinition] = {}
    entries = module.manifest.get("data")
    if not isinstance(entries, list):
        return definitions
    for entry in entries:
        if not isinstance(entry, str) or Path(entry).suffix.casefold() != ".xml":
            continue
        path = module.path / entry
        if not path.is_file():
            continue
        try:
            tree = ElementTree.parse(path)
        except (OSError, ElementTree.ParseError):
            continue
        for element in tree.iter():
            element_id = element.get("id")
            if not element_id:
                continue
            xmlid = _normalized_xmlid(module.name, element_id)
            if element.tag == "menuitem":
                definitions[xmlid] = _MenuDefinition(
                    xmlid=xmlid,
                    parent_xmlid=_normalized_xmlid(
                        module.name,
                        element.get("parent"),
                    ),
                    has_action=bool((element.get("action") or "").strip()),
                )
                continue
            if element.tag != "record" or element.get("model") != "ir.ui.menu":
                continue
            parent_xmlid: str | None = None
            has_action = False
            for field in element.findall("field"):
                field_name = field.get("name")
                if field_name == "parent_id":
                    parent_xmlid = _normalized_xmlid(
                        module.name,
                        field.get("ref"),
                    )
                elif field_name == "action":
                    eval_value = (field.get("eval") or "").strip()
                    has_action = bool(
                        (field.get("ref") or "").strip()
                        or (
                            eval_value
                            and eval_value not in {"False", "None", "0"}
                        )
                        or (field.text or "").strip()
                    )
            definitions[xmlid] = _MenuDefinition(
                xmlid=xmlid,
                parent_xmlid=parent_xmlid,
                has_action=has_action,
            )
    return definitions


def _check_demo_xmlid(
    module: ModuleInfo,
    metadata: dict,
    key: str,
    label: str,
) -> tuple[str | None, list[str]]:
    errors: list[str] = []
    value = metadata.get(key)
    if not isinstance(value, str) or not XMLID_PATTERN.fullmatch(value):
        errors.append(f"{label}: odoocc_demo.{key} 必须是完整的小写 XML ID")
        return None, errors
    if not value.startswith(f"{module.name}."):
        errors.append(
            f"{label}: odoocc_demo.{key} 必须引用当前模块 {module.name}"
        )
        return None, errors
    return value, errors


def _check_demo_metadata(module: ModuleInfo) -> list[str]:
    """Validate the optional, dependency-free contract consumed by demo deployments."""

    errors: list[str] = []
    label = f"{module.name}/__manifest__.py"
    metadata = module.manifest.get("odoocc_demo")
    if not module.is_test:
        if metadata is not None:
            errors.append(f"{label}: 只有 _test 模块可声明 odoocc_demo")
        return errors
    if not isinstance(metadata, dict):
        return [f"{label}: _test 模块必须声明 odoocc_demo 字典"]

    missing = sorted(
        key for key in ODOOCC_DEMO_REQUIRED_KEYS if key not in metadata
    )
    unknown = sorted(
        (key for key in metadata if key not in ODOOCC_DEMO_KEYS),
        key=repr,
    )
    if missing:
        errors.append(
            f"{label}: odoocc_demo 缺少字段 {', '.join(missing)}"
        )
    if unknown:
        errors.append(
            f"{label}: odoocc_demo 包含未知字段 "
            f"{', '.join(repr(key) for key in unknown)}"
        )

    schema_version = metadata.get("schema_version")
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != ODOOCC_DEMO_SCHEMA_VERSION
    ):
        errors.append(
            f"{label}: odoocc_demo.schema_version 必须为 "
            f"{ODOOCC_DEMO_SCHEMA_VERSION}"
        )

    category = metadata.get("category")
    if not isinstance(category, str) or category not in ODOOCC_DEMO_CATEGORIES:
        errors.append(
            f"{label}: odoocc_demo.category 必须是七个允许值之一："
            f"{', '.join(ODOOCC_DEMO_CATEGORIES)}"
        )

    sequence = metadata.get("sequence")
    if (
        isinstance(sequence, bool)
        or not isinstance(sequence, int)
        or not ODOOCC_DEMO_SEQUENCE_MIN
        <= sequence
        <= ODOOCC_DEMO_SEQUENCE_MAX
    ):
        errors.append(
            f"{label}: odoocc_demo.sequence 必须是 "
            f"{ODOOCC_DEMO_SEQUENCE_MIN}..{ODOOCC_DEMO_SEQUENCE_MAX} 的整数"
        )

    keywords = metadata.get("keywords", [])
    if not isinstance(keywords, list):
        errors.append(f"{label}: odoocc_demo.keywords 必须是字符串列表")
    else:
        if len(keywords) > ODOOCC_DEMO_KEYWORD_MAX_COUNT:
            errors.append(
                f"{label}: odoocc_demo.keywords 不得超过 "
                f"{ODOOCC_DEMO_KEYWORD_MAX_COUNT} 项"
            )
        seen_keywords: set[str] = set()
        for index, keyword in enumerate(keywords):
            if (
                not isinstance(keyword, str)
                or not keyword.strip()
                or keyword != keyword.strip()
                or "\n" in keyword
                or "\r" in keyword
                or len(keyword) > ODOOCC_DEMO_KEYWORD_MAX_LENGTH
            ):
                errors.append(
                    f"{label}: odoocc_demo.keywords[{index}] 必须是最长 "
                    f"{ODOOCC_DEMO_KEYWORD_MAX_LENGTH} 字符的非空单行字符串"
                )
                continue
            normalized = keyword.casefold()
            if normalized in seen_keywords:
                errors.append(
                    f"{label}: odoocc_demo.keywords 包含重复项 {keyword!r}"
                )
            seen_keywords.add(normalized)

    menu_xmlid, menu_errors = _check_demo_xmlid(
        module,
        metadata,
        "menu_xmlid",
        label,
    )
    entry_xmlid, entry_errors = _check_demo_xmlid(
        module,
        metadata,
        "entry_menu_xmlid",
        label,
    )
    errors.extend(menu_errors)
    errors.extend(entry_errors)
    definitions = _manifest_menu_definitions(module)
    if menu_xmlid and menu_xmlid not in definitions:
        errors.append(
            f"{label}: odoocc_demo.menu_xmlid 未指向 Manifest data 中的 ir.ui.menu"
        )
    if entry_xmlid and entry_xmlid not in definitions:
        errors.append(
            f"{label}: odoocc_demo.entry_menu_xmlid "
            "未指向 Manifest data 中的 ir.ui.menu"
        )
    if menu_xmlid in definitions and entry_xmlid in definitions:
        entry = definitions[entry_xmlid]
        if not entry.has_action:
            errors.append(
                f"{label}: odoocc_demo.entry_menu_xmlid 必须指向带 action 的可点击菜单"
            )
        current_xmlid: str | None = entry_xmlid
        visited: set[str] = set()
        while current_xmlid and current_xmlid not in visited:
            if current_xmlid == menu_xmlid:
                break
            visited.add(current_xmlid)
            definition = definitions.get(current_xmlid)
            current_xmlid = definition.parent_xmlid if definition else None
        else:
            current_xmlid = None
        if current_xmlid != menu_xmlid:
            errors.append(
                f"{label}: odoocc_demo.entry_menu_xmlid 必须是 menu_xmlid 本身或其后代"
            )
    return errors


def _mask_javascript_non_code(source: str) -> str:
    """Mask comments and string literals while preserving offsets and newlines."""

    masked = list(source)
    length = len(source)

    def mask(start: int, end: int) -> None:
        for index in range(start, end):
            if source[index] not in "\r\n":
                masked[index] = " "

    index = 0
    while index < length:
        if source.startswith("//", index):
            end = source.find("\n", index + 2)
            end = length if end == -1 else end
            mask(index, end)
            index = end
            continue
        if source.startswith("/*", index):
            closing = source.find("*/", index + 2)
            end = length if closing == -1 else closing + 2
            mask(index, end)
            index = end
            continue
        delimiter = source[index]
        if delimiter not in {"'", '"', "`"}:
            index += 1
            continue
        end = index + 1
        escaped = False
        while end < length:
            character = source[end]
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == delimiter:
                end += 1
                break
            end += 1
        mask(index, end)
        index = end
    return "".join(masked)


def _javascript_call_end(masked_source: str, opening_parenthesis: int) -> int | None:
    depth = 0
    for index in range(opening_parenthesis, len(masked_source)):
        character = masked_source[index]
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return index
    return None


def _split_javascript_arguments(source: str, masked_source: str) -> list[str]:
    arguments: list[str] = []
    start = 0
    depths = {"(": 0, "[": 0, "{": 0}
    closing_to_opening = {")": "(", "]": "[", "}": "{"}
    for index, character in enumerate(masked_source):
        if character in depths:
            depths[character] += 1
        elif character in closing_to_opening:
            opening = closing_to_opening[character]
            depths[opening] = max(0, depths[opening] - 1)
        elif character == "," and not any(depths.values()):
            arguments.append(source[start:index])
            start = index + 1
    arguments.append(source[start:])
    return arguments


def _javascript_string_literal(argument: str) -> str | None:
    value = argument.strip()
    if len(value) < 2 or value[0] not in {"'", '"'} or value[-1] != value[0]:
        return None
    delimiter = value[0]
    characters: list[str] = []
    index = 1
    while index < len(value) - 1:
        character = value[index]
        if character == "\\":
            index += 1
            if index >= len(value) - 1:
                return None
            characters.append(value[index])
        elif character == delimiter:
            return None
        else:
            characters.append(character)
        index += 1
    return "".join(characters)


def _javascript_describe_tag_calls(source: str) -> Iterator[set[str]]:
    masked_source = _mask_javascript_non_code(source)
    for match in HOOT_TAG_CALL_START_PATTERN.finditer(masked_source):
        opening_parenthesis = match.end() - 1
        closing_parenthesis = _javascript_call_end(
            masked_source,
            opening_parenthesis,
        )
        if closing_parenthesis is None:
            continue
        argument_source = source[opening_parenthesis + 1 : closing_parenthesis]
        argument_mask = masked_source[opening_parenthesis + 1 : closing_parenthesis]
        tags = {
            literal
            for argument in _split_javascript_arguments(
                argument_source,
                argument_mask,
            )
            if (literal := _javascript_string_literal(argument)) is not None
        }
        yield tags


def _asset_references(entries: list) -> Iterator[str]:
    for entry in entries:
        if isinstance(entry, str):
            yield entry
        elif isinstance(entry, (list, tuple)):
            for value in entry[1:]:
                if isinstance(value, str):
                    yield value


def _references_optional_demo_asset(reference: str) -> bool:
    return reference == ODOOCC_DEMO_MODULE or reference.startswith(
        (
            f"{ODOOCC_DEMO_MODULE}/",
            f"{ODOOCC_DEMO_MODULE}.",
            f"@{ODOOCC_DEMO_MODULE}/",
        )
    )


def _skip_javascript_space_and_comments(source: str, index: int) -> int:
    length = len(source)
    while index < length:
        if source[index].isspace():
            index += 1
            continue
        if source.startswith("//", index):
            newline = source.find("\n", index + 2)
            index = length if newline == -1 else newline + 1
            continue
        if source.startswith("/*", index):
            closing = source.find("*/", index + 2)
            index = length if closing == -1 else closing + 2
            continue
        break
    return index


def _javascript_string_at(source: str, index: int) -> str | None:
    index = _skip_javascript_space_and_comments(source, index)
    if index >= len(source) or source[index] not in {"'", '"'}:
        return None
    delimiter = source[index]
    characters: list[str] = []
    index += 1
    while index < len(source):
        character = source[index]
        if character == delimiter:
            return "".join(characters)
        if character == "\\":
            index += 1
            if index >= len(source):
                return None
            character = source[index]
        elif character in "\r\n":
            return None
        characters.append(character)
        index += 1
    return None


def _javascript_optional_demo_imports(source: str) -> set[str]:
    """Return static or dynamic ESM specifiers targeting the private demo module."""

    masked_source = _mask_javascript_non_code(source)
    statements = list(re.finditer(r"\b(?:import|export)\b", masked_source))
    imports: set[str] = set()
    for statement_index, statement in enumerate(statements):
        boundary = (
            statements[statement_index + 1].start()
            if statement_index + 1 < len(statements)
            else len(source)
        )
        semicolon = masked_source.find(";", statement.end(), boundary)
        if semicolon != -1:
            boundary = semicolon

        cursor = _skip_javascript_space_and_comments(source, statement.end())
        if statement.group() == "import" and cursor < len(source):
            if source[cursor] == "(":
                specifier = _javascript_string_at(source, cursor + 1)
                if specifier is not None:
                    imports.add(specifier)
                continue
            specifier = _javascript_string_at(source, cursor)
            if specifier is not None:
                imports.add(specifier)
                continue

        from_match = re.search(
            r"\bfrom\b",
            masked_source[statement.end() : boundary],
        )
        if from_match:
            specifier = _javascript_string_at(
                source,
                statement.end() + from_match.end(),
            )
            if specifier is not None:
                imports.add(specifier)

    return {
        specifier
        for specifier in imports
        if specifier == f"@{ODOOCC_DEMO_MODULE}"
        or specifier.startswith(f"@{ODOOCC_DEMO_MODULE}/")
    }


def _imports_optional_demo_module(source: str, filename: str) -> bool:
    try:
        tree = ast.parse(source, filename=filename)
    except (SyntaxError, ValueError):
        return False

    def is_forbidden(name: str | None) -> bool:
        if not name:
            return False
        return name == ODOOCC_DEMO_MODULE or name.startswith(
            f"odoo.addons.{ODOOCC_DEMO_MODULE}"
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            is_forbidden(alias.name) for alias in node.names
        ):
            return True
        if isinstance(node, ast.ImportFrom):
            if is_forbidden(node.module):
                return True
            if node.module in {"odoo.addons", None} and any(
                alias.name == ODOOCC_DEMO_MODULE for alias in node.names
            ):
                return True
    return False


def _check_module_files(module: ModuleInfo, root: Path) -> list[str]:
    errors: list[str] = []
    required = [
        module.path / "__init__.py",
        module.path / "README.md",
        module.path / "tests" / "__init__.py",
    ]
    for path in required:
        if not path.is_file():
            errors.append(f"{_relative(path, root)}: 必需文件不存在")

    test_paths = sorted((module.path / "tests").glob("test_*.py"))
    if not test_paths:
        errors.append(f"{module.name}/tests: 至少需要一个 test_*.py")
    elif (module.path / "tests" / "__init__.py").is_file():
        imported = _test_imports(module.path / "tests" / "__init__.py")
        for test_path in test_paths:
            if test_path.stem not in imported:
                errors.append(
                    f"{module.name}/tests/__init__.py: 未导入 {test_path.stem}"
                )
            source = _read_text(test_path)
            if not all(
                marker in source
                for marker in ("tagged", "post_install", "-at_install")
            ):
                errors.append(
                    f"{_relative(test_path, root)}: Odoo 测试应标记 post_install/-at_install"
                )

    for python_path in sorted(module.path.rglob("*.py")):
        try:
            source = _read_text(python_path)
            compile(source, str(python_path), "exec")
        except (OSError, SyntaxError, UnicodeError) as exc:
            errors.append(f"{_relative(python_path, root)}: Python 语法错误：{exc}")
            continue
        if _imports_optional_demo_module(source, str(python_path)):
            errors.append(
                f"{_relative(python_path, root)}: 不得导入可选部署模块 "
                f"{ODOOCC_DEMO_MODULE}"
            )

    for javascript_path in sorted(module.path.rglob("*.js")):
        try:
            source = _read_text(javascript_path)
        except (OSError, UnicodeError) as exc:
            errors.append(
                f"{_relative(javascript_path, root)}: JavaScript 无法读取：{exc}"
            )
            continue
        forbidden_imports = sorted(_javascript_optional_demo_imports(source))
        if forbidden_imports:
            errors.append(
                f"{_relative(javascript_path, root)}: 不得导入可选部署模块 "
                f"{ODOOCC_DEMO_MODULE} 的 JavaScript："
                f"{', '.join(repr(value) for value in forbidden_imports)}"
            )

    acl_path = module.path / "security" / "ir.model.access.csv"
    manifest_data = module.manifest.get("data")
    if acl_path.is_file() and (
        not isinstance(manifest_data, list)
        or "security/ir.model.access.csv" not in manifest_data
    ):
        errors.append(f"{module.name}: Manifest data 未加载 ir.model.access.csv")

    for xml_path in sorted(
        list(module.path.rglob("*.xml")) + list(module.path.rglob("*.svg"))
    ):
        try:
            tree = ElementTree.parse(xml_path)
        except (OSError, ElementTree.ParseError) as exc:
            errors.append(f"{_relative(xml_path, root)}: XML/SVG 无法解析：{exc}")
            continue
        if xml_path.suffix == ".xml" and any(
            f"{ODOOCC_DEMO_MODULE}." in attribute
            for element in tree.iter()
            for attribute in element.attrib.values()
        ):
            errors.append(
                f"{_relative(xml_path, root)}: 不得引用可选部署模块 "
                f"{ODOOCC_DEMO_MODULE} 的 XML ID"
            )
        if xml_path.suffix == ".xml" and any(
            element.tag == "tree" for element in tree.iter()
        ):
            errors.append(
                f"{_relative(xml_path, root)}: Odoo 19 列表视图应使用 <list>，不是 <tree>"
            )

    for csv_path in sorted(module.path.rglob("*.csv")):
        errors.extend(_check_csv(csv_path, root))

    readme_path = module.path / "README.md"
    if readme_path.is_file():
        errors.extend(_check_module_readme(module, readme_path, root))
    return errors


def _test_imports(path: Path) -> set[str]:
    try:
        tree = ast.parse(_read_text(path), filename=str(path))
    except (OSError, SyntaxError, UnicodeError):
        return set()
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            imported.update(alias.name for alias in node.names)
    return imported


def _check_csv(path: Path, root: Path) -> list[str]:
    errors: list[str] = []
    label = _relative(path, root)
    try:
        with path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.reader(stream))
    except (OSError, UnicodeError, csv.Error) as exc:
        return [f"{label}: CSV 无法解析：{exc}"]
    if not rows or not rows[0]:
        return [f"{label}: CSV 必须包含表头"]
    width = len(rows[0])
    for index, row in enumerate(rows[1:], start=2):
        if len(row) != width:
            errors.append(f"{label}:{index}: CSV 列数与表头不一致")
    if path.name == "ir.model.access.csv":
        expected_header = [
            "id",
            "name",
            "model_id:id",
            "group_id:id",
            "perm_read",
            "perm_write",
            "perm_create",
            "perm_unlink",
        ]
        if rows[0] != expected_header:
            errors.append(f"{label}: ACL 表头不符合 Odoo 标准")
        if len(rows) < 2:
            errors.append(f"{label}: ACL 文件没有任何权限记录")
    return errors


def _check_module_readme(
    module: ModuleInfo, readme_path: Path, root: Path
) -> list[str]:
    errors: list[str] = []
    text = _read_text(readme_path)
    label = _relative(readme_path, root)
    required_fragments = {
        module.name: "技术名",
        "English summary": "英文摘要标题",
        "安装": "安装说明",
        "测试": "测试说明",
        "许可证": "许可证说明",
        "Odoo老赵": "作者",
        "https://odoocc.com": "官网",
        "156277468@qq.com": "支持邮箱",
    }
    for fragment, description in required_fragments.items():
        if fragment not in text:
            errors.append(f"{label}: 缺少{description} {fragment!r}")
    if not CHINESE_PATTERN.search(text):
        errors.append(f"{label}: 必须包含中文正文")
    if not any(keyword in text for keyword in ("安全", "权限")):
        errors.append(f"{label}: 缺少权限或安全边界")
    if module.is_test:
        if "生产" not in text or not any(
            warning in text for warning in ("不建议", "不得", "不要", "不应", "仅用于")
        ):
            errors.append(f"{label}: _test README 必须明确非生产用途")
    elif module.counterpart_name not in text:
        errors.append(
            f"{label}: 正式模块 README 必须说明 {module.counterpart_name} 验收模块"
        )
    return errors


def _check_module_pairs(modules: list[ModuleInfo]) -> list[str]:
    errors: list[str] = []
    module_names = {module.name for module in modules}
    for module in modules:
        if module.counterpart_name not in module_names:
            if module.is_test:
                errors.append(
                    f"{module.name}: 对应正式模块 {module.counterpart_name} 不存在"
                )
            else:
                errors.append(
                    f"{module.name}: 缺少配套验收模块 {module.counterpart_name}"
                )
    return errors


def _repository_files(root: Path) -> list[Path]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-co", "--exclude-standard", "-z"],
            check=True,
            capture_output=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return sorted(
            path
            for path in root.rglob("*")
            if path.is_file()
            and ".git" not in path.parts
            and "__pycache__" not in path.parts
        )
    paths = []
    for raw_path in result.stdout.split(b"\0"):
        if not raw_path:
            continue
        path = root / raw_path.decode("utf-8", errors="surrogateescape")
        if path.is_file():
            paths.append(path)
    return sorted(set(paths))


def _markdown_section_lines(text: str, title: str) -> list[str] | None:
    lines = text.splitlines()
    section_start: int | None = None
    section_level: int | None = None
    heading_pattern = re.compile(
        r"^(?P<marks>#{1,6})[ \t]+(?P<title>.*?)[ \t]*#*[ \t]*$"
    )
    for index, line in enumerate(lines):
        match = heading_pattern.match(line)
        if not match or match.group("title").strip() != title:
            continue
        section_start = index + 1
        section_level = len(match.group("marks"))
        break
    if section_start is None or section_level is None:
        return None

    section_end = len(lines)
    for index in range(section_start, len(lines)):
        match = heading_pattern.match(lines[index])
        if match and len(match.group("marks")) <= section_level:
            section_end = index
            break
    return lines[section_start:section_end]


def _markdown_table_cells(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for character in stripped:
        if character == "|" and not escaped:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(character)
        if character == "\\" and not escaped:
            escaped = True
        else:
            escaped = False
    cells.append("".join(current).strip())
    if cells and not cells[0]:
        cells.pop(0)
    if cells and not cells[-1]:
        cells.pop()
    return cells


def _markdown_cell_value(cell: str) -> str:
    value = cell.strip()
    if len(value) >= 2 and value.startswith("`") and value.endswith("`"):
        value = value[1:-1].strip()
    return value


def _module_table_rows(readme: str) -> tuple[bool, list[tuple[str, str]]]:
    section = _markdown_section_lines(readme, "模块一览")
    if section is None:
        return False, []

    module_column: int | None = None
    version_column: int | None = None
    rows: list[tuple[str, str]] = []
    table_started = False
    for line in section:
        cells = _markdown_table_cells(line)
        if cells is None:
            if table_started:
                break
            continue
        values = [_markdown_cell_value(cell) for cell in cells]
        if module_column is None or version_column is None:
            if "模块" not in values or "版本" not in values:
                continue
            module_column = values.index("模块")
            version_column = values.index("版本")
            table_started = True
            continue
        if all(re.fullmatch(r":?-{3,}:?", value) for value in values):
            continue
        required_column = max(module_column, version_column)
        if len(values) <= required_column:
            continue
        module_name = values[module_column]
        if not MODULE_NAME_PATTERN.fullmatch(module_name):
            continue
        rows.append((module_name, values[version_column]))
    return table_started, rows


def _check_repository_files(
    root: Path, modules: list[ModuleInfo], files: list[Path]
) -> list[str]:
    errors: list[str] = []
    for relative in sorted(REQUIRED_REPOSITORY_FILES):
        if not (root / relative).is_file():
            errors.append(f"{relative}: 仓库必需文件不存在")

    root_readme_path = root / "README.md"
    if root_readme_path.is_file():
        root_readme = _read_text(root_readme_path)
        table_found, table_rows = _module_table_rows(root_readme)
        rows_by_module: dict[str, list[str]] = {}
        for module_name, version in table_rows:
            rows_by_module.setdefault(module_name, []).append(version)
        if not table_found:
            errors.append("README.md: 模块一览缺少包含“模块”和“版本”的表格")
        for module in modules:
            versions = rows_by_module.get(module.name, [])
            if not versions:
                errors.append(f"README.md: 模块表缺少 {module.name}")
            elif len(versions) > 1:
                errors.append(f"README.md: 模块表重复记录 {module.name}")
            elif versions[0] != module.version:
                errors.append(
                    f"README.md: {module.name} 表格版本应为 {module.version!r}，"
                    f"实际为 {versions[0]!r}"
                )
        discovered_names = {module.name for module in modules}
        for module_name in sorted(rows_by_module.keys() - discovered_names):
            errors.append(f"README.md: 模块表包含未发现模块 {module_name}")

    for path in files:
        relative = _relative(path, root)
        lower_name = path.name.casefold()
        is_unsafe_env = path.name.startswith(".env") and path.name not in {
            ".env.example",
            ".env.sample",
            ".env.template",
        }
        is_database_archive = (
            lower_name.endswith((".sql.gz", ".dump.gz"))
            or (
                path.suffix.casefold() == ".sql"
                and "migrations" not in path.parts
            )
        )
        if (
            path.name in PROHIBITED_FILENAMES
            or path.suffix.lower() in PROHIBITED_SUFFIXES
            or is_unsafe_env
            or is_database_archive
        ):
            errors.append(f"{relative}: 禁止提交运行产物、凭据或密钥文件")
        try:
            content = _read_text(path)
        except (OSError, UnicodeError):
            continue
        for description, pattern in HIGH_CONFIDENCE_SECRET_PATTERNS.items():
            if pattern.search(content):
                errors.append(f"{relative}: 检测到疑似 {description}")
        suspected_values = [
            match.group("value") for match in SECRET_ASSIGNMENT_PATTERN.finditer(content)
        ]
        if (
            path.suffix.casefold() in UNQUOTED_SECRET_TEXT_SUFFIXES
            or lower_name.startswith(".env")
        ):
            suspected_values.extend(
                match.group("value")
                for match in UNQUOTED_SECRET_ASSIGNMENT_PATTERN.finditer(content)
            )
        suspected_values.extend(
            match.group("value")
            for match in SET_PARAM_LITERAL_PATTERN.finditer(content)
            if SECRET_CONFIG_KEY_PATTERN.search(match.group("key"))
        )
        for raw_value in suspected_values:
            value = raw_value.casefold()
            if not any(marker in value for marker in PLACEHOLDER_MARKERS):
                errors.append(f"{relative}: 检测到疑似硬编码密钥、令牌或密码")
                break

    for markdown_path in (path for path in files if path.suffix.lower() == ".md"):
        errors.extend(_check_markdown_links(markdown_path, root))
    return errors


def _check_markdown_links(path: Path, root: Path) -> list[str]:
    errors: list[str] = []
    try:
        text = _read_text(path)
    except (OSError, UnicodeError):
        return errors
    targets = MARKDOWN_LINK_PATTERN.findall(text) + HTML_ASSET_PATTERN.findall(text)
    for raw_target in targets:
        target = raw_target.strip()
        if target.startswith("<") and ">" in target:
            target = target[1 : target.index(">")]
        else:
            target = target.split(maxsplit=1)[0]
        if (
            not target
            or target.startswith(("#", "/", "http://", "https://", "mailto:"))
            or "://" in target
        ):
            continue
        target = unquote(target.split("#", 1)[0].split("?", 1)[0])
        if not target:
            continue
        candidate = path.parent / target
        if not candidate.exists():
            errors.append(
                f"{_relative(path, root)}: 本地链接不存在：{raw_target!r}"
            )
    return errors


def validate_repository(
    root: Path = REPOSITORY_ROOT, *, require_repository_files: bool = True
) -> list[str]:
    """Return every deterministic standard violation in stable order."""

    root = root.resolve()
    paths, errors = discover_module_paths(root)
    modules: list[ModuleInfo] = []
    for path in paths:
        if not MODULE_NAME_PATTERN.fullmatch(path.name):
            errors.append(f"{path.name}: 技术名不符合 {MODULE_NAME_PATTERN.pattern}")
            continue
        try:
            manifest = parse_manifest(path / "__manifest__.py")
        except StandardError as exc:
            errors.append(str(exc))
            continue
        module = ModuleInfo(path.name, path, manifest)
        modules.append(module)
        errors.extend(_check_manifest(module, root))
        errors.extend(_check_module_files(module, root))
    errors.extend(_check_module_pairs(modules))
    if require_repository_files:
        files = _repository_files(root)
        errors.extend(_check_repository_files(root, modules, files))
    return sorted(set(errors))


def format_module_list(modules: Iterable[ModuleInfo], output_format: str) -> str:
    modules = list(modules)
    names = [module.name for module in modules]
    if output_format == "csv":
        return ",".join(names)
    if output_format == "lines":
        return "\n".join(names)
    if output_format == "test-tags":
        return ",".join(f"/{name}" for name in names)
    if output_format == "hoot-modules":
        return ",".join(module.name for module in modules if module.has_hoot_tests)
    if output_format == "hoot-tags":
        return ",".join(
            f"/web:WebSuite.test_unit_desktop[@{module.name}]"
            for module in modules
            if module.has_hoot_tests
        )
    raise ValueError(f"未知输出格式：{output_format}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="自动发现 OdooCC 模块并执行仓库规范检查。"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser("check", help="检查全部模块和仓库文件")
    check_parser.add_argument(
        "--root", type=Path, default=REPOSITORY_ROOT, help=argparse.SUPPRESS
    )

    list_parser = subparsers.add_parser("list", help="输出自动发现的模块")
    list_parser.add_argument(
        "--root", type=Path, default=REPOSITORY_ROOT, help=argparse.SUPPRESS
    )
    list_parser.add_argument(
        "--format",
        choices=("csv", "lines", "test-tags", "hoot-modules", "hoot-tags"),
        default="lines",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    root = args.root.resolve()
    if args.command == "check":
        errors = validate_repository(root)
        if errors:
            print("OdooCC 规范检查失败：", file=sys.stderr)
            for error in errors:
                print(f"- {error}", file=sys.stderr)
            return 1
        modules = load_modules_for_output(root)
        print(f"OdooCC 规范检查通过：{len(modules)} 个模块")
        return 0

    try:
        modules = load_modules_for_output(root)
    except StandardError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(format_module_list(modules, args.format))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
