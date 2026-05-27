from dataclasses import dataclass


@dataclass
class ScreenshotFlow:
    enabled: bool
    name: str
    description: str
    expected_name: str
    status: str = "Pending"
    automation_path: str = ""
    automation_type: str = "Manual"
