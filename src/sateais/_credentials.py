"""認証情報の永続化

`~/.sateais/credentials` に JSON で APIキーを保存・読込する。
パーミッションは 0600 に設定する。

Protocol は切らない（差し替える必要性が薄いため）。
テストでは `path` 引数で `tmp_path` に向けて検証する。
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_CREDENTIALS_PATH = Path.home() / ".sateais" / "credentials"


def load_api_key(path: Path | None = None) -> str | None:
    """APIキーをファイルから読み込む

    Args:
        path: ファイルパス（デフォルト: `~/.sateais/credentials`）

    Returns:
        保存されたAPIキー。ファイル無し・破損時は None。
    """

    p = path or DEFAULT_CREDENTIALS_PATH
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    key = data.get("api_key") if isinstance(data, dict) else None
    return key if isinstance(key, str) else None


def save_api_key(api_key: str, path: Path | None = None) -> Path:
    """APIキーをファイルに保存する

    Args:
        api_key: 保存するAPIキー（前後空白は除去される）
        path: ファイルパス（デフォルト: `~/.sateais/credentials`）

    Returns:
        保存先ファイルパス

    Raises:
        ValueError: APIキーが空文字列の場合
    """

    if not api_key or not api_key.strip():
        raise ValueError("api_key must be non-empty")
    p = path or DEFAULT_CREDENTIALS_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    # ディレクトリも本人のみアクセス可に絞る（既存ディレクトリにも適用）
    try:
        p.parent.chmod(0o700)
    except OSError:
        pass
    # APIキー本文を書き込む前に 0600 の空ファイルを用意し、
    # 「生成〜chmod」の間に他ユーザーから読める窓を無くす。
    p.touch(mode=0o600, exist_ok=True)
    try:
        p.chmod(0o600)  # 既存ファイルが緩いパーミッションだった場合に備え再設定
    except OSError:
        # パーミッション設定に失敗しても保存自体は成功しているので例外は無視する
        pass
    p.write_text(
        json.dumps({"api_key": api_key.strip()}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return p
