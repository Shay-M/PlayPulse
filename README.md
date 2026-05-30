# PlayPulse

PlayPulse is a professional PyQt6 desktop frontend for Android Store localization and deployment workflows. It guides an Android app through project scanning, locale selection, localized Google Play metadata generation, screenshot preparation, deployment validation, and centralized logs.

The current version is frontend-first, with a hardened manual ADB screenshot workflow, an internal JSON-based ADB flow engine, and replaceable service classes so Gemini, Maestro, Fastlane, and Google Play integrations can be added later without rewriting the UI.

## Features

- Sidebar workflow: Project Setup, Store Metadata, Screenshots, Deployment, and Logs
- Android project scanning for Gradle files, AndroidManifest.xml, package name, and `app/src/main/res/values*` locale folders
- Locale detection for folders such as `values`, `values-he`, `values-iw`, `values-fr`, `values-es`, `values-de`, `values-pt-rBR`, and `values-zh-rCN`
- Manual locale add/remove support
- Editable generated Google Play metadata table with title, short description, full description, and status
- Google Play character hints: 30 character title, 80 character short description, 4000 character full description
- Real ADB device discovery and `screencap` PNG capture when Android platform-tools are installed
- Automatic fallback screenshot capture using `shell screencap`, `pull`, and cleanup when `exec-out` fails
- Internal ADB Flow Engine for repeatable JSON-based screenshot flows without Maestro
- Simplified Locale Preparation workflow with readiness validation before multi-locale capture
- Persistent ADB settings using `QSettings`, including saved `adb.exe` path, selected device, output folder, and last project path
- Flow Editor with add, duplicate, delete, save, load, step editing, single-step run, full-flow run, and all-enabled-flow run
- Mock screenshot capture fallback for UI demos without a connected device
- Flexible screenshot flow planning with presets, manual flows, mock project screen discovery, and optional Maestro YAML flow loading
- ADB diagnostics panel with adb path resolution, raw `adb devices -l` output, command stdout/stderr, and screenshot file validation
- Mock Fastlane / Google Play validation and upload simulation
- Shared `AppState`, centralized `LogService`, reusable background worker utilities, and QSS light theme

## Requirements

- Python 3.11+
- PyQt6 6.7.0
- Android platform-tools for real screenshot capture

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

## Run

```bash
python -m app.main
```

## What Is Mocked

The UI is fully navigable and functional. Manual screenshot capture can use real ADB when `adb` is available and a device or emulator is connected. These integrations are still simulated or optional:

- Gemini API metadata generation
- Fastlane Screengrab
- Fastlane Supply
- Google Play Developer API upload
- Maestro screenshot flows are optional and not required for manual capture

## Real Manual Screenshot Capture

To capture real screenshots:

1. Install Android platform-tools so `adb` is available in `PATH`, `ANDROID_HOME`, `ANDROID_SDK_ROOT`, or select `adb.exe` manually in the Screenshots page.
2. Start an emulator or connect a device with USB debugging enabled.
3. Open the Screenshots page and click `Run ADB Diagnostics`.
4. Click `Refresh devices`.
5. Choose `Real ADB screencap` as the capture backend.
6. Navigate the app manually on the emulator/device to the screen you want.
7. Select the relevant flow row and click `Capture selected now`.

PlayPulse validates the screenshot file after capture. It checks the adb exit code, file existence, file size, and PNG signature bytes.

## ADB Path and Android Version Detection

`adb` does not have to be available globally in PowerShell. PlayPulse can use the full Android SDK platform-tools path and save it between runs.

Example Windows path:

```text
C:\Users\shay\AppData\Local\Android\Sdk\platform-tools\adb.exe
```

On the Screenshots page:

1. Click `Select adb.exe manually` and choose the full `adb.exe` path.
2. Click `Save adb path`.
3. Click `Test adb path` or `Run ADB Diagnostics`.
4. Select the real device serial, for example `emulator-5554`.
5. Click `Detect Android version`.

All ADB operations go through `ADBService.run_adb_command(...)`, so device refresh, diagnostics, Android version detection, manual screenshots, fallback screenshots, internal flows, locale preparation, and widget capture all use the same resolved `adb.exe` path.

Android version detection runs the resolved command with the selected serial:

```text
<resolved_adb_path> -s <device_serial> shell getprop ro.build.version.sdk
<resolved_adb_path> -s <device_serial> shell getprop ro.build.version.release
<resolved_adb_path> -s <device_serial> shell getprop ro.product.manufacturer
<resolved_adb_path> -s <device_serial> shell getprop ro.product.model
```

If it fails, copy ADB diagnostics. They include the resolved path, selected serial, last command, exit code, stdout, and stderr.

## Internal ADB Flow Engine

The Screenshots page includes PlayPulse's own internal automation backend for repeatable screenshot flows. It does not require Maestro.

Internal flows are saved as JSON files under `playpulse_flows/`. A minimal flow looks like this:

```json
{
  "name": "Home screen",
  "description": "Launches the app and captures the home screen",
  "steps": [
    { "type": "launch_app" },
    { "type": "wait", "seconds": 2 },
    { "type": "take_screenshot", "name": "home" }
  ]
}
```

Supported first-version step types:

- `launch_app`
- `wait`
- `tap_coordinates`
- `tap_text`
- `tap_content_desc`
- `tap_resource_id`
- `swipe`
- `press_back`
- `enter_text`
- `open_locale_settings`
- `go_home`
- `force_stop_app`
- `run_deep_link`
- `run_broadcast`
- `take_screenshot`

To run an internal flow:

1. Scan the Android project so PlayPulse detects the package name.
2. Confirm ADB diagnostics pass and a ready device is selected.
3. Use the Flow Editor on the Screenshots page to create or load flows.
4. Select a screenshot output folder.
5. Run a selected step, one full flow, or all enabled flows.

Each run reports progress per step, for example `Running step 1/3: launch_app`. If a step fails, the flow stops and the ADB diagnostics panel keeps the last command, stdout, stderr, and screenshot validation details.

## Localized Screenshots and Locale Preparation

Saving screenshots under locale folders does not automatically change the app or Android device language. Locale folders only control where screenshots are saved.

To capture real localized screenshots, configure and test Locale Preparation before running a multi-locale capture.

The Screenshots page now shows a readiness summary and a per-locale table before capture:

- Capture target
- Language preparation configured or not configured
- Selected locale count
- Ready to capture yes/no
- Resolved adb path status
- Selected device serial
- Per-locale assigned command or flow
- Last preparation test result

For in-app screenshots, PlayPulse shows only:

- `Current language only`
- `App debug command`
- `In-app recorded language flow`
- `Combined: device + app language`

For widget and home-screen screenshots, PlayPulse shows only:

- `Current language only`
- `Device language recorded flow`
- `Combined: device + app language`

Multi-locale capture is blocked when Locale Preparation is not real enough to change language:

- One locale with `Current language only` is allowed.
- Multiple locales with `Current language only` are blocked.
- `App debug command` requires a valid deep link template or broadcast configuration.
- `In-app recorded language flow` requires every locale to have an assigned app-language flow.
- `Device language recorded flow` requires every locale to have an assigned device-language flow.
- Opening Android language settings alone is not considered a successful language change.

For apps you control, the most reliable app-level approach is usually a debug-only deep link or broadcast that changes the app locale internally. For widgets, Android system language often matters because widgets can be rendered by the launcher, so device language preparation or combined mode is usually required.

Device language switching is Android-version, device, emulator, and launcher dependent. Recorded device language flows may need to be created per emulator type or Android version. Manual ADB screenshot capture remains available for quick testing and diagnosis.

Locale preparation settings are saved to:

```text
playpulse_flows/locale_preparation.json
```

Example:

```json
{
  "capture_target_type": "widget_home_screen",
  "locale_preparation_mode": "combined",
  "app_debug_command": {
    "type": "deep_link",
    "template": "myapp://playpulse/set-locale?locale={locale}"
  },
  "common_options": {
    "force_stop_after_locale_change": true,
    "relaunch_after_locale_change": true,
    "wait_after_locale_change_seconds": 2,
    "go_home_before_widget_capture": true,
    "wait_for_widget_render_seconds": 3
  },
  "app_language_flows": {
    "en-US": "Set App Language - English",
    "he-IL": "Set App Language - Hebrew"
  },
  "device_language_flows": {
    "en-US": "Set Device Language - English",
    "he-IL": "Set Device Language - Hebrew"
  }
}
```

## Why Are All Screenshots in the Same Language?

If every locale folder contains screenshots in the same language, the files were saved into separate folders but the app or device language was not changed before capture.

Use one of these preparation methods before running all captures:

- `App debug command` for apps that expose a debug deep link or broadcast.
- `In-app recorded language flow` when language is changed inside the app settings UI.
- `Device language recorded flow` for Android system language changes.
- `Combined: device + app language` when capturing both app screens and widgets.

Always click `Test selected locale` or `Test all locales` before a full capture. For widget screenshots, device language preparation is usually required.

## Manual Screenshot Troubleshooting

If manual screenshot capture does not work:

1. Click `Run ADB Diagnostics` on the Screenshots page.
2. Run this in a terminal:

```bash
adb devices -l
```

3. Check that the selected device status is `device`, not `offline` or `unauthorized`.
4. If adb is not detected, click `Select adb.exe manually` and choose the Android SDK platform-tools `adb.exe`.
5. Click `Save adb path` so PlayPulse remembers it between runs.
6. Click `Test device connection`.
7. Click `Test screencap command`.
8. Confirm the screenshot output folder exists and is writable.
9. Confirm the app is installed, open, and visible on the emulator/device.
10. If `exec-out` fails, PlayPulse automatically tries the fallback capture method:

```bash
adb -s <device_serial> shell screencap -p /sdcard/playpulse_screen.png
adb -s <device_serial> pull /sdcard/playpulse_screen.png <local_output_file>
adb -s <device_serial> shell rm /sdcard/playpulse_screen.png
```

11. Click `Copy diagnostics to clipboard` and share the diagnostics text if the issue persists.

The diagnostics panel reports the adb path, how adb was found, adb version, raw device output, selected serial, capture backend, output folder writability, last adb command, exit code, stdout, stderr, last screenshot path, whether the file exists, file size, and the capture method used.

## Optional Maestro Flow Capture

Manual ADB capture does not require Maestro. Maestro remains optional for automated navigation before screenshots:

1. Install the Maestro CLI and make sure `maestro` is available in your terminal.
2. Create `.yaml` or `.yml` flow files, for example in `.maestro/`.
3. On the Screenshots page, select the Maestro flows folder and click `Load Maestro flows`.
4. Choose `Maestro flow + ADB screencap` as the capture backend.
5. Run selected flows or all listed flows.

PlayPulse runs `maestro test <flow-file>` and then captures the device screen with ADB. The screenshot files are written per locale under the configured screenshot output folder.

## Future Internal Engine Direction

The internal engine now supports the first repeatable ADB flow commands. Future versions can extend it with richer screen-aware steps:

- tap by text using `uiautomator dump`
- conditional waits
- reusable flow fragments
- visual step previews
- device profile presets

## Planned Integrations

Future versions can replace the mock service implementations in `app/services/` with real integrations:

- `gemini_service.py`: Gemini API prompts and localized metadata generation
- `adb_service.py`: real `adb devices` parsing, diagnostics, screenshot capture, and internal flow commands
- `internal_adb_flow_service.py`: JSON flow loading, saving, and internal ADB step execution
- `locale_preparation_service.py`: locale preparation settings persistence
- `screenshot_service.py`: manual capture orchestration, optional Maestro flow execution, and future Fastlane Screengrab support
- `fastlane_service.py`: Fastlane metadata validation and Supply upload
- Google Play Developer API: service-account based store listing deployment

## Project Structure

```text
app/
  main.py
  ui/
    main_window.py
    styles.py
    workers.py
    pages/
      project_setup_page.py
      metadata_page.py
      screenshots_page.py
      deployment_page.py
      logs_page.py
    components/
      status_badge.py
      card.py
      progress_panel.py
      log_panel.py
  services/
    app_state.py
    log_service.py
    project_scanner.py
    gemini_service.py
    adb_service.py
    internal_adb_flow_service.py
    locale_preparation_service.py
    settings_service.py
    screenshot_service.py
    fastlane_service.py
  models/
    locale_info.py
    metadata_info.py
    device_info.py
    screenshot_flow.py
    internal_flow.py
    locale_preparation.py
    deployment_status.py
requirements.txt
README.md
```

## Notes

The app uses `QThreadPool` and `QRunnable` through `app/ui/workers.py` for long-running operations. The same worker pattern is ready for real network calls, command execution, screenshot capture, and upload workflows.
