from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class InternalFlowStep:
    type: str
    name: str = ""
    seconds: float = 1.0
    x: int = 0
    y: int = 0
    start_x: int = 0
    start_y: int = 0
    end_x: int = 0
    end_y: int = 0
    duration_ms: int = 300
    text: str = ""
    extra_key: str = "locale"
    extra_value: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InternalFlowStep":
        return cls(
            type=str(data.get("type", "wait")),
            name=str(data.get("name", "")),
            seconds=float(data.get("seconds", 1.0)),
            x=int(data.get("x", 0)),
            y=int(data.get("y", 0)),
            start_x=int(data.get("start_x", 0)),
            start_y=int(data.get("start_y", 0)),
            end_x=int(data.get("end_x", 0)),
            end_y=int(data.get("end_y", 0)),
            duration_ms=int(data.get("duration_ms", 300)),
            text=str(data.get("text", "")),
            extra_key=str(data.get("extra_key", "locale")) or "locale",
            extra_value=str(data.get("extra_value", "")),
        )

    def to_dict(self) -> Dict[str, Any]:
        if self.type == "launch_app":
            return {"type": self.type}
        if self.type == "wait":
            return {"type": self.type, "seconds": self.seconds}
        if self.type == "tap_coordinates":
            return {"type": self.type, "x": self.x, "y": self.y}
        if self.type in {"tap_text", "tap_content_desc", "tap_resource_id"}:
            return {"type": self.type, "text": self.text}
        if self.type == "swipe":
            return {
                "type": self.type,
                "start_x": self.start_x,
                "start_y": self.start_y,
                "end_x": self.end_x,
                "end_y": self.end_y,
                "duration_ms": self.duration_ms,
            }
        if self.type == "press_back":
            return {"type": self.type}
        if self.type == "enter_text":
            return {"type": self.type, "text": self.text}
        if self.type == "take_screenshot":
            return {"type": self.type, "name": self.name or "screen"}
        if self.type == "run_deep_link":
            return {"type": self.type, "text": self.text}
        if self.type == "run_broadcast":
            return {
                "type": self.type,
                "name": self.name,
                "extra_key": self.extra_key,
                "extra_value": self.extra_value,
            }
        if self.type in {"open_locale_settings", "go_home", "force_stop_app"}:
            return {"type": self.type, "name": self.name}
        return {"type": self.type}


@dataclass
class InternalFlow:
    name: str
    description: str
    enabled: bool = True
    target_type: str = "in_app_screen"
    steps: List[InternalFlowStep] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InternalFlow":
        steps = [
            InternalFlowStep.from_dict(step_data)
            for step_data in data.get("steps", [])
            if isinstance(step_data, dict)
        ]
        return cls(
            name=str(data.get("name", "Untitled flow")),
            description=str(data.get("description", "")),
            enabled=bool(data.get("enabled", True)),
            target_type=str(data.get("target_type", "in_app_screen")),
            steps=steps,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "enabled": self.enabled,
            "target_type": self.target_type,
            "steps": [step.to_dict() for step in self.steps],
        }
