from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from app.services.adb_service import ADBService

logger = logging.getLogger(__name__)


class ScreenshotCollector:
    APP_SPECIFIC_DIR_TEMPLATE = "/sdcard/Android/data/{package_name}/files/playpulse_screenshots"
    LEGACY_DOWNLOAD_DIR_TEMPLATE = "/sdcard/Download/PlayPulseScreenshots/{package_name}"

    def __init__(self, adb_service: ADBService | None = None) -> None:
        self.adb_service = adb_service

    def collect(
        self,
        package_name: str,
        local_output_dir: str | None = None,
        selected_device_serial: str | None = None,
        manual_adb_path: str | None = None,
        timeout: int = 120,
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
            "remote_pngs_found": [],
            "command": "",
            "exit_code": None,
        }

        package_name = (package_name or "").strip()
        if not package_name:
            result["error_message"] = "Package name is missing."
            return result

        local_root = Path(local_output_dir or Path.cwd() / "playpulse_output" / "screenshots" / package_name).expanduser()
        try:
            local_root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            result["error_message"] = f"Failed to create local folder: {error}"
            return result
        result["local_output_folder"] = str(local_root)

        adb_path = self._resolve_adb_path(manual_adb_path or "")
        if not adb_path:
            result["error_message"] = "ADB path could not be resolved."
            return result
        result["adb_path_used"] = adb_path

        selected_device = self._resolve_device_serial(selected_device_serial, manual_adb_path or "")
        result["device_serial"] = selected_device or ""
        if not selected_device:
            result["error_message"] = "No selected device serial. Select a device before collecting screenshots."
            return result

        remote_folders = [
            self.APP_SPECIFIC_DIR_TEMPLATE.format(package_name=package_name),
            self.LEGACY_DOWNLOAD_DIR_TEMPLATE.format(package_name=package_name),
        ]
        result["remote_folders_checked"] = remote_folders

        combined_stdout: list[str] = []
        combined_stderr: list[str] = []
        pulled_paths: list[str] = []
        missing_paths: list[str] = []
        remote_pngs: list[str] = []

        for remote_root in remote_folders:
            list_result = self._run_adb(
                adb_path,
                selected_device,
                ["shell", "find", remote_root, "-type", "f", "-name", "*.png"],
                timeout=30,
            )
            combined_stdout.append(list_result.get("stdout", ""))
            combined_stderr.append(list_result.get("stderr", ""))
            if list_result.get("exit_code") != 0:
                missing_paths.append(remote_root)
                continue

            found_files = [line.strip() for line in list_result.get("stdout", "").splitlines() if line.strip()]
            if not found_files:
                missing_paths.append(remote_root)
                continue

            remote_pngs.extend(found_files)
            pull_target = local_root / self._safe_folder_name(remote_root)
            pull_target.mkdir(parents=True, exist_ok=True)
            pull_result = self._run_adb(
                adb_path,
                selected_device,
                ["pull", remote_root, str(pull_target)],
                timeout=timeout,
            )
            combined_stdout.append(pull_result.get("stdout", ""))
            combined_stderr.append(pull_result.get("stderr", ""))
            result["command"] = pull_result.get("command", "")
            result["exit_code"] = pull_result.get("exit_code")
            if pull_result.get("exit_code") == 0:
                pulled_paths.append(str(pull_target))
            else:
                missing_paths.append(remote_root)

        result["stdout"] = "\n".join(text for text in combined_stdout if text).strip()
        result["stderr"] = "\n".join(text for text in combined_stderr if text).strip()
        result["remote_pngs_found"] = remote_pngs
        result["pulled_paths"] = pulled_paths
        result["missing_paths"] = missing_paths

        local_pngs = sorted(path for path in local_root.rglob("*.png") if path.is_file())
        if local_pngs:
            result["success"] = True
            result["pulled_paths"] = [str(path) for path in local_pngs]
            logger.info("Collected %s PlayPulse screenshot file(s)", len(local_pngs))
            return result

        result["error_message"] = (
            "No PlayPulse screenshots were found on the selected device. "
            "connectedAndroidTest may have passed without writing PNG files. "
            "Check PlayPulseScreenshotTest and PlayPulseScreenshotHelper logs."
        )
        return result

    def _run_adb(self, adb_path: str, device_serial: str, args: list[str], timeout: int) -> dict:
        command = [adb_path, "-s", device_serial] + args
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
            return {
                "command": " ".join(command),
                "exit_code": completed.returncode,
                "stdout": completed.stdout or "",
                "stderr": completed.stderr or "",
            }
        except subprocess.TimeoutExpired as error:
            stdout = error.stdout if isinstance(error.stdout, str) else (error.stdout or b"").decode("utf-8", errors="replace")
            stderr = error.stderr if isinstance(error.stderr, str) else (error.stderr or b"").decode("utf-8", errors="replace")
            return {
                "command": " ".join(command),
                "exit_code": None,
                "stdout": stdout,
                "stderr": stderr or f"ADB command timed out after {timeout} seconds.",
            }
        except OSError as error:
            return {"command": " ".join(command), "exit_code": None, "stdout": "", "stderr": str(error)}

    def _resolve_adb_path(self, manual_adb_path: str) -> str:
        if self.adb_service:
            path_info = self.adb_service.resolve_adb_path(manual_adb_path)
            if path_info.found:
                return path_info.path
            logger.warning("ADB service could not resolve adb path: %s", path_info.error_message)

        if manual_adb_path:
            candidate = Path(manual_adb_path).expanduser()
            if candidate.exists() and candidate.is_file():
                return str(candidate)

        return shutil.which("adb") or ""

    def _resolve_device_serial(self, selected_device_serial: str | None, manual_adb_path: str) -> str:
        if selected_device_serial:
            return selected_device_serial
        if not self.adb_service:
            return ""

        devices = self.adb_service.refresh_devices(manual_adb_path)
        if len(devices) == 1:
            return devices[0].identifier
        if len(devices) > 1:
            logger.warning("Multiple devices are connected; collection requires a selected device.")
        return ""

    def _safe_folder_name(self, value: str) -> str:
        return value.strip("/").replace("/", "_").replace(".", "_") or "remote"
