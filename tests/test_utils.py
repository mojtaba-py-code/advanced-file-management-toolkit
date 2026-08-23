"""Tests for filesystem helpers, config loading and reporting."""

from __future__ import annotations

from pathlib import Path

import pytest

from utils.config import Config, load_config
from utils.exceptions import ConfigError, OperationError
from utils.fs import categorize, human_readable_size, is_empty_dir
from utils.reporting import generate_report, render


@pytest.mark.parametrize(
    "num, expected",
    [(0, "0 B"), (512, "512 B"), (1024, "1.00 KB"), (1048576, "1.00 MB"), (1073741824, "1.00 GB")],
)
def test_human_readable_size(num: int, expected: str) -> None:
    assert human_readable_size(num) == expected


def test_human_readable_size_negative() -> None:
    with pytest.raises(ValueError):
        human_readable_size(-1)


def test_categorize() -> None:
    assert categorize(Path("a.jpg")) == "Images"
    assert categorize(Path("a.mp4")) == "Videos"
    assert categorize(Path("a.unknownext")) == "Others"


def test_is_empty_dir(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert is_empty_dir(empty) is True
    (empty / "f.txt").write_text("x", encoding="utf-8")
    assert is_empty_dir(empty) is False


def test_load_config_defaults_when_missing(tmp_path: Path) -> None:
    cfg = load_config(None)  # no path -> built-in defaults
    assert cfg["hashing"]["algorithm"] == "sha256"


def test_load_config_missing_explicit_path_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.yaml")


def test_config_dotted_get() -> None:
    cfg = Config()
    assert cfg.get("general.threads") == 4
    assert cfg.get("does.not.exist", "fallback") == "fallback"


def test_reporting_all_formats(tmp_path: Path) -> None:
    payload = {
        "title": "Test",
        "summary": {"items": 2, "bytes": 100},
        "rows": [{"path": "a.txt", "size": 50}, {"path": "b.txt", "size": 50}],
    }
    for fmt in ("json", "csv", "txt", "html"):
        out = generate_report(payload, fmt=fmt, output_dir=tmp_path, name=f"r_{fmt}")
        assert out.exists()
        assert out.suffix == f".{fmt}"
        assert out.read_text(encoding="utf-8").strip()


def test_reporting_rejects_unknown_format() -> None:
    with pytest.raises(OperationError):
        render({"summary": {}}, fmt="xml")
