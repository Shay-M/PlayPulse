from dataclasses import dataclass


@dataclass
class MetadataInfo:
    locale: str
    app_title: str
    short_description: str
    full_description: str
    status: str = "Draft"
