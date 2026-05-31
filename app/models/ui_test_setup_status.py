from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict


@dataclass
class UITestSetupStatus:
    # Basic project signals
    project_path: str = ""
    has_android_project: bool = False
    gradle_settings_found: bool = False
    root_gradle_found: bool = False
    gradle_dsl: str = ""  # 'groovy' or 'kotlin' or ''

    # App module
    app_module_path: str = ""
    app_gradle_file: str = ""

    # Package / namespace
    package_name: str = ""
    application_id: str = ""
    namespace: str = ""

    # androidTest sources
    android_test_source_exists: bool = False
    android_test_files: List[str] = field(default_factory=list)

    # Test runner and dependencies
    test_instrumentation_runner: str | None = None
    android_test_dependencies: List[str] = field(default_factory=list)
    missing_dependencies: List[str] = field(default_factory=list)

    # Language / frameworks
    kotlin_used: bool = False
    compose_used: bool = False

    # PlayPulse generated test files
    existing_playpulse_test_files: List[str] = field(default_factory=list)

    # Overall readiness
    ready_for_ui_test_screenshots: bool = False
    messages: List[str] = field(default_factory=list)


@dataclass
class UITestSetupRequirements:
    files_to_create: Dict[str, str] = field(default_factory=dict)  # path -> content
    gradle_changes: List[str] = field(default_factory=list)  # human-readable diffs/lines to add
    warnings: List[str] = field(default_factory=list)
    can_apply: bool = True
