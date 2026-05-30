from __future__ import annotations

import getpass
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List

from app.models.device_info import DeviceInfo
from app.services.settings_service import SettingsService

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass
class ADBPathInfo:
    found: bool = False
    path: str = ""
    source: str = "not found"
    searched_paths: List[str] | None = None
    error_message: str = ""


@dataclass
class ADBCommandResult:
    command: str = ""
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    stdout_bytes: bytes = b""
    timed_out: bool = False
    error_message: str = ""


@dataclass
class ADBDiagnostics:
    adb_found: bool = False
    adb_path: str = ""
    adb_source: str = "not found"
    adb_version: str = ""
    android_sdk_version: str = ""
    android_release_version: str = ""
    device_manufacturer: str = ""
    device_model: str = ""
    connected_devices_count: int = 0
    raw_devices_output: str = ""
    selected_device_serial: str = ""
    selected_capture_backend: str = ""
    screenshot_output_folder: str = ""
    output_folder_exists: bool = False
    output_folder_writable: bool = False
    last_executed_adb_command: str = ""
    last_command_exit_code: int | None = None
    last_stdout: str = ""
    last_stderr: str = ""
    last_screenshot_file_path: str = ""
    screenshot_file_created: bool = False
    screenshot_file_size_bytes: int = 0
    capture_method_used: str = ""
    ready_devices: List[DeviceInfo] | None = None
    problem_devices: List[DeviceInfo] | None = None
    user_message: str = ""

    def as_text(self) -> str:
        ready_devices = self.ready_devices or []
        problem_devices = self.problem_devices or []
        ready_lines = [f"  - {device.identifier} ({device.description})" for device in ready_devices]
        problem_lines = [
            f"  - {device.identifier} ({device.status}) {device.description}" for device in problem_devices
        ]
        return "\n".join(
            [
                f"adb found: {self.adb_found}",
                f"adb path: {self.adb_path or 'Not found'}",
                f"adb discovery source: {self.adb_source}",
                "adb version:",
                self.adb_version or "Not available",
                f"Android release: {self.android_release_version or 'Not available'}",
                f"Android SDK version: {self.android_sdk_version or 'Not available'}",
                f"device manufacturer: {self.device_manufacturer or 'Not available'}",
                f"device model: {self.device_model or 'Not available'}",
                f"connected ready devices count: {self.connected_devices_count}",
                "ready devices:",
                "\n".join(ready_lines) if ready_lines else "  none",
                "problem devices:",
                "\n".join(problem_lines) if problem_lines else "  none",
                "raw adb devices -l output:",
                self.raw_devices_output or "Not available",
                f"selected device serial: {self.selected_device_serial or 'None'}",
                f"selected capture backend: {self.selected_capture_backend or 'None'}",
                f"screenshot output folder: {self.screenshot_output_folder or 'None'}",
                f"output folder exists: {self.output_folder_exists}",
                f"output folder writable: {self.output_folder_writable}",
                f"last executed adb command: {self.last_executed_adb_command or 'None'}",
                f"last command exit code: {self.last_command_exit_code}",
                "last stdout:",
                self.last_stdout or "",
                "last stderr:",
                self.last_stderr or "",
                f"last screenshot file path: {self.last_screenshot_file_path or 'None'}",
                f"screenshot file created: {self.screenshot_file_created}",
                f"screenshot file size bytes: {self.screenshot_file_size_bytes}",
                f"capture method used: {self.capture_method_used or 'None'}",
                f"user message: {self.user_message or 'OK'}",
            ]
        )


@dataclass
class ADBCaptureResult:
    screenshot_path: str
    method_used: str
    file_size_bytes: int
    command_result: ADBCommandResult


class ADBUserError(RuntimeError):
    def __init__(self, message: str, diagnostics: ADBDiagnostics | None = None) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


class ADBService:
    def __init__(self, settings_service: SettingsService | None = None) -> None:
        self.settings_service = settings_service
        self.manual_adb_path: str = ""
        self.last_command_result = ADBCommandResult()
        self.last_diagnostics = ADBDiagnostics()

    def set_manual_adb_path(self, path: str) -> None:
        self.manual_adb_path = path.strip()

    def resolve_adb_path(self, manual_adb_path: str = "") -> ADBPathInfo:
        saved_path = self.settings_service.adb_path() if self.settings_service else ""
        manual_path = manual_adb_path.strip() or self.manual_adb_path
        searched_paths: List[str] = []

        for source, configured_path in [
            ("saved adb path", saved_path),
            ("manually selected path", manual_path),
        ]:
            if not configured_path:
                continue
            candidate = Path(configured_path).expanduser()
            searched_paths.append(str(candidate))
            if candidate.exists() and candidate.is_file():
                return self._adb_path_found(str(candidate), source, searched_paths)

        adb_from_path = shutil.which("adb")
        if adb_from_path:
            searched_paths.append(adb_from_path)
            return self._adb_path_found(adb_from_path, "PATH", searched_paths)

        for env_name in ["ANDROID_HOME", "ANDROID_SDK_ROOT"]:
            env_value = os.environ.get(env_name, "")
            if not env_value:
                continue
            for filename in ["adb.exe", "adb"]:
                candidate = Path(env_value) / "platform-tools" / filename
                searched_paths.append(str(candidate))
                if candidate.exists() and candidate.is_file():
                    return self._adb_path_found(str(candidate), f"{env_name}/platform-tools", searched_paths)

        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            candidate = Path(local_app_data) / "Android" / "Sdk" / "platform-tools" / "adb.exe"
            searched_paths.append(str(candidate))
            if candidate.exists() and candidate.is_file():
                return self._adb_path_found(str(candidate), "common Windows Android SDK path", searched_paths)

        current_user = getpass.getuser()
        candidate = Path("C:/Users") / current_user / "AppData" / "Local" / "Android" / "Sdk" / "platform-tools" / "adb.exe"
        searched_paths.append(str(candidate))
        if candidate.exists() and candidate.is_file():
            return self._adb_path_found(str(candidate), "common Windows Android SDK path", searched_paths)

        return ADBPathInfo(
            False,
            "",
            "not found",
            searched_paths,
            "ADB was not found. Install Android platform-tools or select adb.exe manually.",
        )

    def _adb_path_found(self, path: str, source: str, searched_paths: List[str]) -> ADBPathInfo:
        if self.settings_service:
            self.settings_service.save_adb_path(path)
        return ADBPathInfo(True, path, source, list(searched_paths))

    def refresh_devices(self, manual_adb_path: str = "") -> List[DeviceInfo]:
        diagnostics = self.run_diagnostics(manual_adb_path=manual_adb_path)
        self.last_diagnostics = diagnostics
        return diagnostics.ready_devices or []

    def run_diagnostics(
        self,
        manual_adb_path: str = "",
        selected_device_serial: str = "",
        capture_backend: str = "",
        output_folder: str = "",
    ) -> ADBDiagnostics:
        path_info = self.resolve_adb_path(manual_adb_path)
        diagnostics = ADBDiagnostics(
            adb_found=path_info.found,
            adb_path=path_info.path,
            adb_source=path_info.source,
            selected_device_serial=selected_device_serial,
            selected_capture_backend=capture_backend,
            screenshot_output_folder=output_folder,
        )

        diagnostics.output_folder_writable = self.is_output_folder_writable(output_folder)
        diagnostics.output_folder_exists = bool(output_folder) and Path(output_folder).expanduser().exists()

        if not path_info.found:
            diagnostics.user_message = path_info.error_message
            self.last_diagnostics = diagnostics
            return diagnostics

        version_result = self.run_adb_command(["version"], manual_adb_path=manual_adb_path, timeout=10)
        diagnostics.adb_version = version_result.stdout or version_result.stderr

        devices_result = self.run_adb_command(["devices", "-l"], manual_adb_path=manual_adb_path, timeout=12)
        diagnostics.raw_devices_output = devices_result.stdout or devices_result.stderr
        diagnostics.last_executed_adb_command = devices_result.command
        diagnostics.last_command_exit_code = devices_result.exit_code
        diagnostics.last_stdout = devices_result.stdout
        diagnostics.last_stderr = devices_result.stderr

        all_devices = self.parse_devices(devices_result.stdout)
        ready_devices = [device for device in all_devices if device.status.lower() == "device"]
        problem_devices = [device for device in all_devices if device.status.lower() != "device"]
        diagnostics.ready_devices = ready_devices
        diagnostics.problem_devices = problem_devices
        diagnostics.connected_devices_count = len(ready_devices)

        device_serial_for_info = selected_device_serial
        if not device_serial_for_info and ready_devices:
            device_serial_for_info = ready_devices[0].identifier
        if device_serial_for_info:
            diagnostics.android_release_version = self._read_device_property(
                device_serial_for_info,
                "ro.build.version.release",
                manual_adb_path,
            )
            diagnostics.android_sdk_version = self._read_device_property(
                device_serial_for_info,
                "ro.build.version.sdk",
                manual_adb_path,
            )
            diagnostics.device_manufacturer = self._read_device_property(
                device_serial_for_info,
                "ro.product.manufacturer",
                manual_adb_path,
            )
            diagnostics.device_model = self._read_device_property(
                device_serial_for_info,
                "ro.product.model",
                manual_adb_path,
            )

        if devices_result.timed_out:
            diagnostics.user_message = "adb devices timed out. Restart ADB or the emulator and try again."
        elif devices_result.exit_code != 0:
            diagnostics.user_message = devices_result.stderr or "adb devices failed."
        elif not ready_devices:
            diagnostics.user_message = (
                "No ready Android device was found. Start an emulator or connect a device, then run adb devices."
            )

        self.last_diagnostics = diagnostics
        return diagnostics

    def test_device_connection(self, device: DeviceInfo, manual_adb_path: str = "") -> ADBDiagnostics:
        diagnostics = self.run_diagnostics(manual_adb_path=manual_adb_path, selected_device_serial=device.identifier)
        self._require_ready_device(device, diagnostics)
        result = self.run_adb_command(["get-state"], device_serial=device.identifier, manual_adb_path=manual_adb_path, timeout=10)
        diagnostics.last_executed_adb_command = result.command
        diagnostics.last_command_exit_code = result.exit_code
        diagnostics.last_stdout = result.stdout
        diagnostics.last_stderr = result.stderr
        if result.exit_code == 0 and result.stdout.strip() == "device":
            diagnostics.user_message = "Device connection is ready."
        else:
            diagnostics.user_message = result.error_message or result.stderr or "Selected device is not ready."
        self.last_diagnostics = diagnostics
        return diagnostics

    def capture_screenshot(
        self,
        device: DeviceInfo,
        output_path: Path,
        manual_adb_path: str = "",
    ) -> ADBCaptureResult:
        diagnostics = self.run_diagnostics(
            manual_adb_path=manual_adb_path,
            selected_device_serial=device.identifier,
            output_folder=str(output_path.parent),
        )
        self._require_ready_device(device, diagnostics)
        self._require_writable_output_folder(output_path.parent, diagnostics)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            output_path.unlink()

        primary_result = self.run_adb_command(
            ["exec-out", "screencap", "-p"],
            device_serial=device.identifier,
            manual_adb_path=manual_adb_path,
            timeout=30,
            binary_stdout=True,
        )
        diagnostics.last_executed_adb_command = primary_result.command
        diagnostics.last_command_exit_code = primary_result.exit_code
        diagnostics.last_stdout = primary_result.stdout
        diagnostics.last_stderr = primary_result.stderr

        if primary_result.exit_code == 0 and primary_result.stdout_bytes:
            try:
                output_path.write_bytes(primary_result.stdout_bytes)
            except OSError as error:
                diagnostics.user_message = f"Permission issue writing the output file: {error}"
                self.last_diagnostics = diagnostics
                raise ADBUserError(diagnostics.user_message, diagnostics)
            validation_error = self._validate_png_file(output_path)
            if not validation_error:
                return self._capture_success(output_path, "exec-out", primary_result, diagnostics)
            self._delete_broken_file(output_path)
            diagnostics.user_message = validation_error
        else:
            diagnostics.user_message = self._capture_error_message(primary_result)

        fallback_result = self._capture_with_fallback(device, output_path, manual_adb_path)
        diagnostics.last_executed_adb_command = fallback_result.command
        diagnostics.last_command_exit_code = fallback_result.exit_code
        diagnostics.last_stdout = fallback_result.stdout
        diagnostics.last_stderr = fallback_result.stderr
        validation_error = self._validate_png_file(output_path)
        if validation_error:
            self._delete_broken_file(output_path)
            diagnostics.last_screenshot_file_path = str(output_path)
            diagnostics.screenshot_file_created = False
            diagnostics.screenshot_file_size_bytes = 0
            diagnostics.capture_method_used = "fallback failed"
            diagnostics.user_message = validation_error
            self.last_diagnostics = diagnostics
            raise ADBUserError(validation_error, diagnostics)

        return self._capture_success(output_path, "fallback pull", fallback_result, diagnostics)

    def launch_app(self, device: DeviceInfo | str, package_name: str, manual_adb_path: str = "") -> None:
        if not package_name:
            raise ADBUserError("Package name is missing. Scan the Android project before launching the app.")
        self._run_device_command(
            device,
            [
                "shell",
                "monkey",
                "-p",
                package_name,
                "-c",
                "android.intent.category.LAUNCHER",
                "1",
            ],
            manual_adb_path,
            15,
            f"Failed to launch {package_name}",
        )

    def get_android_sdk_version(self, device_serial: str, manual_adb_path: str = "") -> str:
        return self._read_required_device_property(device_serial, "ro.build.version.sdk", manual_adb_path)

    def get_android_release_version(self, device_serial: str, manual_adb_path: str = "") -> str:
        return self._read_required_device_property(device_serial, "ro.build.version.release", manual_adb_path)

    def get_device_manufacturer(self, device_serial: str, manual_adb_path: str = "") -> str:
        return self._read_required_device_property(device_serial, "ro.product.manufacturer", manual_adb_path)

    def get_device_model(self, device_serial: str, manual_adb_path: str = "") -> str:
        return self._read_required_device_property(device_serial, "ro.product.model", manual_adb_path)

    def open_locale_settings(self, device_serial: str, manual_adb_path: str = "") -> None:
        result = self.run_adb_command(
            [
                "shell",
                "am",
                "start",
                "-a",
                "android.settings.LOCALE_SETTINGS",
            ],
            device_serial=device_serial,
            manual_adb_path=manual_adb_path,
            timeout=15,
        )
        self._record_command_result(device_serial, result, "Opened Android locale settings.")
        if result.exit_code != 0:
            raise ADBUserError(result.stderr or result.error_message or "Could not open Android locale settings.")

    def go_home(self, device_serial: str, manual_adb_path: str = "") -> None:
        result = self.run_adb_command(
            ["shell", "input", "keyevent", "KEYCODE_HOME"],
            device_serial=device_serial,
            manual_adb_path=manual_adb_path,
            timeout=10,
        )
        self._record_command_result(device_serial, result, "Navigated to Android home screen.")
        if result.exit_code != 0:
            raise ADBUserError(result.stderr or result.error_message or "Could not navigate to home screen.")

    def run_deep_link(self, device_serial: str, deep_link: str, manual_adb_path: str = "") -> None:
        if not deep_link.strip():
            raise ADBUserError("Deep link template is empty.")
        result = self.run_adb_command(
            [
                "shell",
                "am",
                "start",
                "-a",
                "android.intent.action.VIEW",
                "-d",
                deep_link.strip(),
            ],
            device_serial=device_serial,
            manual_adb_path=manual_adb_path,
            timeout=15,
        )
        self._record_command_result(device_serial, result, "Deep link command completed.")
        if result.exit_code != 0:
            raise ADBUserError(result.stderr or result.error_message or "Deep link command failed.")

    def run_broadcast(
        self,
        device_serial: str,
        action: str,
        extra_key: str,
        extra_value: str,
        manual_adb_path: str = "",
    ) -> None:
        if not action.strip() or not extra_key.strip():
            raise ADBUserError("Broadcast action and extra key are required.")
        result = self.run_adb_command(
            [
                "shell",
                "am",
                "broadcast",
                "-a",
                action.strip(),
                "--es",
                extra_key.strip(),
                extra_value,
            ],
            device_serial=device_serial,
            manual_adb_path=manual_adb_path,
            timeout=15,
        )
        self._record_command_result(device_serial, result, "Broadcast command completed.")
        if result.exit_code != 0:
            raise ADBUserError(result.stderr or result.error_message or "Broadcast command failed.")

    def force_stop_app(self, device_serial: str, package_name: str, manual_adb_path: str = "") -> None:
        if not package_name.strip():
            raise ADBUserError("Package name is required to force stop the app.")
        result = self.run_adb_command(
            ["shell", "am", "force-stop", package_name.strip()],
            device_serial=device_serial,
            manual_adb_path=manual_adb_path,
            timeout=12,
        )
        self._record_command_result(device_serial, result, f"Force stopped {package_name}.")
        if result.exit_code != 0:
            raise ADBUserError(result.stderr or result.error_message or f"Could not force stop {package_name}.")

    def tap(self, device: DeviceInfo, x: int, y: int, manual_adb_path: str = "") -> None:
        if x < 0 or y < 0:
            raise ADBUserError("Tap coordinates must be zero or positive.")
        self._run_device_command(
            device,
            ["shell", "input", "tap", str(x), str(y)],
            manual_adb_path,
            12,
            "ADB tap command failed.",
        )

    def tap_ui_element(
        self,
        device_serial: str,
        selector_type: str,
        selector_value: str,
        manual_adb_path: str = "",
    ) -> None:
        if not selector_value.strip():
            raise ADBUserError(f"{selector_type} selector is required for UI tap.")
        temp_file = Path(tempfile.gettempdir()) / f"playpulse_uiautomator_{device_serial}.xml"
        dump_command = ["shell", "uiautomator", "dump", "/sdcard/window_dump.xml"]
        dump_result = self.run_adb_command(
            dump_command,
            device_serial=device_serial,
            manual_adb_path=manual_adb_path,
            timeout=20,
        )
        if dump_result.exit_code != 0:
            raise ADBUserError(dump_result.stderr or dump_result.error_message or "Failed to dump UI hierarchy.")

        pull_result = self.run_adb_command(
            ["pull", "/sdcard/window_dump.xml", str(temp_file)],
            device_serial=device_serial,
            manual_adb_path=manual_adb_path,
            timeout=20,
        )
        if pull_result.exit_code != 0:
            raise ADBUserError(pull_result.stderr or pull_result.error_message or "Failed to pull UI dump.")

        try:
            bounds = self._find_ui_element_bounds(temp_file, selector_type, selector_value)
        finally:
            try:
                if temp_file.exists():
                    temp_file.unlink()
            except OSError:
                temp_file = Path()

        if not bounds:
            raise ADBUserError(f"Could not find UI element for {selector_type}: {selector_value}")
        x = int((bounds[0] + bounds[2]) / 2)
        y = int((bounds[1] + bounds[3]) / 2)
        tap_result = self.run_adb_command(
            ["shell", "input", "tap", str(x), str(y)],
            device_serial=device_serial,
            manual_adb_path=manual_adb_path,
            timeout=12,
        )
        self._record_command_result(device_serial, tap_result, "Tapped UI element.")
        if tap_result.exit_code != 0:
            raise ADBUserError(tap_result.stderr or tap_result.error_message or "Failed to tap UI element.")

    def tap_text(self, device_serial: str, text: str, manual_adb_path: str = "") -> None:
        self.tap_ui_element(device_serial, "text", text, manual_adb_path)

    def tap_content_desc(self, device_serial: str, content_desc: str, manual_adb_path: str = "") -> None:
        self.tap_ui_element(device_serial, "content-desc", content_desc, manual_adb_path)

    def tap_resource_id(self, device_serial: str, resource_id: str, manual_adb_path: str = "") -> None:
        self.tap_ui_element(device_serial, "resource-id", resource_id, manual_adb_path)

    def _find_ui_element_bounds(self, xml_path: Path, selector_type: str, selector_value: str) -> tuple[int, int, int, int] | None:
        try:
            import xml.etree.ElementTree as ET
        except ImportError as error:
            raise ADBUserError(f"XML parser unavailable: {error}")

        tree = ET.parse(str(xml_path))
        root = tree.getroot()
        search_attrs = {
            "text": "text",
            "content-desc": "content-desc",
            "resource-id": "resource-id",
        }
        attr_name = search_attrs.get(selector_type)
        if not attr_name:
            return None

        for node in root.iter("node"):
            value = node.attrib.get(attr_name, "")
            if not value:
                continue
            if value == selector_value or selector_value in value:
                bounds_text = node.attrib.get("bounds", "")
                bounds = self._parse_bounds(bounds_text)
                if bounds:
                    return bounds
        return None

    def _parse_bounds(self, bounds_text: str) -> tuple[int, int, int, int] | None:
        if not bounds_text.startswith("[") or "]" not in bounds_text:
            return None
        try:
            left, top, right, bottom = bounds_text.replace("[", "").replace("]", ",").split(",")[:4]
            return int(left), int(top), int(right), int(bottom)
        except ValueError:
            return None

    def swipe(
        self,
        device: DeviceInfo,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration_ms: int,
        manual_adb_path: str = "",
    ) -> None:
        if min(start_x, start_y, end_x, end_y) < 0:
            raise ADBUserError("Swipe coordinates must be zero or positive.")
        if duration_ms <= 0:
            raise ADBUserError("Swipe duration must be greater than zero.")
        self._run_device_command(
            device,
            [
                "shell",
                "input",
                "swipe",
                str(start_x),
                str(start_y),
                str(end_x),
                str(end_y),
                str(duration_ms),
            ],
            manual_adb_path,
            15,
            "ADB swipe command failed.",
        )

    def press_back(self, device: DeviceInfo, manual_adb_path: str = "") -> None:
        self._run_device_command(
            device,
            ["shell", "input", "keyevent", "KEYCODE_BACK"],
            manual_adb_path,
            10,
            "ADB back command failed.",
        )

    def enter_text(self, device: DeviceInfo, text: str, manual_adb_path: str = "") -> None:
        prepared_text = self._prepare_input_text(text)
        if not prepared_text:
            raise ADBUserError("Text input step is empty.")
        self._run_device_command(
            device,
            ["shell", "input", "text", prepared_text],
            manual_adb_path,
            15,
            "ADB text input command failed.",
        )

    def wait(self, seconds: float) -> None:
        if seconds < 0:
            raise ADBUserError("Wait duration must be zero or greater.")
        time.sleep(seconds)

    def run_adb_command(
        self,
        args: List[str],
        device_serial: str | None = None,
        timeout: int = 60,
        binary_stdout: bool = False,
        manual_adb_path: str = "",
    ) -> ADBCommandResult:
        path_info = self.resolve_adb_path(manual_adb_path)
        if not path_info.found:
            result = ADBCommandResult(error_message=path_info.error_message)
            self.last_command_result = result
            return result

        command_args = list(args)
        if device_serial and not (len(command_args) >= 2 and command_args[0] == "-s"):
            command_args = ["-s", device_serial] + command_args
        command = [path_info.path] + command_args
        command_text = " ".join(command)
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            result = ADBCommandResult(
                command=command_text,
                exit_code=None,
                timed_out=True,
                error_message=f"ADB command timed out after {timeout} seconds.",
                stdout=(error.stdout or b"").decode("utf-8", errors="replace"),
                stderr=(error.stderr or b"").decode("utf-8", errors="replace"),
            )
            self.last_command_result = result
            return result
        except OSError as error:
            result = ADBCommandResult(command=command_text, error_message=str(error), stderr=str(error))
            self.last_command_result = result
            return result

        stdout_text = ""
        stdout_bytes = b""
        if binary_stdout:
            stdout_bytes = completed.stdout
            stdout_text = self._summarize_binary_stdout(stdout_bytes)
        else:
            stdout_text = completed.stdout.decode("utf-8", errors="replace")

        result = ADBCommandResult(
            command=command_text,
            exit_code=completed.returncode,
            stdout=stdout_text,
            stderr=completed.stderr.decode("utf-8", errors="replace"),
            stdout_bytes=stdout_bytes,
        )
        self.last_command_result = result
        return result

    def parse_devices(self, output: str) -> List[DeviceInfo]:
        devices: List[DeviceInfo] = []
        for line in output.splitlines():
            line = line.strip()
            if not line or line.startswith("List of devices"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue

            identifier = parts[0]
            status = parts[1]
            detail_parts = parts[2:]
            model = self._value_for_key(detail_parts, "model")
            product = self._value_for_key(detail_parts, "product")
            description = model or product or "Android device"
            devices.append(DeviceInfo(identifier, description.replace("_", " "), status))
        return devices

    def is_output_folder_writable(self, output_folder: str) -> bool:
        if not output_folder:
            return False
        folder = Path(output_folder).expanduser()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix="playpulse_write_test_", dir=folder, delete=True):
                return True
        except OSError:
            return False

    def _read_device_property(self, device_serial: str, property_name: str, manual_adb_path: str = "") -> str:
        result = self.run_adb_command(
            ["shell", "getprop", property_name],
            device_serial=device_serial,
            manual_adb_path=manual_adb_path,
            timeout=12,
        )
        self._record_command_result(device_serial, result, f"Read Android device property {property_name}.")
        if result.exit_code != 0:
            return ""
        return result.stdout.strip()

    def _read_required_device_property(self, device_serial: str, property_name: str, manual_adb_path: str = "") -> str:
        value = self._read_device_property(device_serial, property_name, manual_adb_path)
        if value:
            return value
        raise ADBUserError(f"Could not read Android device property: {property_name}.")

    def _run_device_command(
        self,
        device: DeviceInfo | str,
        args: List[str],
        manual_adb_path: str,
        timeout: int,
        failure_message: str,
    ) -> None:
        diagnostics = self.last_diagnostics or ADBDiagnostics()
        if isinstance(device, str):
            device = DeviceInfo(device, "Android device", "device")
        diagnostics.selected_device_serial = device.identifier
        self._require_ready_device(device, diagnostics)
        result = self.run_adb_command(
            args,
            device_serial=device.identifier,
            manual_adb_path=manual_adb_path,
            timeout=timeout,
        )
        diagnostics.last_executed_adb_command = result.command
        diagnostics.last_command_exit_code = result.exit_code
        diagnostics.last_stdout = result.stdout
        diagnostics.last_stderr = result.stderr
        if result.exit_code == 0 and not result.timed_out:
            diagnostics.user_message = "ADB command completed successfully."
            self.last_diagnostics = diagnostics
            return

        if result.timed_out:
            message = "ADB command timed out."
        else:
            message = result.error_message or result.stderr or failure_message
        diagnostics.user_message = message
        self.last_diagnostics = diagnostics
        raise ADBUserError(message, diagnostics)

    def _record_command_result(self, device_serial: str, result: ADBCommandResult, success_message: str) -> None:
        diagnostics = self.last_diagnostics or ADBDiagnostics()
        diagnostics.selected_device_serial = device_serial
        diagnostics.last_executed_adb_command = result.command
        diagnostics.last_command_exit_code = result.exit_code
        diagnostics.last_stdout = result.stdout
        diagnostics.last_stderr = result.stderr
        if result.exit_code == 0 and not result.timed_out:
            diagnostics.user_message = success_message
        elif result.timed_out:
            diagnostics.user_message = "ADB command timed out."
        else:
            diagnostics.user_message = result.error_message or result.stderr
        self.last_diagnostics = diagnostics

    def _prepare_input_text(self, text: str) -> str:
        prepared = text.strip()
        replacements = {
            " ": "%s",
            "\\": "\\\\",
            "&": "\\&",
            "<": "\\<",
            ">": "\\>",
            "|": "\\|",
            ";": "\\;",
            "(": "\\(",
            ")": "\\)",
            '"': '\\"',
            "'": "\\'",
        }
        for source, replacement in replacements.items():
            prepared = prepared.replace(source, replacement)
        return prepared

    def _capture_with_fallback(
        self,
        device: DeviceInfo,
        output_path: Path,
        manual_adb_path: str,
    ) -> ADBCommandResult:
        remote_path = "/sdcard/playpulse_screen.png"
        shell_result = self.run_adb_command(
            ["shell", "screencap", "-p", remote_path],
            device_serial=device.identifier,
            manual_adb_path=manual_adb_path,
            timeout=30,
        )
        if shell_result.exit_code != 0:
            return shell_result

        pull_result = self.run_adb_command(
            ["pull", remote_path, str(output_path)],
            device_serial=device.identifier,
            manual_adb_path=manual_adb_path,
            timeout=30,
        )
        self.run_adb_command(
            ["shell", "rm", remote_path],
            device_serial=device.identifier,
            manual_adb_path=manual_adb_path,
        )
        return pull_result

    def _capture_success(
        self,
        output_path: Path,
        method_used: str,
        command_result: ADBCommandResult,
        diagnostics: ADBDiagnostics,
    ) -> ADBCaptureResult:
        file_size = output_path.stat().st_size
        diagnostics.last_screenshot_file_path = str(output_path)
        diagnostics.screenshot_file_created = True
        diagnostics.screenshot_file_size_bytes = file_size
        diagnostics.capture_method_used = method_used
        diagnostics.last_executed_adb_command = command_result.command
        diagnostics.last_command_exit_code = command_result.exit_code
        diagnostics.last_stdout = command_result.stdout
        diagnostics.last_stderr = command_result.stderr
        diagnostics.user_message = "Screenshot captured successfully."
        self.last_diagnostics = diagnostics
        return ADBCaptureResult(str(output_path), method_used, file_size, command_result)

    def _require_ready_device(self, device: DeviceInfo, diagnostics: ADBDiagnostics) -> None:
        status = device.status.lower()
        if status == "device":
            return
        if status == "offline":
            message = "Selected device is offline. Restart the emulator/device and run adb devices."
        elif status == "unauthorized":
            message = "Selected device is unauthorized. Approve the USB debugging prompt on the device."
        elif status == "mock":
            message = "No ready Android device was found. Start an emulator or connect a device, then run adb devices."
        else:
            message = f"Selected device is not ready. Current adb status: {device.status}."
        diagnostics.user_message = message
        self.last_diagnostics = diagnostics
        raise ADBUserError(message, diagnostics)

    def _require_writable_output_folder(self, output_folder: Path, diagnostics: ADBDiagnostics) -> None:
        if self.is_output_folder_writable(str(output_folder)):
            return
        diagnostics.user_message = "Screenshot output folder is not writable. Choose another folder."
        self.last_diagnostics = diagnostics
        raise ADBUserError(diagnostics.user_message, diagnostics)

    def _validate_png_file(self, output_path: Path) -> str:
        if not output_path.exists():
            return "Screenshot file was not created."
        if output_path.stat().st_size <= 0:
            return "Screencap returned empty output."
        with output_path.open("rb") as handle:
            signature = handle.read(len(PNG_SIGNATURE))
        if signature != PNG_SIGNATURE:
            return "Created file is not a valid PNG."
        return ""

    def _delete_broken_file(self, output_path: Path) -> None:
        try:
            if output_path.exists():
                output_path.unlink()
        except OSError:
            return

    def _capture_error_message(self, result: ADBCommandResult) -> str:
        if result.timed_out:
            return "ADB screencap command timed out."
        if result.error_message:
            return result.error_message
        if result.exit_code != 0:
            return result.stderr or "ADB screencap command failed."
        if not result.stdout_bytes:
            return "Screencap returned empty output."
        return "ADB screencap failed."

    def _summarize_binary_stdout(self, stdout_bytes: bytes) -> str:
        if not stdout_bytes:
            return ""
        signature = stdout_bytes[:8].hex(" ").upper()
        return f"<{len(stdout_bytes)} bytes, first bytes: {signature}>"

    def _value_for_key(self, parts: List[str], key: str) -> str:
        prefix = f"{key}:"
        for part in parts:
            if part.startswith(prefix):
                return part.removeprefix(prefix)
        return ""
