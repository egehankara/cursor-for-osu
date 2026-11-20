import pytest

from osu_cursor import gnome, update


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    return tmp_path


@pytest.fixture
def github(monkeypatch):
    """Stands in for GitHub, counting how often it is asked."""
    state = {"release": update.Release("0.4.0", "https://example.invalid/v0.4.0"), "calls": 0, "error": None}

    def fetch():
        state["calls"] += 1
        if state["error"]:
            raise state["error"]
        return state["release"]

    monkeypatch.setattr(update, "_fetch", fetch)
    return state


@pytest.mark.parametrize(
    ("latest", "current", "expected"),
    [
        ("0.4.0", "0.3.0", True),
        ("v0.3.1", "0.3.0", True),
        ("0.10.0", "0.9.0", True),  # compared as numbers, not text
        ("1.0", "0.9.9", True),
        ("0.3.0", "0.3.0", False),
        ("0.2.9", "0.3.0", False),
        ("0.4.0-beta", "0.3.0", False),  # not understood, so not offered
        ("", "0.3.0", False),
    ],
)
def test_newer_versions(latest, current, expected):
    assert update.is_newer(latest, current) is expected


def test_github_is_asked_once_a_day(data, github, monkeypatch):
    now = 1_000_000.0
    monkeypatch.setattr(update.time, "time", lambda: now)
    assert update.latest_release().version == "0.4.0"
    assert update.latest_release().version == "0.4.0"
    assert github["calls"] == 1

    now += update.CHECK_INTERVAL_S + 1
    github["release"] = update.Release("0.5.0", "https://example.invalid/v0.5.0")
    assert update.latest_release().version == "0.5.0"
    assert github["calls"] == 2


def test_without_network_the_last_answer_is_kept(data, github, monkeypatch):
    assert update.latest_release() is not None
    monkeypatch.setattr(update.time, "time", lambda: 10**12)  # the cache is old
    github["error"] = OSError("no network")
    assert update.latest_release().version == "0.4.0"


def test_without_network_and_without_an_answer_nothing_is_shown(data, github):
    github["error"] = OSError("no network")
    assert update.latest_release() is None
    assert update.available_update() is None


def test_update_is_offered_only_when_newer_and_turned_on(data, github, monkeypatch):
    monkeypatch.setattr(update, "__version__", "0.3.0")
    assert update.available_update().version == "0.4.0"

    gnome.set_update_check_enabled(False)
    assert update.available_update() is None

    gnome.set_update_check_enabled(True)
    monkeypatch.setattr(update, "__version__", "0.4.0")
    assert update.available_update() is None


def test_source_folder_from_install(data, tmp_path):
    assert update.source_dir() is None
    source = tmp_path / "cursor-for-osu"
    (source / ".git").mkdir(parents=True)
    gnome.data_dir().mkdir(parents=True)
    (gnome.data_dir() / "install-source").write_text(f"{source}\n")
    assert update.source_dir() == source


def test_a_skipped_version_is_not_offered_but_the_next_one_is(data, github, monkeypatch):
    monkeypatch.setattr(update, "__version__", "0.3.0")
    gnome.skip_update("0.4.0")
    assert update.available_update() is None

    github["release"] = update.Release("0.5.0", "https://example.invalid/v0.5.0")
    monkeypatch.setattr(update.time, "time", lambda: 10**12)  # a day later
    assert update.available_update().version == "0.5.0"
