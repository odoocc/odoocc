import ast
import io
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr
from dataclasses import replace
from pathlib import Path
from unittest import mock
from xml.etree import ElementTree

from tools import scaffold_module
from tools.check_modules import validate_repository
from tools.scaffold_module import (
    ScaffoldError,
    ScaffoldSpec,
    create_modules,
    normalize_dependencies,
    render_scaffold,
)


class TestScaffoldModule(unittest.TestCase):
    @staticmethod
    def _spec(module_name="occ_quality_trace"):
        return ScaffoldSpec(
            module_name=module_name,
            title="质量追溯",
            summary="追踪批次、工序和质量事件",
            summary_en="Trace lots, operations, and quality events.",
            description="为制造企业提供可审计的质量追溯基础能力。",
            demo_category="supply_manufacturing",
            category="Manufacturing",
            dependencies=("mrp", "stock"),
            demo_keywords=("质量追溯", "批次"),
        )

    def test_create_pair_is_valid_and_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            result = create_modules(self._spec(), root=root)

            self.assertEqual(result.status, "created")
            formal = root / "occ_quality_trace"
            acceptance = root / "occ_quality_trace_test"
            self.assertTrue(formal.is_dir())
            self.assertTrue(acceptance.is_dir())

            formal_manifest = ast.literal_eval(
                (formal / "__manifest__.py").read_text(encoding="utf-8")
            )
            acceptance_manifest = ast.literal_eval(
                (acceptance / "__manifest__.py").read_text(encoding="utf-8")
            )
            self.assertEqual(formal_manifest["author"], "Odoo老赵")
            self.assertEqual(formal_manifest["depends"], ["mrp", "stock"])
            self.assertFalse(
                any(
                    dependency.endswith("_test")
                    for dependency in formal_manifest["depends"]
                )
            )
            self.assertEqual(
                acceptance_manifest["depends"],
                ["occ_quality_trace"],
            )
            self.assertIs(acceptance_manifest["auto_install"], False)
            self.assertEqual(
                acceptance_manifest["odoocc_demo"],
                {
                    "schema_version": 1,
                    "category": "supply_manufacturing",
                    "sequence": 100,
                    "menu_xmlid": (
                        "occ_quality_trace_test.menu_acceptance_root"
                    ),
                    "entry_menu_xmlid": (
                        "occ_quality_trace_test.menu_acceptance_check"
                    ),
                    "keywords": ["质量追溯", "批次"],
                },
            )
            self.assertNotIn("odoocc_demo", formal_manifest)

            for python_path in root.rglob("*.py"):
                compile(
                    python_path.read_text(encoding="utf-8"),
                    str(python_path),
                    "exec",
                )
            for xml_path in root.rglob("*.xml"):
                ElementTree.parse(xml_path)

            self.assertEqual(
                validate_repository(root, require_repository_files=False),
                [],
            )
            repeated = create_modules(self._spec(), root=root)
            self.assertEqual(repeated.status, "unchanged")

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            result = create_modules(self._spec(), root=root, dry_run=True)

            self.assertEqual(result.status, "planned")
            self.assertFalse((root / "occ_quality_trace").exists())
            self.assertFalse((root / "occ_quality_trace_test").exists())

    def test_conflict_never_overwrites_existing_content(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            create_modules(self._spec(), root=root)
            manifest_path = root / "occ_quality_trace" / "__manifest__.py"
            manifest_before = manifest_path.read_bytes()
            readme_path = root / "occ_quality_trace" / "README.md"
            readme_path.write_text("用户已经修改\n", encoding="utf-8")

            with self.assertRaisesRegex(ScaffoldError, "已有内容不同"):
                create_modules(self._spec(), root=root)

            self.assertEqual(manifest_path.read_bytes(), manifest_before)
            self.assertEqual(
                readme_path.read_text(encoding="utf-8"),
                "用户已经修改\n",
            )

    def test_partial_target_is_rejected_without_filling_it(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            partial = root / "occ_quality_trace"
            partial.mkdir()

            with self.assertRaisesRegex(ScaffoldError, "只存在部分目标目录"):
                create_modules(self._spec(), root=root)

            self.assertEqual(list(partial.iterdir()), [])
            self.assertFalse((root / "occ_quality_trace_test").exists())

    def test_invalid_or_unsafe_names_are_rejected(self):
        invalid_names = (
            "quality_trace",
            "occ_Quality",
            "occ_quality-trace",
            "occ_quality__trace",
            "occ_quality_trace_test",
            "occ_" + "a" * 70,
        )
        for module_name in invalid_names:
            with self.subTest(module_name=module_name), self.assertRaises(
                ScaffoldError
            ):
                self._spec(module_name).validate()

    def test_dependencies_accept_repeatable_and_comma_separated_values(self):
        self.assertEqual(
            normalize_dependencies(["mrp,stock", "mail", "stock"]),
            ("mrp", "stock", "mail"),
        )
        self.assertEqual(normalize_dependencies([]), ("base",))
        with self.assertRaisesRegex(ScaffoldError, "依赖不得重复"):
            replace(
                self._spec(),
                dependencies=("base", "base"),
            ).validate()

    def test_demo_contract_inputs_are_strictly_validated(self):
        invalid_specs = (
            replace(self._spec(), demo_category="unknown"),
            replace(self._spec(), demo_sequence=-1),
            replace(self._spec(), demo_sequence=0),
            replace(self._spec(), demo_sequence=True),
            replace(self._spec(), demo_keywords=("",)),
            replace(self._spec(), demo_keywords=(" 质量",)),
            replace(self._spec(), demo_keywords=("质量", "质量")),
            replace(self._spec(), demo_keywords=("x" * 41,)),
            replace(self._spec(), demo_keywords=tuple(str(i) for i in range(13))),
        )
        for spec in invalid_specs:
            with self.subTest(spec=spec), self.assertRaises(ScaffoldError):
                spec.validate()

    def test_cli_requires_demo_category(self):
        parser = scaffold_module._build_parser()
        arguments = [
            "create",
            "occ_quality_trace",
            "--title",
            "质量追溯",
            "--summary",
            "追踪质量事件",
            "--summary-en",
            "Trace quality events.",
            "--description",
            "质量追溯基础能力。",
        ]

        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(arguments)

        parsed = parser.parse_args(
            arguments
            + [
                "--demo-category",
                "supply_manufacturing",
                "--demo-keyword",
                "质量",
                "--demo-keyword",
                "批次",
            ]
        )
        self.assertEqual(parsed.demo_sequence, 100)
        self.assertEqual(parsed.demo_keyword, ["质量", "批次"])

    def test_quotes_in_user_text_are_safely_rendered(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            spec = replace(
                self._spec(),
                title='质量 "Alpha" \\ 追溯',
                description='支持 "双引号"、\\路径与中文。',
            )

            create_modules(spec, root=root)

            for python_path in root.rglob("*.py"):
                compile(
                    python_path.read_text(encoding="utf-8"),
                    str(python_path),
                    "exec",
                )
            acceptance_model = (
                root
                / "occ_quality_trace_test"
                / "models"
                / "acceptance_check.py"
            ).read_text(encoding="utf-8")
            self.assertIn(r'质量 \"Alpha\" \\ 追溯', acceptance_model)

    def test_xml_10_illegal_characters_are_rejected_before_writing(self):
        invalid_specs = (
            replace(self._spec(), title="质量\x0b追溯"),
            replace(self._spec(), description="质量追溯\ud800"),
        )
        for spec in invalid_specs:
            with self.subTest(value=repr(spec)), self.assertRaisesRegex(
                ScaffoldError, "XML 1.0 非法字符"
            ):
                spec.validate()

    def test_rendered_python_is_validated_before_repository_writes(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            template_root = Path(temporary_directory) / "templates"
            shutil.copytree(scaffold_module.TEMPLATE_ROOT, template_root)
            (template_root / "formal" / "__init__.py.tmpl").write_text(
                '"unterminated\n',
                encoding="utf-8",
            )

            with mock.patch.object(scaffold_module, "TEMPLATE_ROOT", template_root):
                with self.assertRaisesRegex(ScaffoldError, "静态校验失败"):
                    render_scaffold(self._spec())

    def test_target_appearing_during_creation_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            original_existing_state = scaffold_module._existing_state

            def create_racing_target(root_path, targets, rendered):
                state = original_existing_state(root_path, targets, rendered)
                targets[1].mkdir()
                return state

            with mock.patch.object(
                scaffold_module,
                "_existing_state",
                side_effect=create_racing_target,
            ):
                with self.assertRaisesRegex(ScaffoldError, "拒绝覆盖"):
                    create_modules(self._spec(), root=root)

            self.assertFalse((root / "occ_quality_trace").exists())
            self.assertEqual(list((root / "occ_quality_trace_test").iterdir()), [])
            self.assertEqual(list(root.glob(".odoocc-scaffold-*")), [])

    def test_failed_rollback_preserves_recovery_staging(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            formal_target = root / "occ_quality_trace"
            original_existing_state = scaffold_module._existing_state
            original_rmdir = Path.rmdir

            def create_racing_target(root_path, targets, rendered):
                state = original_existing_state(root_path, targets, rendered)
                targets[1].mkdir()
                return state

            def fail_formal_rollback(path):
                if path == formal_target:
                    raise OSError("simulated rollback failure")
                return original_rmdir(path)

            with mock.patch.object(
                scaffold_module,
                "_existing_state",
                side_effect=create_racing_target,
            ), mock.patch.object(Path, "rmdir", fail_formal_rollback):
                with self.assertRaisesRegex(
                    ScaffoldError, "回滚不完整.*恢复现场"
                ):
                    create_modules(self._spec(), root=root)

            recovery_directories = list(root.glob(".odoocc-scaffold-*"))
            self.assertEqual(len(recovery_directories), 1)
            self.assertTrue(
                (recovery_directories[0] / "occ_quality_trace").is_dir()
            )
            self.assertTrue(formal_target.is_dir())

    def test_keyboard_interrupt_rolls_back_and_keeps_interrupt_semantics(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            original_reserve_directory = scaffold_module._reserve_directory

            def interrupt_on_second_target(path):
                if path == root / "occ_quality_trace_test":
                    raise KeyboardInterrupt
                return original_reserve_directory(path)

            with mock.patch.object(
                scaffold_module,
                "_reserve_directory",
                side_effect=interrupt_on_second_target,
            ):
                with self.assertRaises(KeyboardInterrupt):
                    create_modules(self._spec(), root=root)

            self.assertFalse((root / "occ_quality_trace").exists())
            self.assertFalse((root / "occ_quality_trace_test").exists())
            self.assertEqual(list(root.glob(".odoocc-scaffold-*")), [])

    def test_incomplete_interrupt_rollback_keeps_recovery_path_in_note(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            formal_target = root / "occ_quality_trace"
            original_reserve_directory = scaffold_module._reserve_directory
            original_rmdir = Path.rmdir

            def interrupt_on_second_target(path):
                if path == root / "occ_quality_trace_test":
                    raise KeyboardInterrupt
                return original_reserve_directory(path)

            def fail_formal_rollback(path):
                if path == formal_target:
                    raise OSError("simulated interrupt rollback failure")
                return original_rmdir(path)

            with mock.patch.object(
                scaffold_module,
                "_reserve_directory",
                side_effect=interrupt_on_second_target,
            ), mock.patch.object(Path, "rmdir", fail_formal_rollback):
                with self.assertRaises(KeyboardInterrupt) as caught:
                    create_modules(self._spec(), root=root)

            notes = getattr(caught.exception, "__notes__", caught.exception.args)
            self.assertTrue(any("恢复现场" in str(note) for note in notes))
            self.assertEqual(len(list(root.glob(".odoocc-scaffold-*"))), 1)
            self.assertTrue(formal_target.is_dir())

    def test_rollback_never_deletes_a_concurrently_edited_file(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            readme_path = root / "occ_quality_trace" / "README.md"
            original_reserve_directory = scaffold_module._reserve_directory

            def edit_then_fail(path):
                if path == root / "occ_quality_trace" / "tests":
                    readme_path.write_text("并发用户修改\n", encoding="utf-8")
                    raise OSError("simulated later write failure")
                return original_reserve_directory(path)

            with mock.patch.object(
                scaffold_module,
                "_reserve_directory",
                side_effect=edit_then_fail,
            ):
                with self.assertRaisesRegex(
                    ScaffoldError, "回滚不完整.*恢复现场"
                ):
                    create_modules(self._spec(), root=root)

            self.assertEqual(
                readme_path.read_text(encoding="utf-8"),
                "并发用户修改\n",
            )
            self.assertEqual(len(list(root.glob(".odoocc-scaffold-*"))), 1)


if __name__ == "__main__":
    unittest.main()
