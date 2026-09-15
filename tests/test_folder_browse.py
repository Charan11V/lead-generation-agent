"""Tests for Workspace folder browse helpers."""

from __future__ import annotations

from pathlib import Path

from frequency_agent.folder_browse import (
    browse_roots,
    default_save_folder,
    list_subfolders,
    parent_within_roots,
)


def test_browse_roots_includes_exports(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / "Documents").mkdir()
    roots = browse_roots(tmp_path / "project")
    names = {r.name for r in roots}
    assert "Documents" in names
    assert "exports" in names
    assert Path(default_save_folder(tmp_path / "project")).is_dir()


def test_list_subfolders_and_parent(tmp_path: Path):
    root = tmp_path / "Documents"
    child = root / "leads"
    child.mkdir(parents=True)
    (child / "nested").mkdir()
    assert [p.name for p in list_subfolders(root)] == ["leads"]
    assert parent_within_roots(child, [root]) == root
    assert parent_within_roots(root, [root]) is None
