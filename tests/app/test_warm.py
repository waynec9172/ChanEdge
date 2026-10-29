"""Warm counting and the startup key check. No network."""

from pathlib import Path

from chanedge.app.cli import main
from chanedge.app.jev_warm import enable_floor

ROOT = Path(__file__).resolve().parents[2]


def test_enable_floor_needs_both_sides() -> None:
    assert enable_floor(30, 30) is True
    assert enable_floor(29, 30) is False
    assert enable_floor(30, 3) is False
    assert enable_floor(270, 30) is True
    assert enable_floor(0, 0) is False


def test_enabled_paper_refuses_to_start_without_the_key(tmp_path: Path, capsys) -> None:
    overlay = tmp_path / "on.yaml"
    overlay.write_text(
        "systemone:\n  enabled: true\njev:\n  version: typesafe-v1\n",
        encoding="utf-8",
    )
    code = main(
        [
            "paper",
            "--once",
            "--config",
            str(ROOT / "config" / "default.yaml"),
            "--overlay",
            str(overlay),
            "--root",
            str(tmp_path),
        ],
        environ={},
        exchange=_Boom(),
        clock=_Boom(),
    )
    assert code == 1
    assert "TYPESAFE_API_KEY" in capsys.readouterr().err


def test_jev_warm_stays_off_with_the_default_file(tmp_path: Path, capsys) -> None:
    code = main(
        [
            "jev-warm",
            "--config",
            str(ROOT / "config" / "default.yaml"),
            "--root",
            str(tmp_path),
        ],
        environ=_Boom(),
        exchange=_Boom(),
        clock=_Boom(),
    )
    assert code == 1
    assert "systemone.enabled is false" in capsys.readouterr().err


class _Boom:
    def __getattr__(self, name: str):
        raise AssertionError(name)
