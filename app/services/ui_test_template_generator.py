from __future__ import annotations

from pathlib import Path
from typing import Dict


class UITestTemplateGenerator:
    DEFAULT_PACKAGE_NAME = "com.example.playpulse"

    def __init__(self, project_path: str, package_name: str) -> None:
        self.project_path = Path(project_path) if project_path else Path.cwd()
        self.package_name = (package_name or self.DEFAULT_PACKAGE_NAME).strip() or self.DEFAULT_PACKAGE_NAME

    def generate_templates(self) -> Dict[str, str]:
        files: Dict[str, str] = {}
        package_name = self.package_name
        # target subpackage 'playpulse'
        full_package = f"{package_name}.playpulse"
        package_path = full_package.replace(".", "/")

        # Always generate Kotlin test helpers and config to keep implementation consistent
        files[f"app/src/androidTest/java/{package_path}/PlayPulseTestConfig.kt"] = self._test_config_template(package_name)
        files[f"app/src/androidTest/java/{package_path}/PlayPulseScreenshotHelper.kt"] = self._screenshot_helper_template(package_name)
        files[f"app/src/androidTest/java/{package_path}/PlayPulseLocaleHelper.kt"] = self._locale_helper_template(package_name)
        files[f"app/src/androidTest/java/{package_path}/PlayPulseScreenshotTest.kt"] = self._kotlin_playpulse_test_template(package_name)
        return files

    def write_templates(self, files: Dict[str, str]) -> Dict[str, list[str]]:
        results = {
            "written": [],
            "skipped": [],
            "errors": [],
        }
        for relative_path, contents in files.items():
            path = self.project_path / relative_path
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists():
                    results["skipped"].append(str(relative_path))
                    continue
                path.write_text(contents, encoding="utf-8")
                results["written"].append(str(relative_path))
            except OSError as exc:
                results["errors"].append(f"{relative_path}: {exc}")
        return results

    def _detect_kotlin(self) -> bool:
        candidates = [
            self.project_path / "app" / "build.gradle.kts",
            self.project_path / "app" / "build.gradle",
        ]
        for candidate in candidates:
            if candidate.exists() and candidate.suffix == ".kts":
                return True
            if candidate.exists():
                try:
                    content = candidate.read_text(encoding="utf-8", errors="ignore")
                    if "kotlin-android" in content or "composeOptions" in content:
                        return True
                except OSError:
                    continue
        return False

    def _build_test_template(self, package_name: str, use_kotlin: bool) -> str:
        if use_kotlin:
            return self._kotlin_test_template(package_name)
        return self._java_test_template(package_name)

    def _kotlin_test_template(self, package_name: str) -> str:
        template = """package {package_name}

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import org.junit.Assert
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
        device.pressHome()
    }

    @Test
    fun captureSampleScreenshot() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val appPackage = "{package_name}"
        device.wait(Until.hasObject(By.pkg(appPackage).depth(0)), 10_000)

        // TODO: Navigate to the target app screen before capturing a screenshot.
        // Add a helper, Espresso action, or UI Automator flow here.

        val fileName = "playpulse_screenshot_sample.png"
        val outputFile = instrumentation.targetContext.getExternalFilesDir(null)?.resolve(fileName)
        Assert.assertNotNull(outputFile)

        // TODO: Capture the screen to outputFile using your preferred mechanism.
        Assert.assertTrue("Screenshot target may not be ready", true)
    }
}
"""
        return template.replace("{package_name}", package_name)

    def _java_test_template(self, package_name: str) -> str:
        template = """package {package_name};

import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.uiautomator.By;
import androidx.test.uiautomator.UiDevice;
import androidx.test.uiautomator.Until;
import org.junit.Assert;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class PlayPulseScreenshotTest {
    private UiDevice device;

    @Before
    public void setUp() {
        device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation());
        device.pressHome();
    }

    @Test
    public void captureSampleScreenshot() {
        String appPackage = "{package_name}";
        device.wait(Until.hasObject(By.pkg(appPackage).depth(0)), 10000);

        // TODO: Navigate to the target app screen before capturing a screenshot.
        // Add a helper, Espresso action, or UI Automator flow here.

        String fileName = "playpulse_screenshot_sample.png";
        Assert.assertTrue("Screenshot target may not be ready", true);
    }
}
"""
        return template.replace("{package_name}", package_name)

    def _test_config_template(self, package_name: str) -> str:
        template = """package {full_package}

object PlayPulseTestConfig {
    const val PACKAGE_NAME = "{package}"
    // Primary output root on device
    const val OUTPUT_ROOT = "/sdcard/Download/PlayPulseScreenshots"

    // Default locales to iterate when capturing screenshots. Edit as needed.
    val DEFAULT_LOCALES = arrayOf("en-US")

    // Default screenshot names to capture per locale.
    val DEFAULT_SCREENSHOT_NAMES = arrayOf("home", "details")

    // Wait time after sending locale change (ms)
    const val WAIT_AFTER_LOCALE_CHANGE_MS = 1500L
}
"""
        return template.replace("{full_package}", f"{package_name}.playpulse").replace("{package}", package_name)

    def _screenshot_helper_template(self, package_name: str) -> str:
        template = """package {full_package}

import android.app.Instrumentation
import android.graphics.Bitmap
import android.util.Log
import java.io.File
import java.io.FileOutputStream

object PlayPulseScreenshotHelper {
    private const val TAG = "PlayPulseScreenshotHelper"

    /**
     * Capture a screenshot and save it to device storage.
     * Tries primary external path first, then falls back to app external files dir.
     * Throws AssertionError on failure.
     */
    fun takeScreenshot(instrumentation: Instrumentation, packageName: String, locale: String, screenshotName: String): String {
        val primary = PlayPulseTestConfig.OUTPUT_ROOT + "/" + packageName + "/" + locale
        val fallbackBase = instrumentation.targetContext.getExternalFilesDir(null)
        val fallback = fallbackBase?.let { File(it, "PlayPulseScreenshots/$locale").absolutePath }

        val candidates = listOfNotNull(primary, fallback)
        var lastError: Exception? = null

        for (candidate in candidates) {
            try {
                val dir = File(candidate)
                if (!dir.exists()) dir.mkdirs()
                val file = File(dir, "$screenshotName.png")

                val uiAutomation = instrumentation.uiAutomation
                val bitmap: Bitmap? = uiAutomation.takeScreenshot()
                if (bitmap == null) throw AssertionError("Failed to capture screenshot bitmap")

                FileOutputStream(file).use { out ->
                    if (!bitmap.compress(Bitmap.CompressFormat.PNG, 100, out)) {
                        throw AssertionError("Failed to compress and write PNG file")
                    }
                }

                if (!file.exists() || file.length() == 0L) {
                    throw AssertionError("Screenshot file was not saved correctly: ${'$'}{file.absolutePath}")
                }

                Log.i(TAG, "Screenshot saved: ${'$'}{file.absolutePath} (size=${'$'}{file.length()} bytes)")
                return file.absolutePath
            } catch (e: Exception) {
                Log.w(TAG, "Failed to save screenshot to candidate path $candidate: ${'$'}{e.message}")
                lastError = e
            }
        }

        throw AssertionError("Failed to save screenshot for '$screenshotName' in locales $locale: ${'$'}{lastError?.message}")
    }
}
"""
        return template.replace("{full_package}", f"{package_name}.playpulse")

    def _locale_helper_template(self, package_name: str) -> str:
        template = """package {full_package}

import android.app.Instrumentation
import android.content.Intent
import android.util.Log

object PlayPulseLocaleHelper {
    private const val TAG = "PlayPulseLocaleHelper"

    /**
     * Default locale switching requires the app to implement a broadcast receiver or deep link.
     * If the app does not implement it, screenshots will be captured in the current app language.
     */
    fun setAppLocale(instrumentation: Instrumentation, packageName: String, localeTag: String): Boolean {
        val action = "${package_name}.PLAYPULSE_SET_LOCALE"
        return try {
            val intent = Intent(action)
            intent.setPackage(packageName)
            intent.putExtra("locale", localeTag)
            instrumentation.targetContext.sendBroadcast(intent)
            Thread.sleep(PlayPulseTestConfig.WAIT_AFTER_LOCALE_CHANGE_MS)
            Log.i(TAG, "Locale command sent: action=$action locale=$localeTag")
            true
        } catch (e: Exception) {
            Log.w(TAG, "Locale switch failed: ${'$'}{e.message}")
            false
        }
    }
}
"""
        return template.replace("{full_package}", f"{package_name}.playpulse")

    def _kotlin_playpulse_test_template(self, package_name: str) -> str:
        template = """package {full_package}

import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import androidx.test.uiautomator.By
import org.junit.Assert
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

@RunWith(AndroidJUnit4::class)
class PlayPulseScreenshotTest {
    private lateinit var device: UiDevice
    private val TAG = "PlayPulseScreenshotTest"

    @Before
    fun setUp() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        device = UiDevice.getInstance(instrumentation)
        device.pressHome()
    }

    private fun launchApp(instrumentation: androidx.test.platform.app.Instrumentation, pkg: String) {
        Log.i(TAG, "Launching app: $pkg")
        val launchIntent = instrumentation.targetContext.packageManager.getLaunchIntentForPackage(pkg)
        if (launchIntent != null) {
            launchIntent.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK)
            instrumentation.targetContext.startActivity(launchIntent)
        } else {
            Log.w(TAG, "Launch intent not found for package: $pkg")
        }
    }

    private fun waitForApp(pkg: String, timeoutMs: Long = 10_000L) {
        device.wait(Until.hasObject(By.pkg(pkg).depth(0)), timeoutMs)
    }

    @Test
    fun capturePlayPulseScreenshots() {
        Log.i(TAG, "Starting PlayPulse screenshot test")
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val pkg = PlayPulseTestConfig.PACKAGE_NAME

        for (locale in PlayPulseTestConfig.DEFAULT_LOCALES) {
            Log.i(TAG, "Locale started: $locale")
            val switched = PlayPulseLocaleHelper.setAppLocale(instrumentation, pkg, locale)
            if (!switched) {
                Log.w(TAG, "Locale switch was not successful for $locale. Screenshots will be captured in the current app language.")
            } else {
                Log.i(TAG, "Locale command sent for $locale")
            }

            launchApp(instrumentation, pkg)
            Log.i(TAG, "App launched: $pkg")
            waitForApp(pkg)

            for (screenshotName in PlayPulseTestConfig.DEFAULT_SCREENSHOT_NAMES) {
                Log.i(TAG, "Capturing screenshot: $screenshotName (locale=$locale)")
                val outPath = PlayPulseScreenshotHelper.takeScreenshot(instrumentation, pkg, locale, screenshotName)
                Log.i(TAG, "Screenshot saved: $outPath")
                val f = File(outPath)
                Assert.assertTrue("Screenshot file should exist: $outPath", f.exists())
                Assert.assertTrue("Screenshot file should not be empty: $outPath", f.length() > 0)
            }

        }
    }
}
"""
        return template.replace("{full_package}", f"{package_name}.playpulse")
