"""Mutable workflow document used by the desktop editor."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from window_auto.workflow.loader import load_workflow_v2


STEP_DEFAULTS: dict[str, dict[str, Any]] = {
    "template_match": {
        "template": "assets/resource/image/template.png",
        "threshold": 0.8,
        "attempts": 3,
        "interval_ms": 500,
        "result_variable": "match",
        "post_action": "none",
        "post_button": "left",
        "post_action_interval_ms": 100,
        "post_key": "ENTER",
        "post_modifiers": [],
        "post_key_hold_ms": 50,
    },
    "mouse_move": {
        "move_mode": "absolute",
        "x": 0,
        "y": 0,
        "delta_x": 0,
        "delta_y": 0,
    },
    "mouse_click": {
        "x": 0,
        "y": 0,
        "button": "left",
        "count": 1,
        "interval_ms": 100,
    },
    "key_press": {
        "key": "ENTER",
        "modifiers": [],
        "hold_ms": 50,
    },
    "text_input": {
        "text": "",
        "strategy": "key_sequence",
        "interval_ms": 80,
        "sensitive": False,
    },
    "wait": {
        "delay_mode": "fixed",
        "duration_ms": 500,
        "min_duration_ms": 300,
        "max_duration_ms": 800,
    },
}

STEP_LABELS = {
    "template_match": "模板识别",
    "mouse_move": "鼠标移动",
    "mouse_click": "鼠标点击",
    "key_press": "键盘按键",
    "text_input": "文本输入",
    "wait": "延迟",
}

AUTO_DELAY_DEFAULTS: dict[str, Any] = {
    "mode": "none",
    "fixed_ms": 500,
    "min_ms": 300,
    "max_ms": 800,
}
AUTO_DELAY_MODES = ("none", "fixed", "random")


class WorkflowDocument:
    def __init__(self, data: dict[str, Any] | None = None, path: Path | None = None) -> None:
        self.data = data or self._new_data()
        self.path = path
        self.dirty = False

    @staticmethod
    def _new_data() -> dict[str, Any]:
        return {
            "version": 2,
            "name": "未命名工作流",
            "target": {"title_pattern": "", "class_name": None},
            "settings": {
                "stop_on_error": True,
                "default_timeout_ms": 10_000,
                "auto_delay": dict(AUTO_DELAY_DEFAULTS),
            },
            "steps": [],
        }

    @classmethod
    def load(cls, path: Path, project_root: Path) -> WorkflowDocument:
        load_workflow_v2(path, project_root)
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return cls(data=data, path=path.resolve())

    @property
    def name(self) -> str:
        return str(self.data.get("name", "未命名工作流"))

    @property
    def steps(self) -> list[dict[str, Any]]:
        return self.data["steps"]

    @property
    def auto_delay(self) -> dict[str, Any]:
        settings = self.data.setdefault("settings", {})
        delay = settings.setdefault("auto_delay", dict(AUTO_DELAY_DEFAULTS))
        for key, value in AUTO_DELAY_DEFAULTS.items():
            delay.setdefault(key, value)
        return delay

    def set_auto_delay(
        self,
        mode: str,
        *,
        fixed_ms: int,
        min_ms: int,
        max_ms: int,
    ) -> None:
        if mode not in AUTO_DELAY_MODES:
            raise ValueError(f"未知的自动延迟模式：{mode}")
        if int(min_ms) > int(max_ms):
            raise ValueError("最短延迟不能大于最长延迟。")
        self.data.setdefault("settings", {})["auto_delay"] = {
            "mode": mode,
            "fixed_ms": int(fixed_ms),
            "min_ms": int(min_ms),
            "max_ms": int(max_ms),
        }
        self.dirty = True

    def set_name(self, name: str) -> None:
        name = name.strip()
        if name and name != self.name:
            self.data["name"] = name
            self.dirty = True

    def set_target(self, title: str, class_name: str | None) -> None:
        self.data["target"] = {
            "title_pattern": title,
            "class_name": class_name or None,
        }
        self.dirty = True

    def add_step(self, step_type: str) -> int:
        return self.insert_step(step_type, len(self.steps))

    def insert_step(self, step_type: str, position: int) -> int:
        if step_type not in STEP_DEFAULTS:
            raise ValueError(f"Unsupported step type: {step_type}")
        position = min(max(position, 0), len(self.steps))
        existing = {str(step.get("id", "")) for step in self.steps}
        base_id = step_type.replace("_", "-")
        sequence = 1
        step_id = f"{base_id}-{sequence}"
        while step_id in existing:
            sequence += 1
            step_id = f"{base_id}-{sequence}"
        step = {
            "id": step_id,
            "type": step_type,
            "name": STEP_LABELS[step_type],
            "enabled": True,
            "on_failure": "stop",
            **deepcopy(STEP_DEFAULTS[step_type]),
        }
        self.steps.insert(position, step)
        self.dirty = True
        return position

    def remove_step(self, index: int) -> None:
        del self.steps[index]
        self.dirty = True

    def move_step(self, index: int, offset: int) -> int:
        destination = index + offset
        if not 0 <= destination < len(self.steps):
            return index
        self.steps[index], self.steps[destination] = (
            self.steps[destination],
            self.steps[index],
        )
        self.dirty = True
        return destination

    def update_step(self, index: int, field: str, value: Any) -> None:
        step = self.steps[index]
        if field == "id":
            value = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value)).strip("-")
            if not value:
                raise ValueError("步骤 ID 不能为空。")
            if any(
                step_index != index and step.get("id") == value
                for step_index, step in enumerate(self.steps)
            ):
                raise ValueError(f"步骤 ID 已存在：{value}")
        if step.get("type") == "wait":
            if (
                field == "min_duration_ms"
                and int(value) > int(step.get("max_duration_ms", value))
            ):
                raise ValueError("最短延迟不能大于最长延迟。")
            if (
                field == "max_duration_ms"
                and int(value) < int(step.get("min_duration_ms", value))
            ):
                raise ValueError("最长延迟不能小于最短延迟。")
        step[field] = value
        self.dirty = True

    def save(self, path: Path | None = None, project_root: Path | None = None) -> Path:
        output = (path or self.path)
        if output is None:
            raise ValueError("Workflow path has not been selected.")
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self.data, ensure_ascii=False, indent=2) + "\n"
        if project_root is not None:
            # Validate with the strict v2 loader before touching the target file,
            # so the editor can never save a workflow it cannot reopen.
            fd, temp_name = tempfile.mkstemp(
                dir=output.parent, prefix=output.stem + "-", suffix=".json"
            )
            temp_path = Path(temp_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(text)
                load_workflow_v2(temp_path, project_root)
                os.replace(temp_path, output)
            except Exception:
                temp_path.unlink(missing_ok=True)
                raise
        else:
            output.write_text(text, encoding="utf-8")
        self.path = output
        self.dirty = False
        return output
