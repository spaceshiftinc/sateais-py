# Contributing

`sateais` SDK 開発者向けガイド。

## 開発環境セットアップ

[uv](https://docs.astral.sh/uv/) を使用します。

```bash
git clone <repo-url>
cd sateais-py
uv sync --extra dev
source .venv/bin/activate
```

開発インストール（CLI を `sateais` コマンドで使えるようにする）:

```bash
uv tool install -e .
```

## 日常コマンド

```bash
# テスト
pytest                                  # 全テスト
pytest tests/unit/application -v        # 特定レイヤー
pytest -k test_wait                     # キーワード絞り込み

# Lint / Format
ruff check src/ tests/                  # チェック
ruff check --fix src/ tests/            # 自動修正
ruff format src/ tests/                 # フォーマット

# 型チェック
mypy src/sateais
```

CI ではこれら全てが通る必要があります。

## ブランチ戦略

- `develop`（デフォルト）← `feature/*`
- リリース時のみ `develop` → `main`
- PR タイトル: `feat:` / `fix:` / `docs:` / `chore:` / `refactor:` プレフィクス

## コーディング規約

ワークスペース共通の規約に従います:

- **docstring / コメントは日本語**
- **ログメッセージは英語**（`[モジュール名] message: detail` 形式）
- 型ヒント必須
- TODO / FIXME / デバッグコード残し禁止
- 仕様変更時は `docs/` を先に更新

## アーキテクチャを守る

[ARCHITECTURE.md](ARCHITECTURE.md) の依存方向ルールを厳守してください。

| ファイル | 依存できる相手 |
|---|---|
| `_types.py` / `_errors.py` | 標準ライブラリのみ |
| `_http.py` | `_types`, `_errors` + `httpx` |
| `_credentials.py` | 標準ライブラリ (`json`, `pathlib`) のみ |
| `_client.py` / `cli.py` | 上のすべて |

レビュー時の主な観点:

1. 新しい外部ライブラリ依存は `_http.py` 相当のモジュールに閉じているか
2. ドメインルール（必須パラメータ組合せなど）は `AnalysisRequest.validate()` にあるか
3. CLI / SDK 固有の引数解釈・出力整形が下位モジュールに漏れていないか
4. 「これは Port を切るべきか？」を即決せず、CLAUDE.md の判断基準（テストで困るか + 差し替え未来があるか）を当てはめる

## テストの追加

新機能・バグ修正には必ずテストを追加してください。`tests/` 直下のフラット構成です:

| 変更対象 | テストファイル |
|---|---|
| エンティティ / `AnalysisRequest.validate` | `tests/test_types.py` |
| HTTP 通信 / エラーマッピング | `tests/test_http.py` |
| 認証ファイル | `tests/test_credentials.py` |
| Client / Analyze / Jobs | `tests/test_client.py` |
| CLI | `tests/test_cli.py` |

HTTP を絡めないテストは `tests/conftest.FakeApiClient` を `api=` パラメータで注入してください。

## リリース手順

1. `src/sateais/_version.py` の `__version__` を更新
2. `CHANGELOG.md` に変更点を追記
3. `develop` → `main` の PR
4. main マージ後、タグ付け `git tag v0.x.0 && git push --tags`
5. `uv build && uv publish`（または GitHub Actions）
