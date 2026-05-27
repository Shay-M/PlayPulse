from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable, Dict, List

from app.models.locale_info import LocaleInfo


class ProjectScanner:
    def scan_project(
        self,
        project_path: str,
        progress_callback: Callable[[object], None] | None = None,
    ) -> Dict[str, object]:
        root = Path(project_path).expanduser()
        normalized_path = str(root).replace("\\", "/")

        self._emit(progress_callback, "Checking selected folder")
        if not root.exists():
            if "app/src/main/res" in normalized_path:
                return self._mock_android_like_result(
                    "The selected path was not found, but it looks like an Android resource path. "
                    "Mock project data was loaded so the workflow remains usable."
                )
            return self._empty_result(
                "Selected folder does not exist. You can still add target locales manually."
            )

        self._emit(progress_callback, "Scanning Gradle files")
        gradle_files = self._find_gradle_files(root)

        self._emit(progress_callback, "Locating AndroidManifest.xml")
        manifest_path = self._find_manifest(root)
        package_name = self._read_package_name(manifest_path, gradle_files, root)

        self._emit(progress_callback, "Detecting Android resource locales")
        res_roots = self._find_res_roots(root)
        detected_locales = self._detect_locales(root, res_roots)

        android_like = bool(res_roots or manifest_path or gradle_files)
        complete_structure = bool(res_roots and manifest_path and gradle_files)

        if android_like and not detected_locales:
            detected_locales = self._mock_locales("Mocked from Android-like structure")

        if android_like:
            messages = [
                "Android project signals found.",
                f"Gradle files detected: {len(gradle_files)}",
                f"Resource roots detected: {len(res_roots)}",
                f"Locales detected: {len(detected_locales)}",
            ]
            if not complete_structure:
                messages.append(
                    "Some expected Android files were not found, but the workflow can continue."
                )
            return {
                "valid": complete_structure,
                "package_name": package_name,
                "project_type": "Android Gradle Project" if gradle_files else "Android-like Project",
                "gradle_files": [self._relative(root, file_path) for file_path in gradle_files],
                "manifest": self._relative(root, manifest_path) if manifest_path else "Not found",
                "locales": detected_locales,
                "validation_message": "\n".join(messages),
            }

        return self._empty_result(
            "Selected folder does not appear to contain an Android project structure. "
            "You can continue by adding target locales manually."
        )

    def _find_gradle_files(self, root: Path) -> List[Path]:
        candidates: List[Path] = []
        direct_names = [
            "settings.gradle",
            "settings.gradle.kts",
            "build.gradle",
            "build.gradle.kts",
            "app/build.gradle",
            "app/build.gradle.kts",
        ]
        for name in direct_names:
            path = root / name
            if path.exists():
                candidates.append(path)

        for path in root.rglob("*.gradle*"):
            if path.is_file() and path not in candidates:
                candidates.append(path)

        return sorted(candidates, key=lambda item: self._relative(root, item))

    def _find_manifest(self, root: Path) -> Path | None:
        preferred = root / "app" / "src" / "main" / "AndroidManifest.xml"
        if preferred.exists():
            return preferred

        manifests = sorted(root.rglob("AndroidManifest.xml"))
        return manifests[0] if manifests else None

    def _find_res_roots(self, root: Path) -> List[Path]:
        roots: List[Path] = []

        if root.name == "res" and root.parent.name == "main":
            roots.append(root)

        preferred = root / "app" / "src" / "main" / "res"
        if preferred.exists() and preferred not in roots:
            roots.append(preferred)

        for path in root.rglob("res"):
            if not path.is_dir() or path in roots:
                continue
            if path.parent.name == "main" and path.parent.parent.name == "src":
                roots.append(path)

        return sorted(roots, key=lambda item: self._relative(root, item))

    def _detect_locales(self, root: Path, res_roots: List[Path]) -> List[LocaleInfo]:
        locales_by_code: Dict[str, LocaleInfo] = {}
        for res_root in res_roots:
            for child in sorted(res_root.iterdir()):
                if not child.is_dir():
                    continue
                locale = self._locale_from_values_folder(root, child)
                if not locale:
                    continue
                if locale.code not in locales_by_code:
                    locales_by_code[locale.code] = locale

        preferred_order = ["en-US", "he-IL", "fr-FR", "es-ES", "de-DE", "pt-BR", "zh-CN"]
        return sorted(
            locales_by_code.values(),
            key=lambda item: (
                preferred_order.index(item.code)
                if item.code in preferred_order
                else len(preferred_order),
                item.code,
            ),
        )

    def _locale_from_values_folder(self, root: Path, folder: Path) -> LocaleInfo | None:
        name = folder.name
        if name == "values":
            return LocaleInfo("en-US", self._relative(root, folder), "English (US)", "Default resources")

        if not name.startswith("values-"):
            return None

        qualifiers = name.removeprefix("values-").split("-")
        language = qualifiers[0].lower()
        if not re.fullmatch(r"[a-z]{2,3}", language):
            return None

        legacy_language_map = {"iw": "he", "in": "id", "ji": "yi"}
        language = legacy_language_map.get(language, language)

        region = ""
        for qualifier in qualifiers[1:]:
            if qualifier.startswith("r") and len(qualifier) >= 3:
                region = qualifier[1:].upper()
                break

        default_regions = {
            "en": "US",
            "he": "IL",
            "fr": "FR",
            "es": "ES",
            "de": "DE",
            "pt": "PT",
            "zh": "CN",
            "id": "ID",
            "yi": "001",
        }
        region = region or default_regions.get(language, language.upper())
        code = f"{language}-{region}"
        status = "Detected"
        if qualifiers[0].lower() == "iw":
            status = "Detected legacy iw"

        return LocaleInfo(code, self._relative(root, folder), self._display_name(code), status)

    def _read_package_name(self, manifest_path: Path | None, gradle_files: List[Path], root: Path) -> str:
        if manifest_path:
            try:
                manifest = ET.parse(manifest_path)
                package_name = manifest.getroot().attrib.get("package", "")
                if package_name:
                    return package_name
            except ET.ParseError:
                manifest_path = None

        patterns = [
            re.compile(r"namespace\s*[= ]\s*[\"']([^\"']+)[\"']"),
            re.compile(r"applicationId\s*[= ]\s*[\"']([^\"']+)[\"']"),
        ]
        for gradle_file in gradle_files:
            try:
                text = gradle_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for pattern in patterns:
                match = pattern.search(text)
                if match:
                    return match.group(1)

        if gradle_files:
            return f"com.example.{root.name.lower().replace(' ', '')}"
        return ""

    def _mock_android_like_result(self, validation_message: str) -> Dict[str, object]:
        return {
            "valid": False,
            "package_name": "com.example.androidapp",
            "project_type": "Android Gradle Project (mocked)",
            "gradle_files": ["app/build.gradle", "build.gradle", "settings.gradle"],
            "manifest": "app/src/main/AndroidManifest.xml",
            "locales": self._mock_locales("Mocked"),
            "validation_message": validation_message,
        }

    def _empty_result(self, validation_message: str) -> Dict[str, object]:
        return {
            "valid": False,
            "package_name": "",
            "project_type": "Unknown",
            "gradle_files": [],
            "manifest": "Not found",
            "locales": [],
            "validation_message": validation_message,
        }

    def _mock_locales(self, status: str) -> List[LocaleInfo]:
        return [
            LocaleInfo("en-US", "app/src/main/res/values", "English (US)", status),
            LocaleInfo("he-IL", "app/src/main/res/values-he", "Hebrew (Israel)", status),
            LocaleInfo("fr-FR", "app/src/main/res/values-fr", "French (France)", status),
            LocaleInfo("es-ES", "app/src/main/res/values-es", "Spanish (Spain)", status),
        ]

    def _display_name(self, code: str) -> str:
        names = {
            "en-US": "English (US)",
            "he-IL": "Hebrew (Israel)",
            "fr-FR": "French (France)",
            "es-ES": "Spanish (Spain)",
            "de-DE": "German (Germany)",
            "pt-BR": "Portuguese (Brazil)",
            "pt-PT": "Portuguese (Portugal)",
            "zh-CN": "Chinese (Simplified)",
            "id-ID": "Indonesian",
            "yi-001": "Yiddish",
        }
        return names.get(code, code)

    def _relative(self, root: Path, path: Path) -> str:
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            return path.as_posix()

    def _emit(self, progress_callback: Callable[[object], None] | None, message: str) -> None:
        if progress_callback:
            progress_callback(message)
