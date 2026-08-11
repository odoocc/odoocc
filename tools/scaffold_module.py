#!/usr/bin/env python3
"""Create a production module and its installable OdooCC acceptance companion."""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import io
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from string import Template
from xml.etree import ElementTree
from xml.sax.saxutils import escape as xml_escape

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.check_modules import (
    MODULE_NAME_PATTERN,
    ODOOCC_DEMO_CATEGORIES,
    ODOOCC_DEMO_KEYWORD_MAX_COUNT,
    ODOOCC_DEMO_KEYWORD_MAX_LENGTH,
    ODOOCC_DEMO_SCHEMA_VERSION,
    ODOOCC_DEMO_SEQUENCE_MAX,
    ODOOCC_DEMO_SEQUENCE_MIN,
    REPOSITORY_ROOT,
)


TEMPLATE_ROOT = Path(__file__).resolve().parent / "templates"
DEPENDENCY_PATTERN = rf"^[a-z0-9]+(?:_[a-z0-9]+)*$"
INITIAL_VERSION = "19.0.1.0.0"


class ScaffoldError(RuntimeError):
    """Raised when scaffolding would be unsafe or ambiguous."""


@dataclass(frozen=True)
class _CreatedPath:
    """A path created by this process, identified without following symlinks."""

    path: Path
    device: int
    inode: int
    expected_digest: bytes | None = None


@dataclass(frozen=True)
class ScaffoldSpec:
    module_name: str
    title: str
    summary: str
    summary_en: str
    description: str
    demo_category: str
    category: str = "Tools"
    dependencies: tuple[str, ...] = ("base",)
    demo_sequence: int = 100
    demo_keywords: tuple[str, ...] = ()

    @property
    def test_module_name(self) -> str:
        return f"{self.module_name}_test"

    @property
    def domain_parts(self) -> tuple[str, ...]:
        return tuple(self.module_name.removeprefix("occ_").split("_"))

    @property
    def class_prefix(self) -> str:
        return "Occ" + "".join(
            part[:1].upper() + part[1:] for part in self.domain_parts
        )

    @property
    def acceptance_model(self) -> str:
        return f"occ.{'.'.join(self.domain_parts)}.acceptance.check"

    @property
    def acceptance_model_xmlid(self) -> str:
        return f"model_{self.acceptance_model.replace('.', '_')}"

    def validate(self) -> None:
        if not MODULE_NAME_PATTERN.fullmatch(self.module_name):
            raise ScaffoldError(
                f"模块名必须匹配 {MODULE_NAME_PATTERN.pattern}：{self.module_name!r}"
            )
        if self.module_name.endswith("_test"):
            raise ScaffoldError("请输入正式模块名；脚手架会自动创建 _test 模块")
        for field_name, value in (
            ("title", self.title),
            ("summary", self.summary),
            ("summary_en", self.summary_en),
            ("description", self.description),
            ("category", self.category),
        ):
            if not value or not value.strip():
                raise ScaffoldError(f"{field_name} 不得为空")
            invalid_codepoint = _first_invalid_xml_codepoint(value)
            if invalid_codepoint is not None:
                raise ScaffoldError(
                    f"{field_name} 包含 XML 1.0 非法字符 "
                    f"U+{invalid_codepoint:04X}"
                )
        for field_name, value in (
            ("title", self.title),
            ("summary", self.summary),
            ("summary_en", self.summary_en),
            ("category", self.category),
        ):
            if "\n" in value or "\r" in value:
                raise ScaffoldError(f"{field_name} 必须是单行文本")
        if len(self.summary) > 120:
            raise ScaffoldError("summary 不得超过 120 个字符")
        if (
            not isinstance(self.demo_category, str)
            or self.demo_category not in ODOOCC_DEMO_CATEGORIES
        ):
            raise ScaffoldError(
                "demo_category 必须是七个允许值之一："
                f"{', '.join(ODOOCC_DEMO_CATEGORIES)}"
            )
        if (
            isinstance(self.demo_sequence, bool)
            or not isinstance(self.demo_sequence, int)
            or not ODOOCC_DEMO_SEQUENCE_MIN
            <= self.demo_sequence
            <= ODOOCC_DEMO_SEQUENCE_MAX
        ):
            raise ScaffoldError(
                "demo_sequence 必须是 "
                f"{ODOOCC_DEMO_SEQUENCE_MIN}..{ODOOCC_DEMO_SEQUENCE_MAX} 的整数"
            )
        if len(self.demo_keywords) > ODOOCC_DEMO_KEYWORD_MAX_COUNT:
            raise ScaffoldError(
                "demo_keyword 不得超过 "
                f"{ODOOCC_DEMO_KEYWORD_MAX_COUNT} 项"
            )
        seen_keywords: set[str] = set()
        for keyword in self.demo_keywords:
            if not isinstance(keyword, str):
                raise ScaffoldError("demo_keyword 必须是字符串")
            invalid_codepoint = _first_invalid_xml_codepoint(keyword)
            if invalid_codepoint is not None:
                raise ScaffoldError(
                    "demo_keyword 包含 XML 1.0 非法字符 "
                    f"U+{invalid_codepoint:04X}"
                )
            if (
                not keyword.strip()
                or keyword != keyword.strip()
                or "\n" in keyword
                or "\r" in keyword
                or len(keyword) > ODOOCC_DEMO_KEYWORD_MAX_LENGTH
            ):
                raise ScaffoldError(
                    "demo_keyword 必须是最长 "
                    f"{ODOOCC_DEMO_KEYWORD_MAX_LENGTH} 字符的非空单行文本"
                )
            normalized_keyword = keyword.casefold()
            if normalized_keyword in seen_keywords:
                raise ScaffoldError(f"demo_keyword 不得重复：{keyword!r}")
            seen_keywords.add(normalized_keyword)
        if not self.dependencies:
            raise ScaffoldError("至少需要一个直接依赖；无额外依赖时使用 base")
        seen_dependencies: set[str] = set()
        for dependency in self.dependencies:
            if not _valid_dependency(dependency):
                raise ScaffoldError(f"无效依赖名：{dependency!r}")
            if dependency in seen_dependencies:
                raise ScaffoldError(f"依赖不得重复：{dependency!r}")
            seen_dependencies.add(dependency)
            if dependency == self.module_name:
                raise ScaffoldError("模块不得依赖自身")
            if dependency.endswith("_test"):
                raise ScaffoldError("正式模块不得依赖 _test 模块")
        table_name = self.acceptance_model.replace(".", "_")
        if len(table_name.encode("utf-8")) > 63:
            raise ScaffoldError(
                "派生验收模型的数据表名超过 PostgreSQL 63 字节限制，"
                "请缩短模块名"
            )


@dataclass(frozen=True)
class ScaffoldResult:
    status: str
    targets: tuple[Path, Path]


def _valid_dependency(value: str) -> bool:
    return bool(re.fullmatch(DEPENDENCY_PATTERN, value))


def _first_invalid_xml_codepoint(value: str) -> int | None:
    """Return the first character forbidden by the XML 1.0 Char production."""

    for character in value:
        codepoint = ord(character)
        if (
            codepoint in {0x09, 0x0A, 0x0D}
            or 0x20 <= codepoint <= 0xD7FF
            or 0xE000 <= codepoint <= 0xFFFD
            or 0x10000 <= codepoint <= 0x10FFFF
        ):
            continue
        return codepoint
    return None


def normalize_dependencies(raw_dependencies: list[str]) -> tuple[str, ...]:
    """Split repeatable/comma-separated CLI values and preserve first occurrence."""

    values: list[str] = []
    seen: set[str] = set()
    for raw_dependency in raw_dependencies or ["base"]:
        for dependency in raw_dependency.split(","):
            dependency = dependency.strip()
            if dependency and dependency not in seen:
                values.append(dependency)
                seen.add(dependency)
    return tuple(values)


def _json_literal(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _template_context(spec: ScaffoldSpec) -> dict[str, str]:
    test_description = (
        f"为 {spec.module_name} 提供管理员可维护的脱敏人工验收清单，"
        "验证安装、配置、核心流程和权限边界。"
    )
    return {
        "module_name": spec.module_name,
        "test_module_name": spec.test_module_name,
        "title": spec.title,
        "summary": spec.summary,
        "summary_en": spec.summary_en,
        "description": spec.description,
        "category": spec.category,
        "version": INITIAL_VERSION,
        "class_prefix": spec.class_prefix,
        "acceptance_model": spec.acceptance_model,
        "acceptance_model_xmlid": spec.acceptance_model_xmlid,
        "display_name_literal": _json_literal(f"OdooCC {spec.title}"),
        "test_display_name_literal": _json_literal(f"OdooCC {spec.title}验收"),
        "summary_literal": _json_literal(spec.summary),
        "test_summary_literal": _json_literal(
            f"验收 OdooCC {spec.title}的公开业务契约"
        ),
        "description_literal": _json_literal(spec.description),
        "test_description_literal": _json_literal(test_description),
        "acceptance_description_literal": _json_literal(
            f"OdooCC {spec.title} Acceptance Check"
        ),
        "category_literal": _json_literal(spec.category),
        "dependencies_literal": _json_literal(list(spec.dependencies)),
        "test_dependencies_literal": _json_literal([spec.module_name]),
        "demo_schema_version": str(ODOOCC_DEMO_SCHEMA_VERSION),
        "demo_category": spec.demo_category,
        "demo_category_literal": _json_literal(spec.demo_category),
        "demo_category_label": ODOOCC_DEMO_CATEGORIES[spec.demo_category],
        "demo_sequence": str(spec.demo_sequence),
        "demo_menu_xmlid_literal": _json_literal(
            f"{spec.test_module_name}.menu_acceptance_root"
        ),
        "demo_entry_menu_xmlid_literal": _json_literal(
            f"{spec.test_module_name}.menu_acceptance_check"
        ),
        "demo_keywords_literal": _json_literal(list(spec.demo_keywords)),
        "xml_title": xml_escape(spec.title, {'"': "&quot;", "'": "&apos;"}),
        "xml_summary": xml_escape(spec.summary, {'"': "&quot;", "'": "&apos;"}),
        "xml_description": xml_escape(
            spec.description, {'"': "&quot;", "'": "&apos;"}
        ),
    }


def render_scaffold(spec: ScaffoldSpec) -> dict[Path, str]:
    """Render every managed file in memory before touching the destination."""

    spec.validate()
    context = _template_context(spec)
    rendered: dict[Path, str] = {}
    profiles = (
        ("formal", spec.module_name),
        ("acceptance", spec.test_module_name),
    )
    for profile, target_name in profiles:
        profile_root = TEMPLATE_ROOT / profile
        if not profile_root.is_dir():
            raise ScaffoldError(f"脚手架模板目录不存在：{profile_root}")
        template_paths = sorted(profile_root.rglob("*.tmpl"))
        if not template_paths:
            raise ScaffoldError(f"脚手架模板目录为空：{profile_root}")
        for template_path in template_paths:
            relative = template_path.relative_to(profile_root)
            output_name = relative.name.removesuffix(".tmpl")
            output_path = Path(target_name) / relative.with_name(output_name)
            try:
                content = Template(
                    template_path.read_text(encoding="utf-8")
                ).substitute(context)
            except (OSError, KeyError, ValueError) as exc:
                raise ScaffoldError(f"模板渲染失败 {template_path}: {exc}") from exc
            if not content.endswith("\n"):
                content += "\n"
            if output_path in rendered:
                raise ScaffoldError(f"模板输出路径重复：{output_path}")
            rendered[output_path] = content
    _validate_rendered(rendered)
    return rendered


def _validate_rendered(rendered: dict[Path, str]) -> None:
    """Validate the complete scaffold in memory before any repository write."""

    errors: list[str] = []
    for relative, content in sorted(rendered.items()):
        label = relative.as_posix()
        if relative.is_absolute() or ".." in relative.parts:
            errors.append(f"{label}: 输出路径不得越出模块")
            continue
        if relative.suffix == ".py":
            try:
                compile(content, label, "exec")
            except (SyntaxError, ValueError) as exc:
                errors.append(f"{label}: Python 语法错误：{exc}")
                continue
            if relative.name == "__manifest__.py":
                try:
                    manifest = ast.literal_eval(content)
                except (SyntaxError, ValueError) as exc:
                    errors.append(f"{label}: Manifest 无法解析：{exc}")
                else:
                    if not isinstance(manifest, dict):
                        errors.append(f"{label}: Manifest 顶层必须是字典")
        elif relative.suffix in {".xml", ".svg"}:
            try:
                ElementTree.fromstring(content)
            except ElementTree.ParseError as exc:
                errors.append(f"{label}: XML/SVG 无法解析：{exc}")
        elif relative.suffix == ".csv":
            try:
                rows = list(csv.reader(io.StringIO(content, newline="")))
            except csv.Error as exc:
                errors.append(f"{label}: CSV 无法解析：{exc}")
                continue
            if not rows or not rows[0]:
                errors.append(f"{label}: CSV 必须包含表头")
                continue
            width = len(rows[0])
            for row_number, row in enumerate(rows[1:], start=2):
                if len(row) != width:
                    errors.append(f"{label}:{row_number}: CSV 列数与表头不一致")
    if errors:
        details = "\n".join(f"- {error}" for error in errors)
        raise ScaffoldError(f"生成内容静态校验失败：\n{details}")


def _check_root(root: Path) -> Path:
    expanded = root.expanduser().absolute()
    if expanded.is_symlink():
        raise ScaffoldError(f"仓库根目录不得是符号链接：{expanded}")
    if not expanded.is_dir():
        raise ScaffoldError(f"仓库根目录不存在：{expanded}")
    return expanded.resolve()


def _existing_state(
    root: Path, targets: tuple[Path, Path], rendered: dict[Path, str]
) -> str:
    existing = [target for target in targets if target.exists() or target.is_symlink()]
    if not existing:
        return "create"
    if len(existing) != len(targets):
        names = ", ".join(path.name for path in existing)
        raise ScaffoldError(f"只存在部分目标目录，拒绝补写：{names}")
    conflicts: list[str] = []
    for target in targets:
        if target.is_symlink() or not target.is_dir():
            conflicts.append(f"{target.name} 不是普通目录")
    for relative, expected in rendered.items():
        path = root / relative
        if path.is_symlink() or not path.is_file():
            conflicts.append(f"{relative.as_posix()} 缺失")
            continue
        try:
            actual = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            conflicts.append(f"{relative.as_posix()} 无法读取：{exc}")
            continue
        if actual != expected:
            conflicts.append(f"{relative.as_posix()} 已有内容不同")
    if conflicts:
        details = "\n".join(f"- {conflict}" for conflict in conflicts)
        raise ScaffoldError(f"目标存在冲突，未修改任何文件：\n{details}")
    return "unchanged"


def _created_path(path: Path) -> _CreatedPath:
    metadata = path.lstat()
    return _CreatedPath(path, metadata.st_dev, metadata.st_ino)


def _same_created_path(created: _CreatedPath, *, directory: bool) -> bool:
    try:
        metadata = created.path.lstat()
    except FileNotFoundError:
        return False
    expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    return (
        expected_type(metadata.st_mode)
        and metadata.st_dev == created.device
        and metadata.st_ino == created.inode
    )


def _write_recovery_staging(
    root: Path, rendered: dict[Path, str]
) -> Path:
    staging = Path(tempfile.mkdtemp(prefix=".odoocc-scaffold-", dir=root))
    try:
        for relative, content in rendered.items():
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
    except Exception as exc:
        try:
            shutil.rmtree(staging)
        except OSError as cleanup_exc:
            raise ScaffoldError(
                f"准备脚手架失败，临时目录清理失败，已保留现场 {staging}: "
                f"{cleanup_exc}"
            ) from exc
        raise ScaffoldError(f"准备脚手架失败，未修改目标目录：{exc}") from exc
    return staging


def _reserve_directory(path: Path) -> _CreatedPath:
    # mkdir(exist_ok=False) safely rejects ordinary concurrent creators. The
    # portable stdlib cannot make mkdir return a directory fd, so a hostile
    # same-user process that removes and replaces the directory in the tiny
    # mkdir-to-lstat window is outside this cooperative concurrency guarantee.
    try:
        path.mkdir(mode=0o755, exist_ok=False)
    except FileExistsError as exc:
        raise ScaffoldError(f"目标在生成期间出现，拒绝覆盖：{path}") from exc
    return _created_path(path)


def _materialize_rendered(
    root: Path,
    targets: tuple[Path, Path],
    rendered: dict[Path, str],
    created_files: list[_CreatedPath],
    created_directories: list[_CreatedPath],
) -> None:
    """Reserve both module roots and create every path exclusively."""

    known_directories: set[Path] = set()

    for target in targets:
        created = _reserve_directory(target)
        created_directories.append(created)
        known_directories.add(target)

    target_names = {target.name for target in targets}
    for relative, content in sorted(rendered.items()):
        if not relative.parts or relative.parts[0] not in target_names:
            raise ScaffoldError(f"模板输出不属于目标模块：{relative}")
        destination = root / relative
        current = root / relative.parts[0]
        for part in relative.parts[1:-1]:
            current /= part
            if current in known_directories:
                continue
            created = _reserve_directory(current)
            created_directories.append(created)
            known_directories.add(current)
        try:
            with destination.open("x", encoding="utf-8", newline="") as stream:
                metadata = os.fstat(stream.fileno())
                created_files.append(
                    _CreatedPath(
                        destination,
                        metadata.st_dev,
                        metadata.st_ino,
                        hashlib.sha256(content.encode("utf-8")).digest(),
                    )
                )
                stream.write(content)
        except FileExistsError as exc:
            raise ScaffoldError(
                f"目标文件在生成期间出现，拒绝覆盖：{destination}"
            ) from exc


def _rollback_created_paths(
    created_files: list[_CreatedPath],
    created_directories: list[_CreatedPath],
) -> list[str]:
    """Remove only paths that still have the inode created by this process."""

    errors: list[str] = []
    for created in reversed(created_files):
        if not created.path.exists() and not created.path.is_symlink():
            continue
        if not _same_created_path(created, directory=False):
            errors.append(f"{created.path}: 已被并发替换，未删除")
            continue
        if created.expected_digest is not None:
            try:
                actual_digest = hashlib.sha256(created.path.read_bytes()).digest()
            except OSError as exc:
                errors.append(f"{created.path}: 回读失败，未删除：{exc}")
                continue
            if actual_digest != created.expected_digest:
                errors.append(f"{created.path}: 内容已被并发修改，未删除")
                continue
            if not _same_created_path(created, directory=False):
                errors.append(f"{created.path}: 回读后被并发替换，未删除")
                continue
        try:
            created.path.unlink()
        except OSError as exc:
            errors.append(f"{created.path}: 删除失败：{exc}")
    for created in reversed(created_directories):
        if not created.path.exists() and not created.path.is_symlink():
            continue
        if not _same_created_path(created, directory=True):
            errors.append(f"{created.path}: 已被并发替换，未删除")
            continue
        try:
            created.path.rmdir()
        except OSError as exc:
            errors.append(f"{created.path}: 删除失败：{exc}")
    return errors


def _add_recovery_note(exc: BaseException, message: str) -> None:
    """Annotate interrupts without changing their type or shell exit semantics."""

    if hasattr(exc, "add_note"):
        exc.add_note(message)
    else:  # pragma: no cover - Python 3.10 compatibility fallback
        exc.args = (*exc.args, message)


def create_modules(
    spec: ScaffoldSpec,
    *,
    root: Path = REPOSITORY_ROOT,
    dry_run: bool = False,
) -> ScaffoldResult:
    """Create both modules without ever replacing a path that already exists."""

    root = _check_root(root)
    rendered = render_scaffold(spec)
    targets = (root / spec.module_name, root / spec.test_module_name)
    state = _existing_state(root, targets, rendered)
    if state == "unchanged":
        return ScaffoldResult("unchanged", targets)
    if dry_run:
        return ScaffoldResult("planned", targets)

    staging = _write_recovery_staging(root, rendered)
    created_files: list[_CreatedPath] = []
    created_directories: list[_CreatedPath] = []
    try:
        _materialize_rendered(
            root,
            targets,
            rendered,
            created_files,
            created_directories,
        )
    except BaseException as exc:
        rollback_errors = _rollback_created_paths(
            created_files, created_directories
        )
        if rollback_errors:
            details = "\n".join(f"- {error}" for error in rollback_errors)
            message = (
                "写入脚手架失败，自动回滚不完整；"
                f"已保留恢复现场：{staging}\n{details}\n原始错误：{exc}"
            )
            if not isinstance(exc, Exception):
                _add_recovery_note(exc, message)
                raise
            raise ScaffoldError(message) from exc
        try:
            shutil.rmtree(staging)
        except OSError as cleanup_exc:
            message = (
                "写入脚手架失败，目标已回滚，但临时目录清理失败；"
                f"已保留恢复现场：{staging}：{cleanup_exc}"
            )
            if not isinstance(exc, Exception):
                _add_recovery_note(exc, message)
                raise
            raise ScaffoldError(message) from exc
        if isinstance(exc, ScaffoldError):
            raise exc
        if isinstance(exc, Exception):
            raise ScaffoldError(
                f"写入脚手架失败，已回滚本次目标：{exc}"
            ) from exc
        raise
    try:
        shutil.rmtree(staging)
    except OSError as exc:
        raise ScaffoldError(
            f"模块已完整创建，但临时恢复目录清理失败：{staging}：{exc}"
        ) from exc
    return ScaffoldResult("created", targets)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="成对创建 OdooCC 正式模块与可安装 _test 验收模块。"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_parser = subparsers.add_parser("create", help="创建一对新模块")
    create_parser.add_argument("module_name")
    create_parser.add_argument("--title", required=True, help="中文短标题")
    create_parser.add_argument("--summary", required=True, help="中文单行摘要")
    create_parser.add_argument(
        "--summary-en", required=True, help="英文单行摘要"
    )
    create_parser.add_argument(
        "--description", required=True, help="中文定位与功能边界"
    )
    create_parser.add_argument("--category", default="Tools")
    create_parser.add_argument(
        "--demo-category",
        required=True,
        choices=tuple(ODOOCC_DEMO_CATEGORIES),
        help="统一演示中心的二级分类",
    )
    create_parser.add_argument(
        "--demo-sequence",
        type=int,
        default=100,
        help="模块在演示分类中的排序（默认 100）",
    )
    create_parser.add_argument(
        "--demo-keyword",
        action="append",
        default=[],
        help="演示入口搜索关键词，可重复传入",
    )
    create_parser.add_argument(
        "--depends",
        action="append",
        default=[],
        help="可重复或使用逗号分隔；未提供时默认为 base",
    )
    create_parser.add_argument("--dry-run", action="store_true")
    create_parser.add_argument(
        "--root", type=Path, default=REPOSITORY_ROOT, help=argparse.SUPPRESS
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    spec = ScaffoldSpec(
        module_name=args.module_name,
        title=args.title.strip(),
        summary=args.summary.strip(),
        summary_en=args.summary_en.strip(),
        description=args.description.strip(),
        demo_category=args.demo_category,
        category=args.category.strip(),
        dependencies=normalize_dependencies(args.depends),
        demo_sequence=args.demo_sequence,
        demo_keywords=tuple(args.demo_keyword),
    )
    try:
        result = create_modules(spec, root=args.root, dry_run=args.dry_run)
    except ScaffoldError as exc:
        print(f"脚手架未执行：{exc}", file=sys.stderr)
        return 2
    action = {
        "created": "已创建",
        "planned": "将创建（dry-run，未写入）",
        "unchanged": "已存在且与模板一致，未修改",
    }[result.status]
    print(f"{action}：")
    for target in result.targets:
        print(f"- {target}")
    if result.status == "created":
        print(
            "下一步：实现真实业务能力、更新根 README，"
            "并运行规范检查和 Odoo 测试。"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
