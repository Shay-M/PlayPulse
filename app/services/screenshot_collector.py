from __future__ import annotations

from pathlib import Path
from typing import Dict

from app.services.adb_service import ADBService


class ScreenshotCollector:
    def __init__(self, adb_service: ADBService | None = None) -> None:
        self.adb_service = adb_service

    def collect(
        self,
        package_name: str,
        local_output_folder: str | None = None,
        selected_device_serial: str | None = None,
        manual_adb_path: str | None = None,
    ) -> dict:
        result: dict = {
            "success": False,
            "package_name": package_name,
            "device_serial": selected_device_serial or "",
            "adb_path_used": "",
            "local_output_folder": "",
            "pulled_paths": [],
            "missing_paths": [],
            "stdout": "",
            "stderr": "",
            "error_message": "",
            "remote_folders_checked": [],
        }

        if not package_name:
            result["error_message"] = "package_name missing"
            return result

        local_root = Path(local_output_folder or Path.cwd() / "playpulse_output" / "screenshots" / package_name)
        try:
            local_root.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            result["error_message"] = f"failed to create local folder: {exc}"
            return result

        adb = self.adb_service
        if not adb:
            result["error_message"] = "ADB service not provided"
            return result

        manual_adb_path = str(manual_adb_path or "")
        selected_device = selected_device_serial or ""
        if not selected_device:
            devices = adb.refresh_devices(manual_adb_path)
            if not devices:
                result["error_message"] = (
                    "No Android devices found. Connect a device and retry."
                )
                return result
            if len(devices) > 1:
                result["error_message"] = (
                    "Multiple Android devices are connected. Select a specific device to use for screenshot collection."
                )
                return result
            selected_device = devices[0].identifier
            result["device_serial"] = selected_device

        adb_path_info = adb.resolve_adb_path(manual_adb_path)
        result["adb_path_used"] = adb_path_info.path if adb_path_info.found else ""
        if not adb_path_info.found:
            result["error_message"] = adb_path_info.error_message or "ADB path could not be resolved."
            return result

        primary_remote_root = f"/sdcard/Download/PlayPulseScreenshots/{package_name}"
        fallback_remote_root = f"/sdcard/Android/data/{package_name}/files/PlayPulseScreenshots"
        remote_roots = [primary_remote_root, fallback_remote_root]
        result["remote_folders_checked"] = remote_roots
        result["local_output_folder"] = str(local_root)

        for remote_root in remote_roots:
            pull_result = adb.run_adb_command(
                ["pull", remote_root, str(local_root)],
                device_serial=selected_device,
                manual_adb_path=manual_adb_path,
                timeout=120,
            )
            result["stdout"] += pull_result.stdout or ""
            result["stderr"] += pull_result.stderr or ""
            if pull_result.exit_code == 0:
                result["success"] = True
                result["pulled_paths"].append(str(local_root))
                return result

        result["missing_paths"] = remote_roots
        result["error_message"] = (
            "No PlayPulse screenshots were found on the selected device. Make sure connectedAndroidTest ran successfully and the test wrote PNG files."
        )
        return result
