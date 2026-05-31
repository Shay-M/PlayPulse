from __future__ import annotations

import re
from pathlib import Path
from typing import List

from app.models.ui_test_setup_status import UITestSetupRequirements


class GradleModifier:
    DEFAULT_DEPS = [
        "androidx.test:runner:1.6.2",
        "androidx.test:rules:1.6.1",
        "androidx.test.ext:junit:1.2.1",
        "androidx.test.espresso:espresso-core:3.6.1",
        "androidx.test.uiautomator:uiautomator:2.3.0",
        "androidx.test:core:1.6.1",
    ]

    COMPOSE_DEPS = [
        "androidx.compose.ui:ui-test-junit4",
        "androidx.compose.ui:ui-test-manifest",
    ]

    def __init__(self, project_path: str) -> None:
        self.project_path = Path(project_path) if project_path else None

    def _find_app_gradle(self) -> Path | None:
        if not self.project_path:
            return None
        app_module = self.project_path / "app"
        candidates = [app_module / "build.gradle", app_module / "build.gradle.kts"]
        for c in candidates:
            if c.exists():
                return c
        # fallback: search for a gradle file that applies android application plugin
        for p in self.project_path.rglob("*.gradle*"):
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "com.android.application" in text or "com.android.library" in text:
                return p
        return None

    def generate_requirements(self) -> UITestSetupRequirements:
        req = UITestSetupRequirements()
        if not self.project_path or not self.project_path.exists():
            req.warnings.append("Project path not set or does not exist.")
            req.can_apply = False
            return req

        app_gradle = self._find_app_gradle()
        if not app_gradle:
            req.warnings.append("Could not find app module build.gradle or build.gradle.kts.")
            req.can_apply = False
            return req

        is_kts = app_gradle.suffix == ".kts"
        try:
            text = app_gradle.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            text = ""

        # Detect existing runner
        runner_exists = bool(re.search(r"testInstrumentationRunner\s*[= ]\s*[\\\"']([^\\\"']+)[\\\"']", text))
        if not runner_exists:
            if is_kts:
                req.gradle_changes.append(
                    "In android.defaultConfig add: testInstrumentationRunner = \"androidx.test.runner.AndroidJUnitRunner\""
                )
            else:
                req.gradle_changes.append(
                    "In android.defaultConfig add: testInstrumentationRunner \"androidx.test.runner.AndroidJUnitRunner\""
                )

        # Detect existing androidTestImplementation lines (both groovy and kotlin DSL)
        existing_deps = re.findall(r"androidTestImplementation\s*\(?\s*[\"']([^\"']+)[\"']\s*\)?", text)
        existing_deps += re.findall(r"androidTestImplementation\(\s*[\"']([^\"']+)[\"']\s*\)", text)

        # Normalize existing dependencies to group:artifact (no version)
        existing_keys = set()
        for e in existing_deps:
            parts = e.split(":")
            if len(parts) >= 2:
                existing_keys.add(":".join(parts[:2]))

        # Prepare deps to add by checking group:artifact presence
        to_add: List[str] = []
        for dep in self.DEFAULT_DEPS:
            parts = dep.split(":")
            key = ":".join(parts[:2]) if len(parts) >= 2 else dep
            if key not in existing_keys:
                to_add.append(dep)

        # Check for Compose usage to include compose deps
        compose_used = "androidx.compose" in text or "composeOptions" in text
        if compose_used:
            for dep in self.COMPOSE_DEPS:
                parts = dep.split(":")
                key = ":".join(parts[:2]) if len(parts) >= 2 else dep
                if key not in existing_keys:
                    to_add.append(dep)

        # Create gradle change lines according to DSL
        for dep in to_add:
            if is_kts:
                req.gradle_changes.append(f'dependencies {{\n    androidTestImplementation("{dep}")\n}}')
            else:
                req.gradle_changes.append(f'dependencies {{\n    androidTestImplementation "{dep}"\n}}')

        # Summarize
        if runner_exists:
            req.gradle_changes.insert(0, "testInstrumentationRunner appears to be configured.")
        else:
            req.gradle_changes.insert(0, "testInstrumentationRunner will be added to android.defaultConfig.")

        if not to_add:
            req.gradle_changes.append("All recommended androidTest dependencies appear present.")

        return req
