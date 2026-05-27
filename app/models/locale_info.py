from dataclasses import dataclass


@dataclass
class LocaleInfo:
    code: str
    source_folder: str
    display_name: str
    status: str = "Detected"
