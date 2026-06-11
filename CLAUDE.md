# CLAUDE.md

このファイルは Claude Code（AI）が `sateais-py` リポジトリで作業する際のガイドラインです。

## プロジェクト概要

**`sateais`** — SateAIs（SAR 衛星画像解析プラットフォーム、現状の対応衛星は Sentinel-1）の公式 Python SDK / CLI。

- `pip install sateais` 1 つで **SDK と CLI の両方** が入る（`openai-python` パターン）
- API 仕様: [products/sateais-api-orchestrator/docs/API.md](../../products/sateais-api-orchestrator/docs/API.md)
- 公開予定パッケージ — 後方互換性に注意

## 技術スタック

- Python 3.10+
- 依存: `httpx` のみ（CLI は stdlib `argparse`）
- ビルド: `hatchling`
- パッケージマネージャ: `uv`
- 型チェック: `mypy`
- Lint/Format: `ruff`

## アーキテクチャ

**軽量 Hexagonal**（HTTP のみ Port 抽象化）。詳細は [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

```
src/sateais/
├── __init__.py        # public API
├── _types.py          # エンティティ + AnalysisRequest.validate()
├── _errors.py         # 例外
├── _http.py           # ApiClient Protocol + HttpApiClient（唯一の Port）
├── _credentials.py    # load_api_key / save_api_key 関数
├── _spinner.py        # 待機中の衛星「信号パルス」アスキーアニメーション（CLI 専用）
├── _client.py         # Client + Analyze + Jobs
└── cli.py             # argparse CLI
```

### 依存方向（厳守）

- `_types.py` / `_errors.py`: 標準ライブラリのみ
- `_http.py`: `httpx` 依存はここに閉じる
- `_credentials.py`: `json` / `pathlib` のみ
- `_spinner.py`: `os` / `shutil` / `sys` / `threading` のみ（cli からのみ利用）
- `_client.py` / `cli.py`: 上のすべてを結線

### 設計判断: なぜ Port は ApiClient だけか

- **`ApiClient` Port あり**: テストで HTTP を完全排除でき、将来 transport を増やす余地もある
- **`time` / `_credentials` は Port なし**: テストでは `monkeypatch` / `tmp_path` で十分。Protocol を切るとファイル数が増えるだけで価値が無い

**「Port を切るか」の判断基準は「テストで本当に困るか」+「差し替える未来が現実的にあるか」**。両方弱ければ Port を切らない。

## コーディング規約

ワークスペース共通の規約に従う:

- **docstring / コメントは日本語**
- **ログメッセージは英語**（`[モジュール名] message: detail` 形式）
- 型ヒント必須
- TODO / FIXME / デバッグコード残し禁止
- 仕様変更時は `docs/` を先に更新

### Public API の境界

`__init__.py` の `__all__` で export しているものはすべて public。SemVer 注意:

```python
from sateais import (
    Client, Job, JobStatus, AnalysisRequest, AnalysisType, ApiClient,
    load_api_key, save_api_key,
    SateAIsError, APIError, AuthenticationError, ValidationError,
    InsufficientCreditsError, NotFoundError, RateLimitError,
    JobFailedError, JobTimeoutError, CredentialsNotFoundError,
    InvalidAnalysisRequestError,
)
```

`_` 始まりのモジュール直 import は準 public 扱い。

## よくある作業の指針

### 新エンドポイントを追加する

1. `_types.py` の `AnalysisType` enum に値を追加
2. 必要なら `AnalysisRequest.validate()` のルール分岐を更新
3. `_client.py` の `Analyze` クラスにメソッド追加
4. CLI は `ANALYZE_ENDPOINTS` の Enum 列挙で自動対応（変更不要）
5. テスト追加 (`tests/test_types.py` + `tests/test_client.py`)

### HTTP レスポンス形式が変わった

`_http.py` の `_job_from_dict` / `_raise_api_error` のみ更新。他のファイルには触らない。

### 新しいエラーコードを追加する

1. `_errors.py` に例外クラスを追加
2. `_http._STATUS_CODE_MAP` にマッピング追加
3. `__init__.py` の `__all__` に追加
4. `tests/test_http.py` のパラメータに追加

### 新しい外部ライブラリを導入したい

原則 `httpx` 以外は追加しない方針。やむを得ない場合:

1. `_http.py` 相当の専用モジュールに依存を閉じ込める
2. `_types.py` / `_errors.py` / `_credentials.py` には絶対に持ち込まない
3. `pyproject.toml` に依存追加

## テスト

```
tests/
├── conftest.py            # FakeApiClient + make_job
├── test_types.py          # Entity + validate
├── test_http.py           # HttpApiClient（httpx.MockTransport）
├── test_credentials.py    # load/save (tmp_path)
├── test_client.py         # Client / Analyze / Jobs（FakeApiClient + monkeypatch time）
└── test_cli.py            # CLI（FakeApiClient 注入）
```

主要パターン:

- **HTTP を絡めるテスト** → `httpx.MockTransport`（`tests/test_http.py`）
- **HTTP を絡めないテスト** → `tests/conftest.FakeApiClient` を `api=` で注入
- **時刻系** → `monkeypatch.setattr(time, "sleep", ...)` / `monkeypatch.setattr(time, "monotonic", ...)`
- **認証ファイル** → `tmp_path` を `path=` で渡すか、`monkeypatch.setattr("sateais._client.load_api_key", ...)`

```bash
pytest                              # 全テスト
pytest tests/test_client.py -v      # 単一ファイル
pytest -k test_wait                 # キーワード絞り
ruff check src/ tests/              # Lint
ruff format src/ tests/             # Format
mypy src/sateais                    # 型チェック
```

## 後方互換性 (publish 後)

- public シンボルの **削除・改名は禁止**（deprecation 経由のみ）
- メソッドシグネチャの引数追加は kwarg-only + default あり
- `AnalysisType` の値（文字列）は API 契約と一致させる
- 例外クラスの継承関係は SemVer メジャー以外で変更しない
- `ApiClient` Protocol の追加メソッド（破壊的変更）はメジャー以外禁止

## ブランチ / PR

- `develop`（デフォルト）← `feature/*`
- リリース時のみ `develop` → `main`
- PR タイトル: `feat:` / `fix:` / `docs:` / `chore:` / `refactor:`

## 関連リポジトリ

- [sateais-api-orchestrator](../../products/sateais-api-orchestrator/) — バックエンド API
- [sateais-js](../sateais-js/) — JS/TS SDK（将来）
- [sateais-platform](../../sateais-platform/) — 横断ドキュメント
