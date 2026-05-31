from __future__ import annotations

import os
import subprocess
import shutil
from pathlib import Path
from typing import Dict


class GradleRunner:
    def __init__(self, project_path: str) -> None:
        self.project_path = Path(project_path) if project_path else Path.cwd()

    def _find_gradlew(self) -> str | None:
        # Prefer project wrapper
        win_wrapper = self.project_path / "gradlew.bat"
        unix_wrapper = self.project_path / "gradlew"
        if win_wrapper.exists():
            return str(win_wrapper)
        if unix_wrapper.exists():
            return str(unix_wrapper)
        # Fallback: rely on gradle on PATH
        gradle = shutil.which("gradle")
        if gradle:
            return gradle
        return None

    def run_connected_android_test(self, timeout: int = 60 * 30) -> Dict[str, str]:
        gradlew = None
        win_wrapper = self.project_path / "gradlew.bat"
        unix_wrapper = self.project_path / "gradlew"
        if win_wrapper.exists():
            gradlew = str(win_wrapper)
        elif unix_wrapper.exists():
            gradlew = str(unix_wrapper)
        else:
            gradlew = "gradle"  # rely on PATH

        cmd = [gradlew, "connectedAndroidTest"]
        try:
            completed = subprocess.run(
                cmd,
                cwd=str(self.project_path),
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except Exception as exc:
            return {"exit_code": "-1", "stdout": "", "stderr": str(exc), "command": " ".join(cmd)}

        stdout = (completed.stdout or b"").decode("utf-8", errors="replace")
        stderr = (completed.stderr or b"").decode("utf-8", errors="replace")
        return {"exit_code": str(completed.returncode), "stdout": stdout, "stderr": stderr, "command": " ".join(cmd)}
