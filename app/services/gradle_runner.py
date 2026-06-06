from __future__ import annotations

import os
import subprocess
import shutil
from pathlib import Path
from typing import Dict


class GradleRunner:
    def __init__(self, project_path: str) -> None:
        self.project_path = Path(project_path) if project_path else Path.cwd()

    def _find_gradlew(self) -> str:
        win_wrapper = self.project_path / "gradlew.bat"
        unix_wrapper = self.project_path / "gradlew"

        if win_wrapper.exists():
            return str(win_wrapper)

        if unix_wrapper.exists():
            return str(unix_wrapper)

        gradle = shutil.which("gradle")
        if gradle:
            return gradle

        raise FileNotFoundError("Gradle wrapper was not found and gradle is not available in PATH.")

    def _module_task(self, app_module_path: str) -> str:
        module = (app_module_path or "app").replace("\\", "/").strip("/")
        module_name = ":" + module.replace("/", ":")
        return f"{module_name}:connectedAndroidTest"

    def run_connected_android_test(self, app_module_path: str = "app", timeout: int = 60 * 30) -> Dict[str, str]:
        try:
            gradlew = self._find_gradlew()
            task = self._module_task(app_module_path)
            cmd = [gradlew, task]

            completed = subprocess.run(
                cmd,
                cwd=str(self.project_path),
                capture_output=True,
                timeout=timeout,
                check=False,
            )

            stdout = (completed.stdout or b"").decode("utf-8", errors="replace")
            stderr = (completed.stderr or b"").decode("utf-8", errors="replace")

            return {
                "exit_code": str(completed.returncode),
                "stdout": stdout,
                "stderr": stderr,
                "command": " ".join(cmd),
            }

        except Exception as exc:
            return {
                "exit_code": "-1",
                "stdout": "",
                "stderr": str(exc),
                "command": " ".join(cmd) if "cmd" in locals() else "",
            }
