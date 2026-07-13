# Changelog

このプロジェクトの主要な変更は本ファイルに記録します。
形式は [Keep a Changelog](https://keepachangelog.com/) に準じ、バージョニングは
[Semantic Versioning](https://semver.org/) に従います。

## [Unreleased]

## [0.1.0] - 2026-07-13

初回の安定版リリース。内容は `0.1.0rc1` 〜 `0.1.0rc3` の累積で、RC からの機能変更はありません。

### Added

- SDK: `Client` ファサードと解析メソッド5種（ship / oilslick / newbuilding / disappearbuilding / timeseries）
- SDK: ジョブ管理 (`jobs.status` / `jobs.result` / `jobs.wait`)
- CLI: `sateais login`, `sateais analyze <endpoint>`, `sateais jobs {status,result,wait}`
- ファイルベース認証情報ストア（`~/.sateais/credentials`、パーミッション 0600）
- 環境変数 `SATEAIS_API_KEY` / `SATEAIS_BASE_URL` 対応
- AnalysisRequest のドメインルール検証
- 例外階層: `SateAIsError` → `APIError` 系 / `JobFailedError` / `JobTimeoutError` /
  `CredentialsNotFoundError` / `InvalidAnalysisRequestError` / `UnknownJobStatusError`
- 軽量 Hexagonal 構成（HTTP 通信のみ `ApiClient` Port で抽象化）
- `Sentinel-1C`（S1C）の相対軌道番号オフセット（172, ESA 定義）に対応

## [0.1.0rc3] - 2026-06-23

### Added

- 例外 `UnknownJobStatusError` を追加。`jobs.wait()` で未知ステータス（`UNKNOWN`）が
  `max_unknown_polls` 回連続した場合に送出し、既定の無限待機でのハングを防ぐ
- `Sentinel-1C`（S1C）の相対軌道番号オフセット（172, ESA 定義）に対応

### Fixed

- CLI: `-o/--output` の書き込み失敗・`login` の認証ファイル保存失敗（`OSError`）で
  生のトレースバックを露出せず、クリーンなエラーで終了コード 1 にするよう修正
- API 応答に `job_id` が欠落／非オブジェクトの場合に生の `KeyError` ではなく `APIError` を送出
- `get_job_result` が JSON 配列/スカラを受けた場合に `dict` 契約を守り `APIError` を送出
- `jobs.wait()` が未知ステータスを返し続けると無限ループしていた問題を修正（上記 `UnknownJobStatusError`）
- 待機アニメーションが `NO_COLOR` で完全停止していたのを修正（`NO_COLOR` は色のみ無効化し、アニメは継続）
- シーンID デコードで暦日として無効な日時を整形せず素の値で表示するよう修正

## [0.1.0rc2] - 2026-06-19

### Changed

- `Client(api=...)` 注入時は API キー解決を必須にせず、解決できなければ
  `client.api_key` を `None` とする（認証は注入した `ApiClient` の責務）
- 通信失敗（HTTP ステータスを持たないエラー）の CLI 終了コードを 7 → 1（一般エラー）に変更
- `Job` を不変（`frozen=True`）に変更
- HTTP `User-Agent` を `sateais-py/<version>` 形式に変更

### Fixed

- CLI `--json @FILE` で存在しないファイルを指定した際にトレースバックを露出せず
  クリーンなエラーメッセージで終了するよう修正
- API 応答ボディが非 JSON の場合に生の `ValueError` ではなく `APIError` を送出
- 認証ファイル保存時の権限を強化（ディレクトリ `0700`、書込み前から `0600`）
- ドキュメントの用語不整合を修正（`detect` → `analyze` 系へ統一）

## [0.1.0rc1] - 2026-06-17

### Added

- SDK: `Client` ファサードと解析メソッド5種（ship / oilslick / newbuilding / disappearbuilding / timeseries）
- SDK: ジョブ管理 (`jobs.status` / `jobs.result` / `jobs.wait`)
- CLI: `sateais login`, `sateais analyze <endpoint>`, `sateais jobs {status,result,wait}`
- ファイルベース認証情報ストア（`~/.sateais/credentials`、パーミッション 0600）
- 環境変数 `SATEAIS_API_KEY` / `SATEAIS_BASE_URL` 対応
- AnalysisRequest のドメインルール検証
- 例外階層: `SateAIsError` → `APIError` 系 / `JobFailedError` / `JobTimeoutError` / `CredentialsNotFoundError` / `InvalidAnalysisRequestError`
- 軽量 Hexagonal 構成（HTTP 通信のみ `ApiClient` Port で抽象化）
