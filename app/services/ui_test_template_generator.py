from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable, Mapping


class UITestTemplateGenerator:
    DEFAULT_PACKAGE_NAME = "com.example.playpulse"
    DEFAULT_SCREENSHOT_NAMES = ("home", "after_navigation")
    SCREENSHOT_DIRECTORY_NAME = "playpulse_screenshots"

    def __init__(
        self,
        project_path: str,
        package_name: str,
        app_module_path: str = "app",
        test_package_name: str | None = None,
        screenshot_names: Iterable[str] | None = None,
        locales: Iterable[str] | None = None,
        clean_output_before_run: bool = True,
        feature_flags: Mapping[str, object] | None = None,
    ) -> None:
        self.project_path = Path(project_path).expanduser() if project_path else Path.cwd()
        self.package_name = self._normalize_package_name(package_name)
        self.app_module_path = self._normalize_module_path(app_module_path)
        self.test_package_name = self._normalize_package_name(
            test_package_name or f"{self.package_name}.playpulse"
        )
        self.screenshot_names = tuple(
            self._safe_identifier(name) for name in (screenshot_names or self.DEFAULT_SCREENSHOT_NAMES)
        )
        self.locales = tuple(self._safe_locale(locale) for locale in (locales or ("current",)))
        self.clean_output_before_run = clean_output_before_run
        self.feature_flags = dict(feature_flags or {})

    def generate_templates(self) -> Dict[str, str]:
        files: Dict[str, str] = {}
        package_path = self.test_package_name.replace(".", "/")
        base_path = f"{self.app_module_path}/src/androidTest/java/{package_path}"

        files[f"{base_path}/PlayPulseTestConfig.kt"] = self._test_config_template()
        files[f"{base_path}/PlayPulseLocaleHelper.kt"] = self._locale_helper_template()
        files[f"{base_path}/PlayPulseScreenshotHelper.kt"] = self._screenshot_helper_template()
        files[f"{base_path}/PlayPulseScreenshotTest.kt"] = self._screenshot_test_template()
        return files

    def deploy_templates(self, overwrite: bool = False) -> Dict[str, list[str]]:
        return self.write_templates(self.generate_templates(), overwrite=overwrite)

    def write_templates(self, files: Dict[str, str], overwrite: bool = False) -> Dict[str, list[str]]:
        results = {
            "written": [],
            "skipped": [],
            "errors": [],
        }
        for relative_path, contents in files.items():
            path = self.project_path / relative_path
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists() and not overwrite:
                    results["skipped"].append(str(relative_path))
                    continue
                path.write_text(contents, encoding="utf-8")
                results["written"].append(str(relative_path))
            except OSError as exc:
                results["errors"].append(f"{relative_path}: {exc}")
        return results

    def _test_config_template(self) -> str:
        screenshot_names = ", ".join(f'"{name}"' for name in self.screenshot_names)
        locales = ", ".join(f'"{locale}"' for locale in self.locales)
        feature_flags = self._feature_flags_template()
        clean_output = "true" if self.clean_output_before_run else "false"

        template = """package {test_package}

object PlayPulseTestConfig {
    const val APP_PACKAGE_NAME = "{app_package}"
    const val SCREENSHOT_DIRECTORY_NAME = "{screenshot_directory}"
    const val CLEAN_OUTPUT_BEFORE_RUN = {clean_output}
    const val APP_LAUNCH_TIMEOUT_MS = 10_000L
    const val SCREEN_SETTLE_MS = 1_500L
    const val WAIT_AFTER_LOCALE_CHANGE_MS = 1_500L
    const val LOCALE_BROADCAST_ACTION = "{app_package}.PLAYPULSE_SET_LOCALE"
    const val LOCALE_EXTRA_KEY = "locale"

    val DEFAULT_LOCALES = arrayOf({locales})
    val SCREENSHOT_NAMES = arrayOf({screenshot_names})
    val FEATURE_FLAGS = {feature_flags}
}
"""
        return (
            template.replace("{test_package}", self.test_package_name)
            .replace("{app_package}", self.package_name)
            .replace("{screenshot_directory}", self.SCREENSHOT_DIRECTORY_NAME)
            .replace("{clean_output}", clean_output)
            .replace("{locales}", locales)
            .replace("{screenshot_names}", screenshot_names)
            .replace("{feature_flags}", feature_flags)
        )

    def _locale_helper_template(self) -> str:
        template = """package {test_package}

import android.app.Instrumentation
import android.content.Intent
import android.util.Log

object PlayPulseLocaleHelper {
    private const val TAG = "PlayPulseLocaleHelper"

    fun setAppLocale(instrumentation: Instrumentation, localeTag: String) {
        if (localeTag == "current") {
            Log.i(TAG, "Using current app language")
            return
        }

        val context = instrumentation.targetContext
        val intent = Intent(PlayPulseTestConfig.LOCALE_BROADCAST_ACTION).apply {
            setPackage(PlayPulseTestConfig.APP_PACKAGE_NAME)
            putExtra(PlayPulseTestConfig.LOCALE_EXTRA_KEY, localeTag)
        }
        context.sendBroadcast(intent)
        Log.i(TAG, "Locale broadcast sent: ${PlayPulseTestConfig.LOCALE_BROADCAST_ACTION}, locale=$localeTag")
        Thread.sleep(PlayPulseTestConfig.WAIT_AFTER_LOCALE_CHANGE_MS)
    }
}
"""
        return template.replace("{test_package}", self.test_package_name)

    def _screenshot_helper_template(self) -> str:
        template = """package {test_package}

import android.graphics.BitmapFactory
import android.util.Log
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.UiDevice
import java.io.File

object PlayPulseScreenshotHelper {
    private const val TAG = "PlayPulseScreenshot"

    fun clearOutputDirectory() {
        val directory = screenshotDirectory()
        directory.listFiles()?.forEach { child ->
            val deleted = child.deleteRecursively()
            if (!deleted) {
                Log.w(TAG, "Could not delete stale screenshot path: ${child.absolutePath}")
            }
        }
    }

    fun capture(locale: String, name: String, device: UiDevice = currentDevice()): File {
        val localeDirectory = File(screenshotDirectory(), safeFileName(locale))
        if (!localeDirectory.exists() && !localeDirectory.mkdirs()) {
            throw IllegalStateException("Could not create locale screenshot directory: ${localeDirectory.absolutePath}")
        }
        val outputFile = File(localeDirectory, "${safeFileName(name)}.png")
        if (outputFile.exists() && !outputFile.delete()) {
            throw AssertionError("Could not replace existing screenshot: ${outputFile.absolutePath}")
        }

        val captured = device.takeScreenshot(outputFile)
        if (!captured) {
            throw AssertionError("UiDevice failed to capture screenshot: ${outputFile.absolutePath}")
        }
        if (!outputFile.exists() || outputFile.length() == 0L) {
            throw AssertionError("Screenshot file was not written: ${outputFile.absolutePath}")
        }

        val bitmap = BitmapFactory.decodeFile(outputFile.absolutePath)
            ?: throw AssertionError("Screenshot is not a readable bitmap: ${outputFile.absolutePath}")
        val width = bitmap.width
        val height = bitmap.height
        bitmap.recycle()

        Log.i(TAG, "Screenshot saved: ${outputFile.absolutePath} (${width}x${height}, ${outputFile.length()} bytes)")
        return outputFile
    }

    fun screenshotDirectoryPath(): String = screenshotDirectory().absolutePath

    private fun screenshotDirectory(): File {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val externalFilesRoot = context.getExternalFilesDir(null)
            ?: throw IllegalStateException("Target app external files directory is unavailable")
        val directory = File(externalFilesRoot, PlayPulseTestConfig.SCREENSHOT_DIRECTORY_NAME)
        if (!directory.exists() && !directory.mkdirs()) {
            throw IllegalStateException("Could not create screenshot directory: ${directory.absolutePath}")
        }
        return directory
    }

    private fun currentDevice(): UiDevice {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        return UiDevice.getInstance(instrumentation)
    }

    private fun safeFileName(value: String): String {
        val cleaned = value.trim().replace(Regex("[^A-Za-z0-9._-]+"), "_").trim('_', '.', '-')
        return cleaned.ifEmpty { "screen" }
    }
}
"""
        return template.replace("{test_package}", self.test_package_name)

    def _screenshot_test_template(self) -> str:
        template = """package {test_package}

import android.content.Intent
import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PlayPulseScreenshotTest {
    private lateinit var device: UiDevice

    @Before
    fun setUp() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        device = UiDevice.getInstance(instrumentation)
        if (PlayPulseTestConfig.CLEAN_OUTPUT_BEFORE_RUN) {
            PlayPulseScreenshotHelper.clearOutputDirectory()
        }
    }

    @Test
    fun capturePlayPulseScreenshots() {
        Log.i(TAG, "Writing screenshots to ${PlayPulseScreenshotHelper.screenshotDirectoryPath()}")
        val instrumentation = InstrumentationRegistry.getInstrumentation()

        for (locale in PlayPulseTestConfig.DEFAULT_LOCALES) {
            PlayPulseLocaleHelper.setAppLocale(instrumentation, locale)
            launchApp()
            waitForApp()
            Thread.sleep(PlayPulseTestConfig.SCREEN_SETTLE_MS)

            for (screenName in PlayPulseTestConfig.SCREENSHOT_NAMES) {
                PlayPulseScreenshotHelper.capture(locale, screenName, device)
            }
        }
    }

    private fun launchApp() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val launchIntent = context.packageManager.getLaunchIntentForPackage(PlayPulseTestConfig.APP_PACKAGE_NAME)
            ?: throw AssertionError("No launcher activity found for ${PlayPulseTestConfig.APP_PACKAGE_NAME}")
        launchIntent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TASK or Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(launchIntent)
    }

    private fun waitForApp() {
        val found = device.wait(
            Until.hasObject(By.pkg(PlayPulseTestConfig.APP_PACKAGE_NAME).depth(0)),
            PlayPulseTestConfig.APP_LAUNCH_TIMEOUT_MS,
        )
        assertTrue("App did not reach the foreground: ${PlayPulseTestConfig.APP_PACKAGE_NAME}", found)
    }

    companion object {
        private const val TAG = "PlayPulseScreenshotTest"
    }
}
"""
        return template.replace("{test_package}", self.test_package_name)

    def _feature_flags_template(self) -> str:
        if not self.feature_flags:
            return "emptyMap<String, String>()"
        pairs = []
        for key, value in sorted(self.feature_flags.items()):
            safe_key = self._escape_kotlin_string(str(key))
            safe_value = self._escape_kotlin_string(str(value))
            pairs.append(f'"{safe_key}" to "{safe_value}"')
        return "mapOf(" + ", ".join(pairs) + ")"

    def _normalize_package_name(self, package_name: str | None) -> str:
        candidate = (package_name or self.DEFAULT_PACKAGE_NAME).strip()
        if self._is_valid_package(candidate):
            return candidate
        return self.DEFAULT_PACKAGE_NAME

    def _normalize_module_path(self, module_path: str | None) -> str:
        candidate = (module_path or "app").replace("\\", "/").strip("/")
        return candidate or "app"

    def _safe_identifier(self, value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value).strip()).strip("._-")
        return cleaned or "screen"

    def _safe_locale(self, value: str) -> str:
        cleaned = str(value or "").strip().replace("_", "-")
        if not cleaned:
            return "current"
        if re.fullmatch(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*", cleaned) or cleaned == "current":
            return cleaned
        return "current"

    def _is_valid_package(self, value: str) -> bool:
        package_part = r"[A-Za-z_][A-Za-z0-9_]*"
        return bool(re.fullmatch(rf"{package_part}(\.{package_part})+", value))

    def _escape_kotlin_string(self, value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')
