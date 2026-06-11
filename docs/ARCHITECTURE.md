# Architecture

`sateais` Python SDK / CLI の内部構造ドキュメント。

## 設計方針

**軽量な Hexagonal 構成**を採用しています。SDK 規模に対する過剰設計を避けつつ、
唯一テストで差し替え価値の高い HTTP 通信だけを Port で抽象化しています。

## ファイル構成

```
src/sateais/
├── __init__.py        # public API の再エクスポート
├── _version.py
├── _types.py          # Job, JobStatus, AnalysisType, AnalysisRequest（+validate）
├── _errors.py         # 例外階層
├── _http.py           # ApiClient Protocol + HttpApiClient（唯一の I/O 抽象境界）
├── _credentials.py    # load_api_key / save_api_key（具体関数、Protocol なし）
├── _spinner.py        # 待機中の衛星「信号パルス」アスキーアニメーション（stdlib のみ、CLI 専用）
├── _client.py         # Client + Analyze + Jobs（ユーザー向けファサード）
└── cli.py             # argparse CLI（自身が composition root）
```

## 依存方向

```
__init__.py
    ↓
_client.py , cli.py        (delivery — facade / CLI)
    ↓
_http.py                   (ApiClient Protocol + HttpApiClient)
    ↓
_types.py , _errors.py     (entities / exceptions, 外部依存なし)

_credentials.py            (filesystem 専用、横参照なし)
_spinner.py                (CLI 表示専用、stdlib のみ、横参照なし)
```

ルール:

- `_types.py` / `_errors.py` は標準ライブラリのみに依存（外部ライブラリ NG）
- `_http.py` は `httpx` 依存をここに閉じ込める
- `_credentials.py` は `json` / `pathlib` 以外に依存しない
- `_spinner.py` は `os` / `shutil` / `sys` / `threading` 以外に依存しない（CLI からのみ利用）
- `_client.py` / `cli.py` がすべてを結線する composition root

## Port の使い分け

### Port を切ったもの: `ApiClient`

```python
# _http.py
@runtime_checkable
class ApiClient(Protocol):
    def submit_analysis(self, request: AnalysisRequest) -> Job: ...
    def get_job(self, job_id: str) -> Job: ...
    def get_job_result(self, job_id: str) -> dict[str, Any]: ...
    def close(self) -> None: ...
```

**理由**:

- テスト時に HTTP 通信を完全に排除した Fake で網羅できる
- 将来 gRPC / Mock サーバ / Replay 機構など、別 transport を足す余地が現実的にある
- 既に `tests/conftest.py:FakeApiClient` で活用済み

### Port を切らなかったもの

| 機能 | 対処 | 理由 |
|---|---|---|
| 時刻 (`time.monotonic`) | 直接呼ぶ | テストは `monkeypatch.setattr(time, "monotonic", ...)` で十分 |
| スリープ (`time.sleep`) | 直接呼ぶ | 同上 |
| 認証ファイル | `load_api_key(path=...)` / `save_api_key(api_key, path=...)` 関数 | テストは `tmp_path` を渡せる |

**判断基準**: 「将来差し替える可能性が現実的にあるか？」「テストで困るか？」の両方が
弱い場合は Protocol を作らず具体実装を使う。

## 待機中の表示（`_spinner.py`）

`--wait` でジョブ完了を待つ間、`cli._wait_for_job` が `SatelliteSpinner` を起動し、
衛星 `▭┋▣┋▭` が右へ信号波 `)` を流す「信号パルス」アスキーアニメーションを 1 行で
表示する（遊び心の演出）。

- 発射リズムは心拍（ハートビート）パターン: 16 フレームのループ内 `{0, 2, 8, 10}` で発射。
- 波は送信源から毎フレーム右へ 1 進み、距離に応じて減衰する。truecolor 端末では
  ティール系の明度で、非対応端末ではグリフ濃淡（`) → ) → ·`）で表現する。
- 送信源は発射フレームだけ明るく（`◉` / 非発射は `◎`）光る。
- 描画関数は `render=` で差し替え可能（`examples/spinner_gallery.py` に別案あり）。

- **stderr が TTY のときだけ** daemon スレッドでアニメーションする。`NO_COLOR` 指定時や
  端末幅が狭いときは無効化される（`SatelliteSpinner.enabled`）。
- 非 TTY（パイプ / リダイレクト / テスト）では従来どおり、ステータス変化時のみ
  1 行ログ（`cli._process_callback`）にフォールバックする。
- 結果 GeoJSON は stdout、アニメーション / ログは stderr に分離しているため、
  `sateais ... --wait > out.geojson` の出力は演出に汚染されない。

## 検証ロジックの置き場所

`AnalysisRequest.validate()` メソッドに集約。
`Analyze._submit()` と `cli._cmd_analyze` が submit 直前に呼ぶ。

```python
@dataclass(frozen=True)
class AnalysisRequest:
    ...
    def validate(self) -> None:
        # 必須パラメータの組み合わせを検証
```

エンティティ自身が自分の整合性を知っているのが自然なので、
別ユースケースクラスを作らずメソッドにした。

## 公開境界

トップレベル `sateais` から export しているものはすべて public。
詳細は [`src/sateais/__init__.py`](../src/sateais/__init__.py) の `__all__` 参照。

`_` で始まるモジュール (`_client`, `_http` など) は内部実装で、
直接 import するのは「準 public」扱い（メジャーバージョン以外で変更しない努力はする）。

## 新しいエンドポイントを追加する

1. `_types.py` の `AnalysisType` enum に値を追加
   - 必要なら `accepts_scene_or_polygon_date` / `requires_date_range` プロパティを更新
2. `AnalysisRequest.validate()` のルール分岐が既存パターンで賄えるか確認
3. `_client.py` の `Analyze` クラスに新しいメソッドを追加
4. CLI 側は `ANALYZE_ENDPOINTS` の Enum 列挙で自動対応（変更不要）
5. `tests/test_types.py` で `validate` のテスト、`tests/test_client.py` で `Analyze.<name>()` のテストを追加

## HTTP レスポンス形式が変わった場合

`_http.py` の `_job_from_dict` / `_raise_api_error` のみ更新。
他のファイルは触らない。

## 新しいエラーコードを追加する場合

1. `_errors.py` に新例外クラスを追加
2. `_http._STATUS_CODE_MAP` に HTTP ステータス → 例外のマッピング追加
3. `__init__.py` の `__all__` に追加
4. `tests/test_http.py::test_http_errors_map_to_domain_exceptions` のパラメータに追加

## テスト構成

```
tests/
├── conftest.py            # FakeApiClient + make_job ヘルパー
├── test_types.py          # JobStatus / Job / AnalysisType / AnalysisRequest
├── test_errors.py         # (今のところ test_types に統合)
├── test_http.py           # HttpApiClient（httpx.MockTransport）
├── test_credentials.py    # load_api_key / save_api_key（tmp_path）
├── test_client.py         # Client / Analyze / Jobs（FakeApiClient + monkeypatch time）
└── test_cli.py            # CLI（FakeApiClient 注入）
```
