# Changelog

このプロジェクトの主要な変更は本ファイルに記録します。
形式は [Keep a Changelog](https://keepachangelog.com/) に準じ、バージョニングは
[Semantic Versioning](https://semver.org/) に従います。

## [Unreleased]

### Changed

- 内部構造を軽量 Hexagonal（HTTP のみ Port 抽象化）に簡素化
- `Clock` / `Sleeper` / `CredentialStore` の Protocol を削除（`time` / 関数を直接利用）
- ファイル数を 24 → 8 に削減（public API 互換）
- `AnalysisRequest.validate()` メソッドに検証ロジックを集約
- `Client(api=...)` 注入時は API キー解決を必須にせず、解決できなければ
  `client.api_key` を `None` とする（認証は注入した `ApiClient` の責務）
- 通信失敗（HTTP ステータスを持たないエラー）の CLI 終了コードを 7 → 1（一般エラー）に変更
- `Job` を不変（`frozen=True`）に変更
- HTTP `User-Agent` を `sateais-python/<version>` 形式に変更

### Fixed

- CLI `--json @FILE` で存在しないファイルを指定した際にトレースバックを露出せず
  クリーンなエラーメッセージで終了するよう修正
- API 応答ボディが非 JSON の場合に生の `ValueError` ではなく `APIError` を送出
- 認証ファイル保存時の権限を強化（ディレクトリ `0700`、書込み前から `0600`）

## [0.1.0] - 2026-05-27

### Added

- 初回リリース
- SDK: `Client` ファサードと検出メソッド5種（ship / oilslick / newbuilding / disappearbuilding / timeseries）
- SDK: ジョブ管理 (`jobs.status` / `jobs.result` / `jobs.wait`)
- CLI: `sateais login`, `sateais analyze <endpoint>`, `sateais jobs {status,result,wait}`
- ファイルベース認証情報ストア（`~/.sateais/credentials`、パーミッション 0600）
- 環境変数 `SATEAIS_API_KEY` / `SATEAIS_BASE_URL` 対応
- AnalysisRequest のドメインルール検証
- 例外階層: `SateAIsError` → `APIError` 系 / `JobFailedError` / `JobTimeoutError` / `CredentialsNotFoundError` / `InvalidAnalysisRequestError`
