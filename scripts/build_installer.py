"""Build the LN-auto desktop installer.

Steps:
  1. Read the version from pyproject.toml (single source of truth).
  2. Build the GUI app with PyInstaller into build/pyinstaller/dist/LN-auto/.
  3. Compile an Inno Setup installer into dist/LN-auto-v<version>-Setup.exe.

Usage:
  .venv/Scripts/python.exe scripts/build_installer.py
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
BUILD_DIR = ROOT / "build" / "pyinstaller"
APP_NAME = "LN-auto"
# Stable AppId: upgrades reuse the same installation instead of duplicating.
# The value is pre-escaped for Inno Setup: "{{" renders a literal "{", so the
# expanded line reads AppId={{GUID} which the constant parser accepts.
INNO_APP_ID = "{{7A2C9E41-3F5B-4A8C-9D2E-1B6F8C4A5E7D}"

ISCC_CANDIDATES = (
    r"D:\Tools\InnoSetup6\ISCC.exe",
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
)

INNO_TEMPLATE = """\
#define AppName "{app_name}"
#define AppVersion "{version}"
#define VersionInfo "{version_info}"
#define AppId "{app_id}"
#define AppDir "{app_dir}"
#define OutDir "{out_dir}"

[Setup]
AppId={{#AppId}}
AppName={{#AppName}}
AppVersion={{#AppVersion}}
AppVerName={{#AppName}} {{#AppVersion}}
VersionInfoVersion={{#VersionInfo}}
AppPublisher=LN-auto contributors
DefaultDirName={{localappdata}}\\Programs\\{app_name}
DefaultGroupName={app_name}
PrivilegesRequired=lowest
OutputDir={{#OutDir}}
OutputBaseFilename={app_name}-v{{#AppVersion}}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
UninstallDisplayIcon={{app}}\\{app_name}.exe

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"; Flags: unchecked

[Files]
Source: "{{#AppDir}}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{{autoprograms}}\\{app_name}"; Filename: "{{app}}\\{app_name}.exe"
Name: "{{autodesktop}}\\{app_name}"; Filename: "{{app}}\\{app_name}.exe"; Tasks: desktopicon

[Run]
Filename: "{{app}}\\{app_name}.exe"; Description: "启动 {app_name}"; Flags: nowait postinstall skipifsilent
"""


def read_version() -> str:
    with PYPROJECT.open("rb") as handle:
        data = tomllib.load(handle)
    version = data["project"]["version"]
    if not isinstance(version, str) or not version.strip():
        raise SystemExit("pyproject.toml: project.version is missing or invalid.")
    return version.strip()


def venv_python() -> Path:
    candidate = ROOT / ".venv" / "Scripts" / "python.exe"
    return candidate if candidate.is_file() else Path(sys.executable)


def ensure_pyinstaller(python: Path) -> None:
    probe = subprocess.run(
        [str(python), "-c", "import PyInstaller"],
        cwd=ROOT,
        capture_output=True,
    )
    if probe.returncode == 0:
        return
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit(
            "PyInstaller is not installed. Run: uv pip install --python "
            f"{python} -e \".[packaging]\""
        )
    print("Installing PyInstaller into the project environment ...")
    subprocess.run(
        [uv, "pip", "install", "--python", str(python), "-e", ".[packaging]"],
        cwd=ROOT,
        check=True,
    )


def run_pyinstaller(python: Path) -> Path:
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    app_dir = BUILD_DIR / "dist" / APP_NAME
    command = [
        str(python),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        "--name",
        APP_NAME,
        "--collect-all",
        "maa",
        "--add-data",
        f"{ROOT / 'assets'};assets",
        "--add-data",
        f"{ROOT / 'config'};config",
        "--distpath",
        str(BUILD_DIR / "dist"),
        "--workpath",
        str(BUILD_DIR / "work"),
        "--specpath",
        str(BUILD_DIR),
        str(ROOT / "scripts" / "launcher_gui.py"),
    ]
    print("Running PyInstaller ...")
    subprocess.run(command, cwd=ROOT, check=True)
    executable = app_dir / f"{APP_NAME}.exe"
    if not executable.is_file():
        raise SystemExit(f"PyInstaller did not produce {executable}")
    return app_dir


def find_iscc() -> Path:
    override = os.environ.get("LN_AUTO_ISCC")
    candidates = [Path(override)] if override else []
    candidates += [Path(candidate) for candidate in ISCC_CANDIDATES]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "Programs" / "Inno Setup 6" / "ISCC.exe")
    on_path = shutil.which("iscc")
    if on_path:
        candidates.append(Path(on_path))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SystemExit(
        "Inno Setup 6 (ISCC.exe) was not found. Install it with:\n"
        "  winget install --id JRSoftware.InnoSetup -e\n"
        "or set LN_AUTO_ISCC to the full ISCC.exe path."
    )


def compile_installer(iscc: Path, app_dir: Path, version: str) -> Path:
    parts = version.split(".")
    version_info = ".".join((parts + ["0", "0", "0"])[:4])
    script = INNO_TEMPLATE.format(
        app_name=APP_NAME,
        app_id=INNO_APP_ID,
        version=version,
        version_info=version_info,
        app_dir=str(app_dir),
        out_dir=str(ROOT / "dist"),
    )
    iss_path = ROOT / "build" / "installer.iss"
    iss_path.parent.mkdir(parents=True, exist_ok=True)
    # Inno Setup requires a BOM to read non-ASCII (Chinese task text) correctly.
    iss_path.write_text(script, encoding="utf-8-sig")
    print("Compiling the installer with Inno Setup ...")
    subprocess.run([str(iscc), "/Q", str(iss_path)], cwd=ROOT, check=True)
    output = ROOT / "dist" / f"{APP_NAME}-v{version}-Setup.exe"
    if not output.is_file():
        raise SystemExit(f"Inno Setup did not produce {output}")
    return output


def main() -> int:
    version = read_version()
    print(f"Building {APP_NAME} v{version}")
    python = venv_python()
    print(f"Python: {python}")
    ensure_pyinstaller(python)
    app_dir = run_pyinstaller(python)
    iscc = find_iscc()
    print(f"Inno Setup: {iscc}")
    installer = compile_installer(iscc, app_dir, version)
    size_mb = installer.stat().st_size / (1024 * 1024)
    print(f"Installer ready: {installer} ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
