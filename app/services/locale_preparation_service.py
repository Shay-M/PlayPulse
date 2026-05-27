from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.models.locale_preparation import LocalePreparationSettings


class LocalePreparationService:
    def __init__(self, project_path: str = "") -> None:
        self.project_path = project_path or Path.cwd().as_posix()

    def default_settings_path(self) -> str:
        root = Path(self.project_path).expanduser()
        return str(root / "playpulse_flows" / "locale_preparation.json")

    def save_settings(self, settings: LocalePreparationSettings, path: str | None = None) -> str:
        file_path = Path(path or self.default_settings_path()).expanduser()
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(json.dumps(settings.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return str(file_path)

    def load_settings(self, path: str | None = None) -> LocalePreparationSettings:
        file_path = Path(path or self.default_settings_path()).expanduser()
        if not file_path.exists():
            raise FileNotFoundError(f"Locale preparation file not found: {file_path}")
        data = json.loads(file_path.read_text(encoding="utf-8"))
        return LocalePreparationSettings.from_dict(data)
