from __future__ import annotations

import re
from pathlib import Path
from typing import List

from app.models.ui_test_setup_status import UITestSetupStatus
from app.services.project_scanner import ProjectScanner


class UITestSetupAnalyzer:
    COMMON_ANDROID_TEST_DEPS = [
        "androidx.test:runner",
        "androidx.test:rules",
        "androidx.test.ext:junit",
        "androidx.test.espresso:espresso-core",
        "androidx.test.uiautomator:uiautomator",
        "androidx.test:core",
    ]

    COMPOSE_TEST_DEPS = [
        "androidx.compose.ui:ui-test-junit4",
        "androidx.compose.ui:ui-test-manifest",
    ]

    def __init__(self, project_path: str) -> None:
        self.project_path = str(Path(project_path).expanduser()) if project_path else ""
        self.root = Path(self.project_path) if self.project_path else None

    def analyze(self) -> UITestSetupStatus:
        status = UITestSetupStatus()
        status.project_path = self.project_path or ""
        if not self.project_path or not Path(self.project_path).exists():
            status.messages.append("Project path not set or does not exist.")
            return status

        scanner = ProjectScanner()
        scan = scanner.scan_project(self.project_path)
        status.has_android_project = bool(scan.get("gradle_files") or scan.get("manifest"))
        gradle_files: List[str] = scan.get("gradle_files") or []
        status.gradle_dsl = "kotlin" if any(p.endswith(".kts") for p in gradle_files) else "groovy"
        status.gradle_settings_found = any(p.endswith("settings.gradle") or p.endswith("settings.gradle.kts") for p in gradle_files)
        status.root_gradle_found = any(Path(self.project_path, p).name.startswith("build.gradle") for p in gradle_files)

        # Determine app module path and gradle file
        app_module = Path(self.project_path) / "app"
        app_gradle = None
        if (app_module / "build.gradle").exists():
            app_gradle = app_module / "build.gradle"
        elif (app_module / "build.gradle.kts").exists():
            app_gradle = app_module / "build.gradle.kts"
        else:
            # search for module with apply plugin: 'com.android.application'
            for p in gradle_files:
                ppath = Path(self.project_path) / p
                try:
                    text = ppath.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                if "com.android.application" in text or "com.android.library" in text:
                    app_gradle = ppath
                    break

        if app_gradle:
            status.app_module_path = str(app_gradle.parent.relative_to(Path(self.project_path)).as_posix())
            status.app_gradle_file = str(app_gradle.relative_to(Path(self.project_path)).as_posix())

        # Package and namespace
        status.package_name = scan.get("package_name") or ""
        # Try to read applicationId or namespace from app gradle
        if app_gradle and app_gradle.exists():
            try:
                text = app_gradle.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                text = ""
            ns_match = re.search(r"namespace\s*[= ]\s*[\"']([^\"']+)[\"']", text)
            appid_match = re.search(r"applicationId\s*[= ]\s*[\"']([^\"']+)[\"']", text)
            if ns_match:
                status.namespace = ns_match.group(1)
            if appid_match:
                status.application_id = appid_match.group(1)
            # Kotlin detection
            if app_gradle.suffix == ".kts" or "kotlin-android" in text:
                status.kotlin_used = True
            # Compose detection
            if "androidx.compose" in text or "composeOptions" in text:
                status.compose_used = True
            # Detect testInstrumentationRunner
            runner_match = re.search(r"testInstrumentationRunner\s*[= ]\s*[\"']([^\"']+)[\"']", text)
            if runner_match:
                status.test_instrumentation_runner = runner_match.group(1)
            # Detect androidTestImplementation deps
            deps = re.findall(r"androidTestImplementation\s+['\"]([^'\"]+)['\"]", text)
            status.android_test_dependencies.extend(deps)

        # If applicationId missing, try to read from manifest
        if not status.application_id and scan.get("manifest") and scan.get("manifest") != "Not found":
            manifest_path = Path(self.project_path) / scan.get("manifest")
            try:
                import xml.etree.ElementTree as ET

                manifest = ET.parse(manifest_path)
                status.application_id = manifest.getroot().attrib.get("package", "")
            except Exception:
                pass

        # Detect androidTest source set
        if status.app_module_path:
            android_test_dir = Path(self.project_path) / status.app_module_path / "src" / "androidTest"
            if android_test_dir.exists():
                status.android_test_source_exists = True
                for p in android_test_dir.rglob("*.kt"):
                    status.android_test_files.append(str(p.relative_to(Path(self.project_path)).as_posix()))
                for p in android_test_dir.rglob("*.java"):
                    status.android_test_files.append(str(p.relative_to(Path(self.project_path)).as_posix()))

        # Check for PlayPulse test files (playpulse package)
        if status.android_test_source_exists:
            for f in status.android_test_files:
                if "/playpulse/" in f or f.endswith("PlayPulseScreenshotTest.kt") or f.endswith("PlayPulseScreenshotTest.java"):
                    status.existing_playpulse_test_files.append(f)

        # Identify missing dependencies
        for dep in self.COMMON_ANDROID_TEST_DEPS:
            if not any(dep in a for a in status.android_test_dependencies):
                status.missing_dependencies.append(dep)

        # Compose deps
        if status.compose_used:
            for dep in self.COMPOSE_TEST_DEPS:
                if not any(dep in a for a in status.android_test_dependencies):
                    status.missing_dependencies.append(dep)

        # Determine readiness: basic heuristics
        ready = status.has_android_project and status.app_module_path and status.package_name
        # require at least runner and core test deps present and androidTest source exists or can be created
        if not status.test_instrumentation_runner:
            ready = False
            status.messages.append("testInstrumentationRunner not configured in app module.")
        if not any("androidx.test:runner" in d for d in status.android_test_dependencies):
            ready = False
            status.messages.append("androidTest runner dependency missing.")
        status.ready_for_ui_test_screenshots = ready

        # Add human-friendly messages
        if status.existing_playpulse_test_files:
            status.messages.append(f"Found existing PlayPulse test files: {len(status.existing_playpulse_test_files)}")

        return status
