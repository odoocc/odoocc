import ast
import tempfile
import unittest
from pathlib import Path

from tools import check_modules
from tools.check_modules import (
    format_module_list,
    load_modules_for_output,
    validate_repository,
)
from tools.scaffold_module import ScaffoldSpec, create_modules


class TestCheckModules(unittest.TestCase):
    @staticmethod
    def _create_pair(root):
        create_modules(
            ScaffoldSpec(
                module_name="occ_service_desk",
                title="服务台",
                summary="管理中小企业内部服务请求",
                summary_en="Manage internal service requests for small businesses.",
                description="提供可扩展的服务请求管理基础。",
                demo_category="customer_operations",
                dependencies=("base",),
                demo_keywords=("服务台", "工单"),
            ),
            root=root,
        )

    def test_discovery_formats_are_stable_and_shell_safe(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._create_pair(root)
            modules = load_modules_for_output(root)

            self.assertEqual(
                format_module_list(modules, "csv"),
                "occ_service_desk,occ_service_desk_test",
            )
            self.assertEqual(
                format_module_list(modules, "test-tags"),
                "/occ_service_desk,/occ_service_desk_test",
            )
            self.assertEqual(format_module_list(modules, "hoot-modules"), "")

    def test_checker_detects_an_unregistered_test_file(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._create_pair(root)
            extra_test = root / "occ_service_desk" / "tests" / "test_extra.py"
            extra_test.write_text(
                "\n".join(
                    [
                        "from odoo.tests import TransactionCase, tagged",
                        "",
                        '@tagged("post_install", "-at_install")',
                        "class TestExtra(TransactionCase):",
                        "    pass",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            errors = validate_repository(root, require_repository_files=False)

            self.assertTrue(
                any("未导入 test_extra" in error for error in errors),
                errors,
            )

    def test_checker_detects_metadata_and_pair_violations(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._create_pair(root)
            test_manifest_path = (
                root / "occ_service_desk_test" / "__manifest__.py"
            )
            manifest = test_manifest_path.read_text(encoding="utf-8")
            manifest = manifest.replace(
                '"auto_install": False',
                '"auto_install": True',
            ).replace(
                '"author": "Odoo老赵"',
                '"author": "Unknown"',
            )
            test_manifest_path.write_text(manifest, encoding="utf-8")

            errors = validate_repository(root, require_repository_files=False)

            self.assertTrue(
                any("auto_install 必须为 False" in error for error in errors),
                errors,
            )
            self.assertTrue(
                any("author 必须为" in error for error in errors),
                errors,
            )

    def test_checker_rejects_unbundled_or_mistagged_hoot_tests(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._create_pair(root)
            formal = root / "occ_service_desk"
            loaded_asset = formal / "static" / "src" / "loaded.js"
            loaded_asset.parent.mkdir(parents=True)
            loaded_asset.write_text(
                "// Loaded unit-test asset.\n",
                encoding="utf-8",
            )
            hoot_test = formal / "static" / "tests" / "service_desk.test.js"
            hoot_test.parent.mkdir(parents=True)
            hoot_test.write_text(
                "\n".join(
                    [
                        'import "@occ_service_desk/loaded";',
                        'describe.current.tags("headless", "wrong_tag");',
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            manifest_path = formal / "__manifest__.py"
            manifest = ast.literal_eval(manifest_path.read_text(encoding="utf-8"))
            manifest["assets"] = {
                "web.assets_unit_tests": [
                    "occ_service_desk/static/src/loaded.js",
                ]
            }
            manifest_path.write_text(repr(manifest) + "\n", encoding="utf-8")

            errors = validate_repository(root, require_repository_files=False)

            self.assertTrue(
                any("web.assets_unit_tests 未包含" in error for error in errors),
                errors,
            )
            self.assertTrue(
                any("同一个 describe.current.tags" in error for error in errors),
                errors,
            )

    def test_checker_only_accepts_active_hoot_tag_calls(self):
        cases = {
            "line_comment": (
                '// describe.current.tags("headless", "occ_service_desk");\n',
                False,
            ),
            "block_comment": (
                "/*\n"
                'describe.current.tags("headless", "occ_service_desk");\n'
                "*/\n",
                False,
            ),
            "template_string": (
                "const documentation = `\n"
                'describe.current.tags("headless", "occ_service_desk");\n'
                "`;\n",
                False,
            ),
            "headless_call": (
                "describe.current.tags(\n"
                '    "headless",\n'
                '    "occ_service_desk",\n'
                ");\n",
                True,
            ),
            "desktop_call": (
                'describe.current.tags("desktop", "occ_service_desk");\n',
                True,
            ),
            "module_only": (
                'describe.current.tags("occ_service_desk");\n',
                False,
            ),
            "split_calls": (
                'describe.current.tags("desktop");\n'
                'describe.current.tags("occ_service_desk");\n',
                False,
            ),
            "mutually_exclusive_execution_tags": (
                'describe.current.tags("headless", "desktop", "occ_service_desk");\n',
                False,
            ),
        }
        for label, (source, should_pass) in cases.items():
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    root = Path(temporary_directory)
                    self._create_pair(root)
                    formal = root / "occ_service_desk"
                    hoot_test = formal / "static" / "tests" / "service_desk.test.js"
                    hoot_test.parent.mkdir(parents=True)
                    hoot_test.write_text(source, encoding="utf-8")
                    manifest_path = formal / "__manifest__.py"
                    manifest = ast.literal_eval(
                        manifest_path.read_text(encoding="utf-8")
                    )
                    manifest["assets"] = {
                        "web.assets_unit_tests": [
                            "occ_service_desk/static/tests/**/*.js",
                        ]
                    }
                    manifest_path.write_text(
                        repr(manifest) + "\n",
                        encoding="utf-8",
                    )

                    errors = validate_repository(
                        root,
                        require_repository_files=False,
                    )
                    has_tag_error = any(
                        "同一个 describe.current.tags" in error for error in errors
                    )

                    self.assertEqual(has_tag_error, not should_pass, errors)

    def test_checker_reports_non_string_dependency_without_crashing(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._create_pair(root)
            manifest_path = root / "occ_service_desk" / "__manifest__.py"
            manifest = ast.literal_eval(manifest_path.read_text(encoding="utf-8"))
            manifest["depends"] = ["base", 123]
            manifest_path.write_text(repr(manifest) + "\n", encoding="utf-8")

            errors = validate_repository(root, require_repository_files=False)

            self.assertTrue(
                any("无效依赖名 123" in error for error in errors),
                errors,
            )

    def test_checker_strictly_validates_demo_metadata_shape_and_values(self):
        cases = {
            "missing_required_key": (
                lambda metadata: metadata.pop("sequence"),
                "odoocc_demo 缺少字段 sequence",
            ),
            "unknown_key": (
                lambda metadata: metadata.update({"future": True}),
                "odoocc_demo 包含未知字段 'future'",
            ),
            "non_string_key": (
                lambda metadata: metadata.update({1: True}),
                "odoocc_demo 包含未知字段 1",
            ),
            "schema_bool": (
                lambda metadata: metadata.update({"schema_version": True}),
                "schema_version 必须为 1",
            ),
            "schema_float": (
                lambda metadata: metadata.update({"schema_version": 1.0}),
                "schema_version 必须为 1",
            ),
            "category": (
                lambda metadata: metadata.update({"category": "unknown"}),
                "category 必须是七个允许值之一",
            ),
            "unhashable_category": (
                lambda metadata: metadata.update({"category": []}),
                "category 必须是七个允许值之一",
            ),
            "sequence_bool": (
                lambda metadata: metadata.update({"sequence": False}),
                "sequence 必须是 1..9999 的整数",
            ),
            "sequence_zero": (
                lambda metadata: metadata.update({"sequence": 0}),
                "sequence 必须是 1..9999 的整数",
            ),
            "keyword_type": (
                lambda metadata: metadata.update({"keywords": ("服务台",)}),
                "keywords 必须是字符串列表",
            ),
            "keyword_duplicate": (
                lambda metadata: metadata.update(
                    {"keywords": ["服务台", "服务台"]}
                ),
                "keywords 包含重复项",
            ),
            "cross_module_xmlid": (
                lambda metadata: metadata.update(
                    {"menu_xmlid": "another_module.menu_acceptance_root"}
                ),
                "menu_xmlid 必须引用当前模块",
            ),
        }
        for name, (mutate, expected) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self._create_pair(root)
                manifest_path = root / "occ_service_desk_test" / "__manifest__.py"
                manifest = ast.literal_eval(
                    manifest_path.read_text(encoding="utf-8")
                )
                mutate(manifest["odoocc_demo"])
                manifest_path.write_text(repr(manifest) + "\n", encoding="utf-8")

                errors = validate_repository(root, require_repository_files=False)

                self.assertTrue(
                    any(expected in error for error in errors),
                    errors,
                )

    def test_checker_accepts_omitted_optional_demo_keywords(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._create_pair(root)
            manifest_path = root / "occ_service_desk_test" / "__manifest__.py"
            manifest = ast.literal_eval(manifest_path.read_text(encoding="utf-8"))
            manifest["odoocc_demo"].pop("keywords")
            manifest_path.write_text(repr(manifest) + "\n", encoding="utf-8")

            errors = validate_repository(root, require_repository_files=False)

            self.assertEqual(errors, [])

    def test_checker_validates_demo_menu_type_action_and_ancestry(self):
        cases = {
            "not_a_menu": (
                lambda manifest, xml: manifest["odoocc_demo"].update(
                    {
                        "entry_menu_xmlid": (
                            "occ_service_desk_test.view_acceptance_check_list"
                        )
                    }
                ),
                "entry_menu_xmlid 未指向 Manifest data 中的 ir.ui.menu",
            ),
            "without_action": (
                lambda manifest, xml: xml.write_text(
                    xml.read_text(encoding="utf-8").replace(
                        '              action="action_acceptance_check"\n',
                        "",
                    ),
                    encoding="utf-8",
                ),
                "entry_menu_xmlid 必须指向带 action 的可点击菜单",
            ),
            "outside_root": (
                lambda manifest, xml: xml.write_text(
                    xml.read_text(encoding="utf-8").replace(
                        '              parent="menu_acceptance_root"\n'
                        '              action="action_acceptance_check"',
                        '              parent="base.menu_administration"\n'
                        '              action="action_acceptance_check"',
                    ),
                    encoding="utf-8",
                ),
                "entry_menu_xmlid 必须是 menu_xmlid 本身或其后代",
            ),
        }
        for name, (mutate, expected) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self._create_pair(root)
                manifest_path = root / "occ_service_desk_test" / "__manifest__.py"
                views_path = (
                    root
                    / "occ_service_desk_test"
                    / "views"
                    / "acceptance_check_views.xml"
                )
                manifest = ast.literal_eval(
                    manifest_path.read_text(encoding="utf-8")
                )
                mutate(manifest, views_path)
                manifest_path.write_text(repr(manifest) + "\n", encoding="utf-8")

                errors = validate_repository(root, require_repository_files=False)

                self.assertTrue(
                    any(expected in error for error in errors),
                    errors,
                )

    def test_checker_rejects_demo_dependency_and_python_import(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._create_pair(root)
            manifest_path = root / "occ_service_desk_test" / "__manifest__.py"
            manifest = ast.literal_eval(manifest_path.read_text(encoding="utf-8"))
            manifest["depends"].append("occ_odoocc_demo")
            manifest_path.write_text(repr(manifest) + "\n", encoding="utf-8")
            model_path = (
                root
                / "occ_service_desk_test"
                / "models"
                / "acceptance_check.py"
            )
            model_path.write_text(
                "from odoo.addons import occ_odoocc_demo\n"
                + model_path.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            views_path = (
                root
                / "occ_service_desk_test"
                / "views"
                / "acceptance_check_views.xml"
            )
            views_path.write_text(
                views_path.read_text(encoding="utf-8").replace(
                    'parent="base.menu_administration"',
                    'parent="occ_odoocc_demo.menu_demo_root"',
                    1,
                ),
                encoding="utf-8",
            )

            errors = validate_repository(root, require_repository_files=False)

            self.assertTrue(
                any("不得依赖可选部署模块" in error for error in errors),
                errors,
            )
            self.assertTrue(
                any("不得导入可选部署模块" in error for error in errors),
                errors,
            )
            self.assertTrue(
                any("不得引用可选部署模块" in error for error in errors),
                errors,
            )

    def test_checker_rejects_demo_javascript_and_asset_references(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._create_pair(root)
            acceptance = root / "occ_service_desk_test"
            static_source = acceptance / "static" / "src"
            static_source.mkdir(parents=True)
            dependency_path = static_source / "demo_dependency.js"
            dependency_path.write_text(
                "/** @odoo-module **/\n"
                'import { DemoCatalog } from "@occ_odoocc_demo/catalog/catalog";\n',
                encoding="utf-8",
            )
            comment_path = static_source / "comment_only.js"
            comment_path.write_text(
                '// import "@occ_odoocc_demo/this_is_only_documentation";\n'
                'const docs = \'import "@occ_odoocc_demo/not_an_import";\';\n',
                encoding="utf-8",
            )

            manifest_path = acceptance / "__manifest__.py"
            manifest = ast.literal_eval(manifest_path.read_text(encoding="utf-8"))
            manifest["assets"] = {
                "web.assets_backend": [
                    "occ_service_desk_test/static/src/*.js",
                    ("include", "occ_odoocc_demo.web_assets_backend"),
                    ("remove", "occ_odoocc_demo/static/src/main.js"),
                ]
            }
            manifest_path.write_text(repr(manifest) + "\n", encoding="utf-8")

            errors = validate_repository(root, require_repository_files=False)

            self.assertTrue(
                any(
                    "demo_dependency.js" in error
                    and "不得导入可选部署模块" in error
                    for error in errors
                ),
                errors,
            )
            self.assertFalse(
                any("comment_only.js" in error for error in errors),
                errors,
            )
            asset_errors = [
                error
                for error in errors
                if "asset 不得引用可选部署模块" in error
            ]
            self.assertEqual(len(asset_errors), 2, errors)

    def test_javascript_demo_import_detection_ignores_non_code(self):
        source = "\n".join(
            [
                'import "@occ_odoocc_demo/side_effect";',
                'export { Demo } from "@occ_odoocc_demo/reexport";',
                'const loader = import("@occ_odoocc_demo/dynamic");',
                '// import "@occ_odoocc_demo/comment";',
                'const docs = \'import "@occ_odoocc_demo/string";\';',
                'const template = `import "@occ_odoocc_demo/template";`;',
            ]
        )

        self.assertEqual(
            check_modules._javascript_optional_demo_imports(source),
            {
                "@occ_odoocc_demo/side_effect",
                "@occ_odoocc_demo/reexport",
                "@occ_odoocc_demo/dynamic",
            },
        )

    def test_checker_rejects_demo_metadata_on_formal_module(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._create_pair(root)
            formal_path = root / "occ_service_desk" / "__manifest__.py"
            acceptance_path = (
                root / "occ_service_desk_test" / "__manifest__.py"
            )
            formal = ast.literal_eval(formal_path.read_text(encoding="utf-8"))
            acceptance = ast.literal_eval(
                acceptance_path.read_text(encoding="utf-8")
            )
            formal["odoocc_demo"] = acceptance["odoocc_demo"]
            formal_path.write_text(repr(formal) + "\n", encoding="utf-8")

            errors = validate_repository(root, require_repository_files=False)

            self.assertTrue(
                any("只有 _test 模块可声明 odoocc_demo" in error for error in errors),
                errors,
            )

    def test_secret_patterns_do_not_match_the_checker_source_itself(self):
        source = Path(check_modules.__file__).read_text(encoding="utf-8")

        for description, pattern in check_modules.HIGH_CONFIDENCE_SECRET_PATTERNS.items():
            with self.subTest(description=description):
                self.assertIsNone(pattern.search(source))

    def test_checker_detects_unquoted_shell_secret_and_set_param_literal(self):
        secret_value = "".join(("0123456789abcdef", "fedcba9876543210"))
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            shell_path = root / "configure.sh"
            shell_path.write_text(
                "APP_SECRET=" + secret_value + "\n",
                encoding="utf-8",
            )
            python_path = root / "settings.py"
            parameter_key = "occ_wechat_login." + "app_secret"
            python_path.write_text(
                'parameters.set_param("'
                + parameter_key
                + '", "'
                + secret_value
                + '")\n',
                encoding="utf-8",
            )

            errors = check_modules._check_repository_files(
                root,
                [],
                [shell_path, python_path],
            )

            self.assertTrue(
                any(
                    error.startswith("configure.sh:") and "疑似硬编码" in error
                    for error in errors
                ),
                errors,
            )
            self.assertTrue(
                any(
                    error.startswith("settings.py:") and "疑似硬编码" in error
                    for error in errors
                ),
                errors,
            )

    def test_module_table_binds_each_version_to_its_data_row(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._create_pair(root)
            modules = load_modules_for_output(root)
            readme_path = root / "README.md"
            readme_path.write_text(
                "\n".join(
                    [
                        "# OdooCC",
                        "",
                        "## 模块一览",
                        "",
                        "| 模块 | 版本 | 定位 |",
                        "| --- | --- | --- |",
                        "| `occ_service_desk` | `19.0.9.9.9` | 正式模块 |",
                        "| `occ_service_desk_test` | `19.0.1.0.0` | 验收模块 |",
                        "",
                        "## 补充说明",
                        "",
                        "正文仍提到正确版本 19.0.1.0.0。",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            errors = check_modules._check_repository_files(
                root,
                modules,
                [readme_path],
            )

            self.assertTrue(
                any(
                    "occ_service_desk 表格版本应为 '19.0.1.0.0'" in error
                    for error in errors
                ),
                errors,
            )

    def test_module_mentioned_only_in_prose_does_not_satisfy_table(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._create_pair(root)
            modules = load_modules_for_output(root)
            readme_path = root / "README.md"
            readme_path.write_text(
                "\n".join(
                    [
                        "# OdooCC",
                        "",
                        "## 模块一览",
                        "",
                        "| 定位 | 模块 | 版本 |",
                        "| --- | --- | --- |",
                        "| 验收模块 | `occ_service_desk_test` | `19.0.1.0.0` |",
                        "",
                        "正式模块 occ_service_desk 的版本是 19.0.1.0.0。",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            errors = check_modules._check_repository_files(
                root,
                modules,
                [readme_path],
            )

            self.assertIn("README.md: 模块表缺少 occ_service_desk", errors)


if __name__ == "__main__":
    unittest.main()
