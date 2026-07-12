"""FIX-12: WAD_DATA_DIR override + the platformdirs-style default."""

from __future__ import annotations

from pathlib import Path

from pipeline import paths


def test_env_override_is_honored(monkeypatch, tmp_path) -> None:
    target = tmp_path / "custom-wad-data"
    monkeypatch.setenv("WAD_DATA_DIR", str(target))
    assert paths.resolve_data_dir() == target.resolve()


def test_env_override_expands_user(monkeypatch) -> None:
    monkeypatch.setenv("WAD_DATA_DIR", "~")
    resolved = paths.resolve_data_dir()
    assert resolved == Path.home().resolve()
    assert resolved.is_absolute()


def test_blank_env_override_falls_back_to_default(monkeypatch) -> None:
    monkeypatch.setenv("WAD_DATA_DIR", "   ")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert paths.resolve_data_dir() == paths._default_data_dir()


def test_unset_env_falls_back_to_default(monkeypatch) -> None:
    monkeypatch.delenv("WAD_DATA_DIR", raising=False)
    assert paths.resolve_data_dir() == paths._default_data_dir()


def test_default_dir_is_stable_and_absolute(monkeypatch) -> None:
    monkeypatch.delenv("WAD_DATA_DIR", raising=False)
    first = paths.resolve_data_dir()
    second = paths.resolve_data_dir()
    assert first == second
    assert first.is_absolute()
    assert first.name == "wad"


def test_default_dir_is_cwd_independent(monkeypatch, tmp_path) -> None:
    """Two 'shells' in different working directories must resolve the same path."""
    monkeypatch.delenv("WAD_DATA_DIR", raising=False)
    here = tmp_path / "here"
    there = tmp_path / "there"
    here.mkdir()
    there.mkdir()

    monkeypatch.chdir(here)
    from_here = paths.resolve_data_dir()

    monkeypatch.chdir(there)
    from_there = paths.resolve_data_dir()

    assert from_here == from_there


def test_env_override_is_also_cwd_independent(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAD_DATA_DIR", str(tmp_path / "shared"))
    monkeypatch.chdir(tmp_path)
    a = paths.resolve_data_dir()
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.chdir(tmp_path / "elsewhere")
    b = paths.resolve_data_dir()
    assert a == b


def test_default_db_path_creates_parent_and_is_named_cache_db(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAD_DATA_DIR", str(tmp_path / "data"))
    db_path = paths.default_db_path()
    assert db_path == (tmp_path / "data" / "cache.db").resolve()
    assert db_path.parent.is_dir()


def test_default_data_dir_platform_darwin(monkeypatch) -> None:
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    resolved = paths._default_data_dir()
    assert resolved.parts[-2:] == ("Application Support", "wad")


def test_default_data_dir_platform_linux_uses_xdg(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    resolved = paths._default_data_dir()
    assert resolved == (tmp_path / "xdg" / "wad").resolve()


def test_default_data_dir_platform_linux_falls_back_without_xdg(monkeypatch) -> None:
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    resolved = paths._default_data_dir()
    assert resolved.parts[-3:] == (".local", "share", "wad")


def test_default_data_dir_platform_windows_uses_appdata(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    resolved = paths._default_data_dir()
    assert resolved == (tmp_path / "Roaming" / "wad").resolve()
