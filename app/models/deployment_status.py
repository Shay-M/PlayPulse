from dataclasses import dataclass, field
from typing import List


@dataclass
class DeploymentStatus:
    project_scanned: bool = False
    locales_selected: bool = False
    metadata_generated: bool = False
    screenshots_captured: bool = False
    fastlane_folder_exists: bool = False
    service_account_configured: bool = False
    last_upload_status: str = "Idle"
    checklist: List[str] = field(default_factory=list)
