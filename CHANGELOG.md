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
