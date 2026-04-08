import os
import shutil
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
APP_NAME = "GrafanaScheduler"
LEGACY_FILES = ("database.db", "secret.key", "clock.log", "dashboard_capture.log")


def _default_data_dir():
    if os.name == "nt":
        root = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or str(Path.home())
        return Path(root) / APP_NAME / "data"
    if sys_platform_startswith("darwin"):
        return Path.home() / "Library" / "Application Support" / APP_NAME / "data"
    return Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME / "data"


def sys_platform_startswith(prefix):
    import sys

    return sys.platform.startswith(prefix)


DATA_DIR = Path(os.getenv("APP_DATA_DIR") or _default_data_dir()).resolve()


def _migrate_legacy_files():
    for filename in LEGACY_FILES:
        legacy_path = BASE_DIR / filename
        target_path = DATA_DIR / filename
        if legacy_path.exists() and not target_path.exists():
            shutil.move(str(legacy_path), str(target_path))


def ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_files()


def data_path(*parts):
    ensure_data_dir()
    return str(DATA_DIR.joinpath(*parts))
