from __future__ import annotations

from pathlib import Path
from typing import Dict

from app.services.adb_service import ADBService


class ScreenshotCollector:
    def __init__(self, adb_service: ADBService | None = None) -> None:
        self.adb_service = adb_service

    def collect(self, package_name: str, local_output_root: str | None = None, manual_adb_path: str = "") -> Dict[str, str]:
        if not package_name:
            return {"error": "package_name missing"}
        remote_root = f"/sdcard/Download/PlayPulseScreenshots/{package_name}"
        local_root = Path(local_output_root or Path.cwd() / "playpulse_output" / "screenshots" / package_name)
        try:
            local_root.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return {"error": f"failed to create local folder: {exc}"}

        adb = self.adb_service
        if not adb:
            return {"error": "ADB service not provided"}

        # Pull the whole directory
        pull_result = adb.run_adb_command(["pull", remote_root, str(local_root)], manual_adb_path=manual_adb_path, timeout=120)
        if pull_result.exit_code != 0:
            return {"error": pull_result.stderr or pull_result.error_message or "adb pull failed"}

        return {"pulled_to": str(local_root), "stdout": pull_result.stdout}
