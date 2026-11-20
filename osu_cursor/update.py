"""Tell whether a newer version is out, from the latest release on GitHub.

The app only says so and shows how to update, it never changes its own files.
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import __version__, gnome

REPOSITORY = "https://github.com/egehankara/cursor-for-osu"
LATEST_RELEASE_API = "https://api.github.com/repos/egehankara/cursor-for-osu/releases/latest"
CHECK_INTERVAL_S = 24 * 60 * 60  # GitHub is asked at most once a day
TIMEOUT_S = 5


@dataclass
class Release:
    version: str
    url: str


def parse_version(text: str) -> tuple[int, ...] | None:
    """(0, 4, 0) for "v0.4.0" or "0.4.0", None for anything else."""
    parts = text.strip().removeprefix("v").split(".")
    if not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def is_newer(latest: str, current: str | None = None) -> bool:
    new, old = parse_version(latest), parse_version(current or __version__)
    return new is not None and old is not None and new > old


def _fetch() -> Release:
    request = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "cursor-for-osu"},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        data = json.load(response)
    return Release(str(data["tag_name"]).removeprefix("v"), str(data["html_url"]))


def latest_release() -> Release | None:
    """The newest release, asked of GitHub once a day and remembered in between."""
    cached = gnome.cached_release()
    if cached and time.time() - cached["checked_at"] < CHECK_INTERVAL_S:
        return Release(cached["version"], cached["url"])
    try:
        release = _fetch()
    except (OSError, ValueError, KeyError, TypeError):
        # No network, GitHub down or a changed answer: try again next time.
        return Release(cached["version"], cached["url"]) if cached else None
    gnome.cache_release(release.version, release.url, time.time())
    return release


def available_update() -> Release | None:
    """The newer release, or None when this one is the latest, it was skipped or checking is off."""
    if not gnome.update_check_enabled():
        return None
    release = latest_release()
    if release is None or not is_newer(release.version) or release.version == gnome.skipped_update():
        return None
    return release


def source_dir() -> Path | None:
    """The folder install.sh was run from, which git pull updates."""
    try:
        folder = Path((gnome.data_dir() / "install-source").read_text().strip())
    except OSError:
        return None
    return folder if (folder / ".git").is_dir() else None
