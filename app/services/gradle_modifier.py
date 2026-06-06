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
        for p in self.project_path.rglob("*.gradle*"):
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "com.android.application" in text or "com.android.library" in text:
                return p
        return None

    def _find_block_match(self, text: str, block_name: str) -> re.Match | None:
        return re.search(rf"^([ \t]*){re.escape(block_name)}\s*\{{", text, re.MULTILINE)

    def _insert_into_block(self, text: str, block_name: str, lines: list[str]) -> str | None:
        match = self._find_block_match(text, block_name)
        if not match:
            return None

        indent = match.group(1)
        position = match.end()
        depth = 1
        while position < len(text) and depth > 0:
            char = text[position]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
            position += 1

        if depth != 0:
            return None

        insert_pos = position - 1
        insertion = ""
        for line in lines:
            insertion += f"\n{indent}    {line}"

        return text[:insert_pos] + insertion + text[insert_pos:]

    def _create_default_config(self, text: str, line: str, is_kts: bool) -> str:
        android_match = self._find_block_match(text, "android")
        if android_match:
            indent = android_match.group(1)
            insert_pos = android_match.end()
            default_config_block = f"\n{indent}    defaultConfig {{\n{indent}        {line}\n{indent}    }}"
            return text[:insert_pos] + default_config_block + text[insert_pos:]

        runner_line = f"testInstrumentationRunner = \"androidx.test.runner.AndroidJUnitRunner\"" if is_kts else "testInstrumentationRunner \"androidx.test.runner.AndroidJUnitRunner\""
        return text + f"\n\nandroid {{\n    defaultConfig {{\n        {runner_line}\n    }}\n}}\n"

    def _append_dependencies_block(self, text: str, lines: list[str]) -> str:
        block = "dependencies {\n"
        for line in lines:
            block += f"    {line}\n"
        block += "}\n"
        return text + "\n" + block

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

        runner_exists = bool(re.search(r"testInstrumentationRunner\s*[= ]\s*[\\\"']([^\\\"']+)[\\\"']", text))
        req.existing_dependencies = []
        req.added_dependencies = []

        existing_deps = re.findall(r"androidTestImplementation\s*\(?\s*[\"']([^\"']+)[\"']\s*\)?", text)
        existing_deps += re.findall(r"androidTestImplementation\(\s*[\"']([^\"']+)[\"']\s*\)", text)

        existing_keys = set()
        for e in existing_deps:
            parts = e.split(":")
            if len(parts) >= 2:
                existing_keys.add(":".join(parts[:2]))

        missing_deps: list[str] = []
        for dep in self.DEFAULT_DEPS:
            parts = dep.split(":")
            key = ":".join(parts[:2]) if len(parts) >= 2 else dep
            if key in existing_keys:
                req.existing_dependencies.append(key)
            else:
                req.added_dependencies.append(dep)
                missing_deps.append(dep)

        compose_used = "androidx.compose" in text or "composeOptions" in text
        if compose_used:
            for dep in self.COMPOSE_DEPS:
                parts = dep.split(":")
                key = ":".join(parts[:2]) if len(parts) >= 2 else dep
                if key in existing_keys:
                    req.existing_dependencies.append(key)
                else:
                    req.added_dependencies.append(dep)
                    missing_deps.append(dep)

        if not runner_exists:
            if is_kts:
                req.gradle_changes.append(
                    "In android.defaultConfig add: testInstrumentationRunner = \"androidx.test.runner.AndroidJUnitRunner\""
                )
            else:
                req.gradle_changes.append(
                    "In android.defaultConfig add: testInstrumentationRunner \"androidx.test.runner.AndroidJUnitRunner\""
                )

        if req.existing_dependencies:
            req.gradle_changes.append("Already present dependencies: " + ", ".join(sorted(set(req.existing_dependencies))))

        if req.added_dependencies:
            comment = "// Added by PlayPulse for Android screenshot UI tests"
            if is_kts:
                dep_block = "dependencies {\n"
                dep_block += f"    {comment}\n"
                for dep in req.added_dependencies:
                    dep_block += f'    androidTestImplementation("{dep}")\n'
                dep_block += "}"
            else:
                dep_block = "dependencies {\n"
                dep_block += f"    {comment}\n"
                for dep in req.added_dependencies:
                    dep_block += f'    androidTestImplementation "{dep}"\n'
                dep_block += "}"
            req.gradle_changes.append("Will add missing androidTest dependencies:")
            req.gradle_changes.append(dep_block)

        if not req.added_dependencies and runner_exists:
            req.gradle_changes.append("All recommended androidTest dependencies appear present.")

        return req

    def apply_requirements(self, requirements: UITestSetupRequirements) -> dict[str, list[str]]:
        results = {"written": [], "skipped": [], "errors": []}
        if not self.project_path or not self.project_path.exists():
            results["errors"].append("Project path not set or does not exist.")
            return results

        app_gradle = self._find_app_gradle()
        if not app_gradle:
            results["errors"].append("Could not find app module build.gradle or build.gradle.kts.")
            return results

        try:
            text = app_gradle.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            results["errors"].append(str(exc))
            return results

        is_kts = app_gradle.suffix == ".kts"
        runner_exists = bool(re.search(r"testInstrumentationRunner\s*[= ]\s*[\\\"']([^\\\"']+)[\\\"']", text))
        changed = False

        if not runner_exists:
            runner_line = (
                'testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"'
                if is_kts
                else 'testInstrumentationRunner "androidx.test.runner.AndroidJUnitRunner"'
            )
            inserted = self._insert_into_block(text, "defaultConfig", [runner_line])
            if inserted is None:
                text = self._create_default_config(text, runner_line, is_kts)
            else:
                text = inserted
            changed = True

        if requirements.added_dependencies:
            comment = "// Added by PlayPulse for Android screenshot UI tests"
            dep_lines = [comment]
            for dep in requirements.added_dependencies:
                if is_kts:
                    dep_lines.append(f'androidTestImplementation("{dep}")')
                else:
                    dep_lines.append(f'androidTestImplementation "{dep}"')

            inserted = self._insert_into_block(text, "dependencies", dep_lines)
            if inserted is None:
                text = self._append_dependencies_block(text, dep_lines)
            else:
                text = inserted
            changed = True

        if not changed:
            results["skipped"].append("No Gradle changes required.")
            return results

        try:
            app_gradle.write_text(text, encoding="utf-8")
            results["written"].append(str(app_gradle.relative_to(self.project_path)))
        except OSError as exc:
            results["errors"].append(str(exc))

        return results
