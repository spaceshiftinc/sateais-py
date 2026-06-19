"""load_api_key / save_api_key のテスト"""

from __future__ import annotations

from pathlib import Path

import pytest

from sateais import load_api_key, save_api_key


def test_save_then_load(tmp_path: Path) -> None:
    p = tmp_path / "credentials"
    save_api_key("sk_abc", path=p)
    assert p.exists()
    assert load_api_key(path=p) == "sk_abc"


def test_load_missing_returns_none(tmp_path: Path) -> None:
    assert load_api_key(path=tmp_path / "absent") is None


def test_load_broken_file_returns_none(tmp_path: Path) -> None:
    p = tmp_path / "broken"
    p.write_text("not-json")
    assert load_api_key(path=p) is None


def test_save_trims_whitespace(tmp_path: Path) -> None:
    p = tmp_path / "credentials"
    save_api_key("  sk_padded  ", path=p)
    assert load_api_key(path=p) == "sk_padded"


def test_save_rejects_empty(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        save_api_key("   ", path=tmp_path / "c")


def test_save_sets_restrictive_permission(tmp_path: Path) -> None:
    p = tmp_path / ".sateais" / "credentials"
    save_api_key("sk_abc", path=p)
    assert p.stat().st_mode & 0o777 == 0o600
    # 親ディレクトリも本人のみアクセス可
    assert p.parent.stat().st_mode & 0o777 == 0o700


def test_save_tightens_permission_of_existing_loose_file(tmp_path: Path) -> None:
    p = tmp_path / "credentials"
    # 緩いパーミッションの既存ファイルがあっても 0600 に絞り直す
    p.write_text('{"api_key": "old"}\n', encoding="utf-8")
    p.chmod(0o644)
    save_api_key("sk_new", path=p)
    assert p.stat().st_mode & 0o777 == 0o600
    assert load_api_key(p) == "sk_new"
