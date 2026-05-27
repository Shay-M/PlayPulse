from dataclasses import dataclass


@dataclass
class DeviceInfo:
    identifier: str
    description: str
    status: str = "Ready"
