from __future__ import annotations

from enum import Enum


class ScreenshotStrategy(str, Enum):
    APP_DEBUG_ADB = "app_debug_adb"
    UI_TEST = "ui_test"
    MANUAL_ADB = "manual_adb"
    INTERNAL_ADB_FLOW = "internal_adb_flow"
    WIDGET_LANGUAGE = "widget_language"
    MAESTRO = "maestro"

    @classmethod
    def default(cls) -> "ScreenshotStrategy":
        return cls.APP_DEBUG_ADB
