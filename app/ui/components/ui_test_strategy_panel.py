from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.ui_test_setup_status import UITestSetupStatus
from app.services.ui_test_setup_analyzer import UITestSetupAnalyzer
from app.services.gradle_modifier import GradleModifier
from app.services.ui_test_template_generator import UITestTemplateGenerator
from app.services.gradle_runner import GradleRunner
from app.services.screenshot_collector import ScreenshotCollector
from app.services.adb_service import ADBService
from app.services.app_state import AppState
from app.services.log_service import LogService
from app.services.settings_service import SettingsService
from app.ui.workers import Worker


class UITestStrategyPanel(QWidget):
    def __init__(
        self,
        state: AppState,
        log_service: LogService,
        adb_service: ADBService,
        settings_service: SettingsService,
        worker_pool,
        status_callback: Callable[[str, str], None],
        selected_device_supplier: Callable[[], str],
    ) -> None:
        super().__init__()
        self.state = state
        self.log_service = log_service
        self.adb_service = adb_service
        self.settings_service = settings_service
        self.worker_pool = worker_pool
        self.status_callback = status_callback
        self.selected_device_supplier = selected_device_supplier

        self.last_ui_test_analysis_status: UITestSetupStatus | None = None
        self.generated_ui_test_files: dict[str, str] = {}
        self.app_module_path = ""
        self.package_name = ""

        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(16)

        card = QFrame()
        card.setObjectName("card")
        layout = QGridLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(10)

        title = QLabel("UI Test / Screenshot Test - Project Analysis")
        title.setObjectName("cardTitle")
        layout.addWidget(title, 0, 0, 1, 3)

        self.analyze_project_button = QPushButton("Analyze Android project")
        self.analyze_project_button.setObjectName("secondaryButton")
        self.analyze_project_button.clicked.connect(self.on_analyze_project_clicked)
        layout.addWidget(self.analyze_project_button, 1, 0)

        self.detail_app_module = QLabel("App module: N/A")
        self.detail_namespace = QLabel("Namespace: N/A")
        self.detail_application_id = QLabel("ApplicationId: N/A")
        self.detail_package_path = QLabel("Test package path: N/A")
        self.detail_gradle_type = QLabel("Gradle DSL: N/A")
        self.detail_test_runner = QLabel("Test runner: N/A")

        layout.addWidget(self.detail_app_module, 2, 0)
        layout.addWidget(self.detail_namespace, 2, 1)
        layout.addWidget(self.detail_application_id, 2, 2)
        layout.addWidget(self.detail_package_path, 3, 0)
        layout.addWidget(self.detail_gradle_type, 3, 1)
        layout.addWidget(self.detail_test_runner, 3, 2)

        deps_title = QLabel("Detected androidTest dependencies")
        deps_title.setObjectName("cardTitle")
        layout.addWidget(deps_title, 4, 0, 1, 3)

        self.deps_table = QTableWidget(0, 2)
        self.deps_table.setHorizontalHeaderLabels(["Dependency", "Status"])
        self.deps_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.deps_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.deps_table.setMinimumHeight(180)
        layout.addWidget(self.deps_table, 5, 0, 1, 3)

        preview_title = QLabel("Gradle setup preview")
        preview_title.setObjectName("cardTitle")
        layout.addWidget(preview_title, 6, 0, 1, 3)

        self.gradle_preview = QPlainTextEdit()
        self.gradle_preview.setReadOnly(True)
        self.gradle_preview.setPlaceholderText("Gradle setup preview will appear after analysis.")
        self.gradle_preview.setMinimumHeight(160)
        layout.addWidget(self.gradle_preview, 7, 0, 1, 3)

        warnings_title = QLabel("Warnings & Messages")
        warnings_title.setObjectName("cardTitle")
        layout.addWidget(warnings_title, 8, 0, 1, 3)

        self.ui_test_warnings = QPlainTextEdit()
        self.ui_test_warnings.setReadOnly(True)
        self.ui_test_warnings.setMinimumHeight(120)
        layout.addWidget(self.ui_test_warnings, 9, 0, 1, 3)

        template_title = QLabel("Generated UI test templates")
        template_title.setObjectName("cardTitle")
        layout.addWidget(template_title, 10, 0, 1, 3)

        self.generate_ui_test_preview_button = QPushButton("Preview generated UI test files")
        self.generate_ui_test_preview_button.setObjectName("secondaryButton")
        self.generate_ui_test_preview_button.clicked.connect(self.on_generate_ui_test_templates_clicked)

        self.apply_ui_test_templates_button = QPushButton("Create UI test files")
        self.apply_ui_test_templates_button.setObjectName("secondaryButton")
        self.apply_ui_test_templates_button.clicked.connect(self.on_apply_ui_test_templates_clicked)
        self.apply_ui_test_templates_button.setEnabled(False)

        self.run_connected_tests_button = QPushButton("Run connectedAndroidTest")
        self.run_connected_tests_button.setObjectName("secondaryButton")
        self.run_connected_tests_button.clicked.connect(self.on_run_connected_tests_clicked)
        self.run_connected_tests_button.setEnabled(False)

        self.collect_screenshots_button = QPushButton("Collect screenshots")
        self.collect_screenshots_button.setObjectName("secondaryButton")
        self.collect_screenshots_button.clicked.connect(self.on_collect_screenshots_clicked)
        self.collect_screenshots_button.setEnabled(False)

        action_buttons = QHBoxLayout()
        action_buttons.setSpacing(8)
        action_buttons.addWidget(self.generate_ui_test_preview_button)
        action_buttons.addWidget(self.apply_ui_test_templates_button)
        action_buttons.addWidget(self.run_connected_tests_button)
        action_buttons.addWidget(self.collect_screenshots_button)
        layout.addLayout(action_buttons, 11, 0, 1, 3)

        self.ui_test_template_preview = QPlainTextEdit()
        self.ui_test_template_preview.setReadOnly(True)
        self.ui_test_template_preview.setPlaceholderText("Generated UI test file preview will appear here.")
        self.ui_test_template_preview.setMinimumHeight(160)
        layout.addWidget(self.ui_test_template_preview, 12, 0, 1, 3)

        main_layout.addWidget(card)

    def _set_status(self, level: str, text: str) -> None:
        try:
            self.status_callback(level, text)
        except Exception:
            pass

    def on_analyze_project_clicked(self) -> None:
        project_path = self.state.selected_project_path
        if not project_path:
            project_path = QFileDialog.getExistingDirectory(self, "Select Android project folder")
            if not project_path:
                self._set_status("warning", "No project")
                return
            self.state.selected_project_path = project_path
            self.settings_service.save_last_project_path(project_path)

        self.analyze_project_button.setEnabled(False)
        self._set_status("info", "Analyzing")
        worker = Worker(self._run_ui_test_analysis, project_path)
        worker.signals.finished.connect(self.on_ui_test_analysis_finished)
        worker.signals.error.connect(self.on_worker_error)
        self.worker_pool.start(worker)

    def _run_ui_test_analysis(self, project_path: str) -> tuple[UITestSetupStatus, object]:
        analyzer = UITestSetupAnalyzer(project_path)
        status = analyzer.analyze()
        gradle_preview = GradleModifier(project_path).generate_requirements()
        return status, gradle_preview

    def on_ui_test_analysis_finished(self, result: tuple[UITestSetupStatus, object]) -> None:
        self.analyze_project_button.setEnabled(True)
        status, gradle_preview = result
        self.last_ui_test_analysis_status = status
        if not status:
            self._set_status("error", "Analysis failed")
            return

        self.app_module_path = status.app_module_path or "app"
        self.package_name = status.namespace or status.package_name or status.application_id or ""

        self.detail_app_module.setText(f"App module: {status.app_module_path or 'N/A'}")
        self.detail_namespace.setText(f"Namespace: {status.namespace or status.package_name or 'N/A'}")
        self.detail_application_id.setText(f"ApplicationId: {status.application_id or 'N/A'}")
        test_pkg = self.package_name or "N/A"
        test_pkg_path = test_pkg.replace('.', '/') if self.package_name else 'N/A'
        self.detail_package_path.setText(f"Test package path: {test_pkg_path}")
        self.detail_gradle_type.setText(f"Gradle DSL: {status.gradle_dsl or 'N/A'}")
        self.detail_test_runner.setText(f"Test runner: {status.test_instrumentation_runner or 'N/A'}")

        self.deps_table.setRowCount(0)
        found = set(status.android_test_dependencies or [])
        expected = UITestSetupAnalyzer.COMMON_ANDROID_TEST_DEPS + (UITestSetupAnalyzer.COMPOSE_DEPS if status.compose_used else [])
        for dep in expected:
            row = self.deps_table.rowCount()
            self.deps_table.insertRow(row)
            self.deps_table.setItem(row, 0, QTableWidgetItem(dep))
            present = any(dep in f for f in found)
            self.deps_table.setItem(row, 1, QTableWidgetItem("Present" if present else "Missing"))

        preview_lines = [str(line) for line in getattr(gradle_preview, "gradle_changes", [])]
        preview_text = "\n\n".join(preview_lines).strip()
        if getattr(gradle_preview, "warnings", None):
            preview_text += "\n\nWarnings:\n" + "\n".join(gradle_preview.warnings)
        self.gradle_preview.setPlainText(preview_text.strip())

        warnings_text = "\n".join(status.messages or [])
        if status.missing_dependencies:
            warnings_text += "\nMissing dependencies: " + ", ".join(status.missing_dependencies)
        if status.existing_playpulse_test_files:
            warnings_text += "\nFound PlayPulse test files: " + ", ".join(status.existing_playpulse_test_files)
        self.ui_test_warnings.setPlainText(warnings_text.strip())

        if status.ready_for_ui_test_screenshots:
            self._set_status("success", "Ready")
        else:
            self._set_status("warning", "Not ready")

    def on_generate_ui_test_templates_clicked(self) -> None:
        project_path = self.state.selected_project_path
        if not project_path:
            project_path = QFileDialog.getExistingDirectory(self, "Select Android project folder")
            if not project_path:
                self._set_status("warning", "No project")
                return
            self.state.selected_project_path = project_path
            self.settings_service.save_last_project_path(project_path)

        package_name = self.package_name or self.state.detected_package_name
        if not package_name:
            self._set_status("warning", "Package name missing")
            self.ui_test_template_preview.setPlainText(
                "Cannot generate UI test templates without a package name. Analyze the project first."
            )
            return

        self.generate_ui_test_preview_button.setEnabled(False)
        self.apply_ui_test_templates_button.setEnabled(False)
        self._set_status("info", "Generating templates")
        worker = Worker(self._generate_ui_test_templates, project_path, package_name)
        worker.signals.finished.connect(self.on_ui_test_template_preview_finished)
        worker.signals.error.connect(self.on_worker_error)
        self.worker_pool.start(worker)

    def _generate_ui_test_templates(self, project_path: str, package_name: str) -> dict[str, str]:
        generator = UITestTemplateGenerator(project_path, package_name)
        return generator.generate_templates()

    def on_ui_test_template_preview_finished(self, result: dict[str, str]) -> None:
        self.generate_ui_test_preview_button.setEnabled(True)
        self.generated_ui_test_files = result or {}
        if not result:
            self.ui_test_template_preview.setPlainText("No UI test templates could be generated.")
            self._set_status("warning", "No template preview")
            return

        preview_lines: list[str] = []
        for path, content in result.items():
            preview_lines.append(f"--- {path} ---\n{content.strip()}")
        self.ui_test_template_preview.setPlainText("\n\n".join(preview_lines))
        self.apply_ui_test_templates_button.setEnabled(True)
        self._set_status("success", "Template preview ready")

    def on_apply_ui_test_templates_clicked(self) -> None:
        if not self.generated_ui_test_files:
            self._set_status("warning", "No templates to save")
            return

        self.apply_ui_test_templates_button.setEnabled(False)
        self._set_status("info", "Writing UI test files")
        worker = Worker(self._apply_ui_test_templates, self.state.selected_project_path, self.generated_ui_test_files)
        worker.signals.finished.connect(self.on_ui_test_template_apply_finished)
        worker.signals.error.connect(self.on_worker_error)
        self.worker_pool.start(worker)

    def _apply_ui_test_templates(self, project_path: str, files_map: dict[str, str]) -> dict[str, list[str]]:
        generator = UITestTemplateGenerator(project_path, self.package_name or self.state.detected_package_name)
        return generator.write_templates(files_map)

    def on_ui_test_template_apply_finished(self, result: dict[str, list[str]]) -> None:
        written = result.get("written", [])
        skipped = result.get("skipped", [])
        errors = result.get("errors", [])
        messages: list[str] = []
        if written:
            messages.append(f"Saved {len(written)} files.")
        if skipped:
            messages.append(f"Skipped existing files: {', '.join(skipped)}")
        if errors:
            messages.append(f"Errors: {', '.join(errors)}")

        ok_to_proceed = bool(written and not errors)
        self.apply_ui_test_templates_button.setEnabled(ok_to_proceed)
        self.run_connected_tests_button.setEnabled(ok_to_proceed)
        self.ui_test_warnings.setPlainText("\n".join(messages).strip())
        self._set_status("success" if ok_to_proceed else "warning", "UI test template apply completed")
        self.log_service.info("UI test template apply completed")

    def on_run_connected_tests_clicked(self) -> None:
        project_path = self.state.selected_project_path
        if not project_path:
            project_path = QFileDialog.getExistingDirectory(self, "Select Android project folder")
            if not project_path:
                self._set_status("warning", "No project")
                return
            self.state.selected_project_path = project_path
            self.settings_service.save_last_project_path(project_path)

        self.run_connected_tests_button.setEnabled(False)
        self._set_status("info", "Running tests")
        worker = Worker(self._run_connected_android_test, project_path, self.app_module_path or "app")
        worker.signals.finished.connect(self.on_connected_tests_finished)
        worker.signals.error.connect(self.on_worker_error)
        self.worker_pool.start(worker)

    def _run_connected_android_test(self, project_path: str, app_module_path: str) -> dict:
        runner = GradleRunner(project_path)
        return runner.run_connected_android_test(app_module_path)

    def on_connected_tests_finished(self, result: dict) -> None:
        self.run_connected_tests_button.setEnabled(True)
        exit_code = str(result.get("exit_code", "-1"))
        out = result.get("stdout", "")
        err = result.get("stderr", "")
        self.ui_test_warnings.setPlainText(f"Gradle exit: {exit_code}\n\nSTDOUT:\n{out}\n\nSTDERR:\n{err}")
        if exit_code == "0":
            self.collect_screenshots_button.setEnabled(True)
            self._set_status("success", "Tests finished")
        else:
            self._set_status("warning", "Tests failed")

    def on_collect_screenshots_clicked(self) -> None:
        if not self.package_name:
            self.package_name = self.last_ui_test_analysis_status and (
                self.last_ui_test_analysis_status.namespace
                or self.last_ui_test_analysis_status.package_name
                or self.last_ui_test_analysis_status.application_id
            ) or self.state.detected_package_name
        if not self.package_name:
            self._set_status("warning", "Package name missing")
            return

        selected_device_serial = self.selected_device_supplier()
        if not selected_device_serial:
            self._set_status("warning", "No selected device")
            self.ui_test_warnings.setPlainText("Select a connected device before collecting screenshots.")
            return

        output_root = str(Path.cwd() / "playpulse_output" / "screenshots" / self.package_name)
        self.collect_screenshots_button.setEnabled(False)
        self._set_status("info", "Collecting screenshots")
        worker = Worker(self._collect_screenshots, self.package_name, output_root, selected_device_serial, self.state.manual_adb_path)
        worker.signals.finished.connect(self.on_screenshots_collected)
        worker.signals.error.connect(self.on_worker_error)
        self.worker_pool.start(worker)

    def _collect_screenshots(self, package_name: str, local_output: str, device_serial: str, manual_adb_path: str) -> dict:
        collector = ScreenshotCollector(self.adb_service)
        return collector.collect(package_name, local_output, selected_device_serial=device_serial, manual_adb_path=manual_adb_path)

    def on_screenshots_collected(self, result: dict) -> None:
        self.collect_screenshots_button.setEnabled(True)
        if result.get("error"):
            self.ui_test_warnings.setPlainText(f"Collect error: {result.get('error')}")
            self._set_status("warning", "Collect failed")
        else:
            self.ui_test_warnings.setPlainText(result.get("message", "Screenshots pulled."))
            self._set_status("success", "Screenshots collected")

    def on_worker_error(self, error: str) -> None:
        self._set_status("error", "Worker error")
        self.ui_test_warnings.setPlainText(error)
        self.log_service.error(error)
