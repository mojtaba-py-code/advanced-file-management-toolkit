"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def sample_tree(tmp_path: Path) -> Path:
    """Create a small, predictable directory tree for tests.

    Layout::

        root/
            a.txt         "hello world"
            b.txt         "hello world"   (duplicate of a.txt)
            unique.txt    "different"
            photo.jpg     "img"
            clip.mp4      "vid"
            empty.dat     ""              (zero-byte)
            temp.tmp      "junk"          (temp file)
            sub/
                nested.txt  "nested"
            emptydir/       (empty directory)
    """
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    (root / "emptydir").mkdir()

    (root / "a.txt").write_text("hello world", encoding="utf-8")
    (root / "b.txt").write_text("hello world", encoding="utf-8")
    (root / "unique.txt").write_text("different content", encoding="utf-8")
    (root / "photo.jpg").write_text("img", encoding="utf-8")
    (root / "clip.mp4").write_text("vid", encoding="utf-8")
    (root / "empty.dat").write_text("", encoding="utf-8")
    (root / "temp.tmp").write_text("junk", encoding="utf-8")
    (root / "sub" / "nested.txt").write_text("nested", encoding="utf-8")
    return root
