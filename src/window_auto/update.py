"""Pure logic for checking GitHub releases for a newer LN-auto version."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


RELEASE_API_URL = (
    "https://api.github.com/repos/LinLey-Nancy/LN-auto/releases/latest"
)
RELEASES_PAGE_URL = "https://github.com/LinLey-Nancy/LN-auto/releases"

_VERSION_PATTERN = re.compile(r"^v?(\d+(?:\.\d+)*)$")


class UpdateCheckError(RuntimeError):
    """Raised when release information cannot be interpreted."""


@dataclass(frozen=True, slots=True)
class ReleaseAsset:
    name: str
    download_url: str
    size: int = 0


@dataclass(frozen=True, slots=True)
class ReleaseInfo:
    version: str
    name: str
    notes: str
    html_url: str
    published_at: str
    asset: ReleaseAsset | None


def parse_version(text: str) -> tuple[int, ...]:
    """Parse versions like "v0.1.2" or "0.2" into comparable integer tuples."""
    match = _VERSION_PATTERN.match(text.strip())
    if match is None:
        raise UpdateCheckError(f"无法解析版本号：{text!r}")
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer(latest: str, current: str) -> bool:
    newest = parse_version(latest)
    present = parse_version(current)
    length = max(len(newest), len(present))
    newest += (0,) * (length - len(newest))
    present += (0,) * (length - len(present))
    return newest > present


def select_installer_asset(assets: list[dict[str, Any]]) -> ReleaseAsset | None:
    """Pick the Windows setup executable from a release's asset list."""
    candidates: list[ReleaseAsset] = []
    for raw in assets:
        if not isinstance(raw, dict):
            continue
        name = raw.get("name")
        url = raw.get("browser_download_url")
        if not isinstance(name, str) or not isinstance(url, str):
            continue
        if not name.lower().endswith(".exe"):
            continue
        candidates.append(
            ReleaseAsset(name=name, download_url=url, size=int(raw.get("size") or 0))
        )
    for asset in candidates:
        if "setup" in asset.name.lower():
            return asset
    return candidates[0] if candidates else None


def parse_release(payload: dict[str, Any]) -> ReleaseInfo:
    """Turn the GitHub "latest release" API payload into a ReleaseInfo."""
    if not isinstance(payload, dict):
        raise UpdateCheckError("Release 数据格式无效。")
    tag = payload.get("tag_name")
    if not isinstance(tag, str) or not tag.strip():
        raise UpdateCheckError("Release 数据缺少 tag_name。")
    version = tag.strip()
    parse_version(version)  # validate early so callers never compare garbage
    assets = payload.get("assets")
    return ReleaseInfo(
        version=version.lstrip("v"),
        name=str(payload.get("name") or version),
        notes=str(payload.get("body") or ""),
        html_url=str(payload.get("html_url") or RELEASES_PAGE_URL),
        published_at=str(payload.get("published_at") or ""),
        asset=select_installer_asset(assets if isinstance(assets, list) else []),
    )
