from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from app.services.ui_test_setup_analyzer import UITestSetupAnalyzer


@dataclass
class AppLocaleBridgePreview:
    package_name: str = ""
    app_module_path: str = "app"
    manifest_path: str = ""
    files_to_create: Dict[str, str] = field(default_factory=dict)
    manifest_receiver_snippet: str = ""
    main_activity_snippet: str = ""
    warnings: List[str] = field(default_factory=list)
    can_apply: bool = False


class AppLocaleBridgeGenerator:
    def __init__(self, project_path: str) -> None:
        self.project_path = Path(project_path).expanduser() if project_path else Path.cwd()

    def preview(self, supported_locales: List[str] | None = None) -> AppLocaleBridgePreview:
        analyzer = UITestSetupAnalyzer(str(self.project_path))
        status = analyzer.analyze()
        package_name = status.application_id or status.namespace or status.package_name
        app_module_path = status.app_module_path or "app"
        preview = AppLocaleBridgePreview(package_name=package_name, app_module_path=app_module_path)

        if not package_name:
            preview.warnings.append("Could not detect package name, namespace, or applicationId.")
            return preview

        manifest_path = self._find_manifest(app_module_path)
        if manifest_path:
            preview.manifest_path = str(manifest_path.relative_to(self.project_path).as_posix())
        else:
            preview.warnings.append("Could not find AndroidManifest.xml for the app module.")

        locales = self._clean_locales(supported_locales or [])
        if not locales:
            locales = ["en-US", "he-IL"]
            preview.warnings.append("No supported locales were passed. Generated bridge defaults to en-US and he-IL; update this list if needed.")

        bridge_package = f"{package_name}.playpulse"
        package_path = bridge_package.replace(".", "/")
        base_path = f"{app_module_path}/src/main/java/{package_path}"

        preview.files_to_create[f"{base_path}/PlayPulseLocaleBridge.kt"] = self._bridge_template(bridge_package, package_name, locales)
        preview.files_to_create[f"{base_path}/PlayPulseLocaleReceiver.kt"] = self._receiver_template(bridge_package, package_name)
        preview.files_to_create[f"{app_module_path}/PLAYPULSE_LOCALE_BRIDGE_INTEGRATION.md"] = self._integration_doc(package_name, bridge_package, locales)
        preview.manifest_receiver_snippet = self._receiver_manifest_snippet(bridge_package, package_name)
        preview.main_activity_snippet = self._activity_snippet(bridge_package)
        preview.can_apply = True
        return preview

    def apply(self, preview: AppLocaleBridgePreview, overwrite: bool = False, apply_manifest_receiver: bool = True) -> Dict[str, List[str]]:
        results: Dict[str, List[str]] = {"written": [], "skipped": [], "errors": [], "manifest": []}
        for relative_path, content in preview.files_to_create.items():
            path = self.project_path / relative_path
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists() and not overwrite:
                    results["skipped"].append(relative_path)
                    continue
                path.write_text(content, encoding="utf-8")
                results["written"].append(relative_path)
            except OSError as error:
                results["errors"].append(f"{relative_path}: {error}")

        if apply_manifest_receiver and preview.manifest_path:
            manifest_result = self._apply_manifest_receiver(preview)
            for key, values in manifest_result.items():
                results.setdefault(key, []).extend(values)
        return results

    def _find_manifest(self, app_module_path: str) -> Path | None:
        candidates = [
            self.project_path / app_module_path / "src" / "main" / "AndroidManifest.xml",
            self.project_path / "app" / "src" / "main" / "AndroidManifest.xml",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        manifests = sorted(self.project_path.rglob("src/main/AndroidManifest.xml"))
        return manifests[0] if manifests else None

    def _apply_manifest_receiver(self, preview: AppLocaleBridgePreview) -> Dict[str, List[str]]:
        results: Dict[str, List[str]] = {"manifest": [], "errors": []}
        manifest_path = self.project_path / preview.manifest_path
        try:
            text = manifest_path.read_text(encoding="utf-8")
        except OSError as error:
            results["errors"].append(f"Could not read manifest: {error}")
            return results

        receiver_class = f"{preview.package_name}.playpulse.PlayPulseLocaleReceiver"
        action = f"{preview.package_name}.PLAYPULSE_SET_LOCALE"
        if receiver_class in text or action in text:
            results["manifest"].append("Manifest already contains PlayPulse locale receiver.")
            return results

        if "</application>" not in text:
            results["errors"].append("Manifest has no </application> tag; receiver snippet was not inserted.")
            return results

        snippet = self._receiver_manifest_snippet(f"{preview.package_name}.playpulse", preview.package_name)
        backup_path = manifest_path.with_suffix(manifest_path.suffix + ".playpulse.bak")
        try:
            if not backup_path.exists():
                backup_path.write_text(text, encoding="utf-8")
            updated = text.replace("</application>", snippet + "\n    </application>", 1)
            manifest_path.write_text(updated, encoding="utf-8")
            results["manifest"].append(f"Inserted receiver into {preview.manifest_path}")
            results["manifest"].append(f"Backup: {backup_path.name}")
        except OSError as error:
            results["errors"].append(f"Could not update manifest: {error}")
        return results

    def _clean_locales(self, locales: List[str]) -> List[str]:
        seen: set[str] = set()
        cleaned: List[str] = []
        for locale in locales:
            value = str(locale or "").strip()
            if not value or value in seen:
                continue
            if not re.fullmatch(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*", value):
                continue
            seen.add(value)
            cleaned.append(value)
        return cleaned

    def _bridge_template(self, bridge_package: str, app_package: str, locales: List[str]) -> str:
        locale_set = ", ".join(f'"{locale}"' for locale in locales)
        action = f"{app_package}.PLAYPULSE_SET_LOCALE"
        return f'''package {bridge_package}

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.util.Log
import java.util.Locale

object PlayPulseLocaleBridge {{
    private const val TAG = "PlayPulseLocaleBridge"
    const val ACTION_SET_LOCALE = "{action}"
    const val EXTRA_LOCALE = "locale"
    private const val PREFS_NAME = "playpulse_locale_bridge"
    private const val PREF_SELECTED_LOCALE = "selected_locale"

    private val supportedLocales = setOf({locale_set})

    fun handleBroadcast(context: Context, intent: Intent?): Boolean {{
        if (intent?.action != ACTION_SET_LOCALE) {{
            return false
        }}
        val localeTag = intent.getStringExtra(EXTRA_LOCALE).orEmpty()
        return setAppLocale(context, localeTag)
    }}

    fun handleIntent(context: Context, intent: Intent?): Boolean {{
        val uri: Uri = intent?.data ?: return false
        if (uri.host != "playpulse" || uri.path != "/set-locale") {{
            return false
        }}
        val localeTag = uri.getQueryParameter(EXTRA_LOCALE).orEmpty()
        return setAppLocale(context, localeTag)
    }}

    fun setAppLocale(context: Context, localeTag: String): Boolean {{
        val normalized = normalizeLocale(localeTag)
        if (normalized.isEmpty()) {{
            Log.w(TAG, "Locale command ignored because locale is empty")
            return false
        }}
        if (supportedLocales.isNotEmpty() && !supportedLocales.contains(normalized)) {{
            Log.w(TAG, "Locale command ignored because $normalized is not supported")
            return false
        }}

        saveLocale(context, normalized)
        applyLocaleBestEffort(context, normalized)
        Log.i(TAG, "Locale command handled: $normalized")
        return true
    }}

    fun currentLocale(context: Context): String {{
        return context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .getString(PREF_SELECTED_LOCALE, "")
            .orEmpty()
    }}

    private fun saveLocale(context: Context, localeTag: String) {{
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putString(PREF_SELECTED_LOCALE, localeTag)
            .apply()
    }}

    private fun applyLocaleBestEffort(context: Context, localeTag: String) {{
        if (tryAppCompatLocale(localeTag)) {{
            return
        }}

        val locale = Locale.forLanguageTag(localeTag)
        Locale.setDefault(locale)
        val resources = context.resources
        val configuration = resources.configuration
        configuration.setLocale(locale)
        @Suppress("DEPRECATION")
        resources.updateConfiguration(configuration, resources.displayMetrics)
        Log.i(TAG, "Applied locale with Resources fallback. Connect currentLocale() to your app locale system for best results.")
    }}

    private fun tryAppCompatLocale(localeTag: String): Boolean {{
        return try {{
            val localeListCompatClass = Class.forName("androidx.core.os.LocaleListCompat")
            val forLanguageTags = localeListCompatClass.getMethod("forLanguageTags", String::class.java)
            val localeList = forLanguageTags.invoke(null, localeTag)
            val appCompatDelegateClass = Class.forName("androidx.appcompat.app.AppCompatDelegate")
            val setApplicationLocales = appCompatDelegateClass.getMethod("setApplicationLocales", localeListCompatClass)
            setApplicationLocales.invoke(null, localeList)
            Log.i(TAG, "Applied locale through AppCompatDelegate: $localeTag")
            true
        }} catch (error: Throwable) {{
            Log.i(TAG, "AppCompat locale API is unavailable; using fallback for $localeTag")
            false
        }}
    }}

    private fun normalizeLocale(localeTag: String): String {{
        return localeTag.trim().replace('_', '-')
    }}
}}
'''

    def _receiver_template(self, bridge_package: str, app_package: str) -> str:
        return f'''package {bridge_package}

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log

class PlayPulseLocaleReceiver : BroadcastReceiver() {{
    override fun onReceive(context: Context, intent: Intent?) {{
        val handled = PlayPulseLocaleBridge.handleBroadcast(context, intent)
        Log.i("PlayPulseLocaleReceiver", "Locale broadcast handled=$handled")
    }}
}}
'''

    def _receiver_manifest_snippet(self, bridge_package: str, app_package: str) -> str:
        receiver_class = f"{bridge_package}.PlayPulseLocaleReceiver"
        action = f"{app_package}.PLAYPULSE_SET_LOCALE"
        return f'''
        <!-- Added by PlayPulse for app locale screenshot automation. Remove for production builds if not needed. -->
        <receiver
            android:name="{receiver_class}"
            android:exported="true">
            <intent-filter>
                <action android:name="{action}" />
            </intent-filter>
        </receiver>'''

    def _activity_snippet(self, bridge_package: str) -> str:
        return f'''// Optional deep link integration for MainActivity.
// Call this in onCreate(intent) and onNewIntent(intent) if you use deep links.
{bridge_package}.PlayPulseLocaleBridge.handleIntent(this, intent)
'''

    def _integration_doc(self, app_package: str, bridge_package: str, locales: List[str]) -> str:
        locales_text = ", ".join(locales)
        return f'''# PlayPulse Locale Bridge Integration

This file was generated by PlayPulse.

Supported locales in the generated bridge: {locales_text}

## Broadcast command

PlayPulse can send:

```bash
adb shell am broadcast -a {app_package}.PLAYPULSE_SET_LOCALE --es locale en-US
```

The manifest receiver was generated for:

```text
{bridge_package}.PlayPulseLocaleReceiver
```

## Deep link option

If you prefer deep links, add an intent-filter to your Activity and call:

```kotlin
{bridge_package}.PlayPulseLocaleBridge.handleIntent(this, intent)
```

from `onCreate` and `onNewIntent`.

## App integration note

The generated bridge applies AppCompat locale by reflection when available, then falls back to saving the locale and updating Resources.
For a production-quality app, connect `PlayPulseLocaleBridge.currentLocale(context)` to your app's existing locale system.
'''
