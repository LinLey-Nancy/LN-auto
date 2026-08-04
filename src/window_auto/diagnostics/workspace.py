"""Create and address the ignored runtime debug workspace."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DebugWorkspace:
    root: Path

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def screenshots(self) -> Path:
        return self.root / "screenshots"

    @property
    def reports(self) -> Path:
        return self.root / "reports"

    def ensure(self) -> None:
        for path in (self.logs, self.screenshots, self.reports):
            path.mkdir(parents=True, exist_ok=True)

    def timestamped_path(self, directory: Path, prefix: str, suffix: str) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        return directory / f"{prefix}-{timestamp}{suffix}"


def create_debug_workspace(project_root: Path, debug_dir: str) -> DebugWorkspace:
    root = Path(debug_dir)
    if not root.is_absolute():
        root = project_root / root
    workspace = DebugWorkspace(root.resolve())
    workspace.ensure()
    return workspace


def configure_file_logging(workspace: DebugWorkspace) -> Path:
    log_path = workspace.timestamped_path(workspace.logs, "run", ".log")
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root_logger.addHandler(handler)
    return log_path
