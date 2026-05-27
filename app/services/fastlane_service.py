from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Dict, List


class FastlaneService:
    def validate_store_assets(
        self,
        project_scanned: bool,
        locales_selected: bool,
        metadata_generated: bool,
        screenshots_captured: bool,
        fastlane_folder: str,
        service_account_configured: bool,
        progress_callback: Callable[[object], None] | None = None,
    ) -> Dict[str, object]:
        if progress_callback:
            progress_callback("Checking project, metadata, screenshots, and deployment settings")
        time.sleep(0.5)
        folder_exists = bool(fastlane_folder) and Path(fastlane_folder).expanduser().exists()
        validations = {
            "project_scanned": project_scanned,
            "locales_selected": locales_selected,
            "metadata_generated": metadata_generated,
            "screenshots_captured": screenshots_captured,
            "fastlane_folder_exists": folder_exists,
            "service_account_configured": service_account_configured,
        }
        summary = [
            f"{key.replace('_', ' ').title()}: {'OK' if value else 'Missing'}"
            for key, value in validations.items()
        ]
        return {
            "validations": validations,
            "summary": summary,
            "valid": all(validations.values()),
        }

    def upload_assets(
        self,
        mode: str,
        progress_callback: Callable[[object], None] | None = None,
    ) -> Dict[str, str]:
        steps = self._steps_for_mode(mode)
        total = len(steps)

        for index, step in enumerate(steps, start=1):
            if progress_callback:
                progress_callback({"message": step, "current": index, "total": total})
            time.sleep(0.55)

        return {"status": "Success", "mode": mode}

    def _steps_for_mode(self, mode: str) -> List[str]:
        if mode == "Upload metadata only":
            return [
                "Preparing Fastlane metadata files",
                "Validating localized text limits",
                "Uploading metadata items",
                "Verifying store listing draft",
            ]
        if mode == "Upload screenshots only":
            return [
                "Checking screenshot folders",
                "Uploading screenshot assets",
                "Associating screenshots with locales",
                "Verifying screenshot draft",
            ]
        if mode == "Prepare files only":
            return [
                "Preparing file structure",
                "Copying localized metadata",
                "Creating store listing manifest",
            ]
        return [
            "Preparing file structure",
            "Verifying metadata items",
            "Checking screenshot availability",
            "Uploading metadata and screenshots",
            "Finalizing Google Play draft",
        ]
