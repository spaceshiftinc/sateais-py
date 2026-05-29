# sateais

SateAIs の公式 Python SDK / CLI。SAR 衛星画像の解析API
（船舶 / オイルスリック / 新規・消失建物 / 時系列変化）を一発で叩けます。
（現状の対応衛星は Sentinel-1。今後拡張予定。）

```bash
pip install sateais
```

これ 1 つで **SDK と CLI の両方** が入ります（`openai-python` と同じパターン）。

## クイックスタート

```python
from sateais import Client

client = Client()                                  # 認証は自動解決
job = client.detect.ship(scene_id="S1A_IW_GRDH_...")
result = client.jobs.wait(job.job_id)              # 完了まで同期 polling
print(len(result["features"]), "ships detected")
```

```bash
sateais login --api-key sk_live_xxxxx
sateais detect ship --scene-id S1A_IW_GRDH_... --wait -o ships.geojson
```

## 認証

優先度: `api_key` 引数 > 環境変数 `SATEAIS_API_KEY` > `~/.sateais/credentials`

```bash
sateais login --api-key sk_live_xxxxx     # → ~/.sateais/credentials (0600)
# または
export SATEAIS_API_KEY=sk_live_xxxxx
```

`SATEAIS_BASE_URL` で dev 環境などへの切替も可能。

## SDK

### 検出メソッド

| メソッド | 入力パターン |
|---|---|
| `client.detect.ship(...)` | `scene_id` または `polygon`+`date` |
| `client.detect.oilslick(...)` | 同上 |
| `client.detect.newbuilding(...)` | `polygon`+`date_start`+`date_end` |
| `client.detect.disappearbuilding(...)` | 同上 |
| `client.detect.timeseries(...)` | 同上 |

詳細パラメータは [API リファレンス](../../products/sateais-api-orchestrator/docs/API.md) 参照。

### ジョブ管理

```python
job = client.jobs.status(job_id)            # 現在の状態を1回取得
geojson = client.jobs.result(job_id)        # 完了済ジョブの結果
geojson = client.jobs.wait(
    job_id,
    poll_interval=10,                       # 秒
    timeout=600,                            # 秒、None で無限
    on_poll=lambda j: print(j.status),      # 進捗コールバック
)
```

### 例外

| 例外 | 発生条件 |
|---|---|
| `AuthenticationError` | 401 / 403 |
| `ValidationError` | 400 |
| `InsufficientCreditsError` | 402 |
| `NotFoundError` | 404 / 410 |
| `RateLimitError` | 429 |
| `APIError` | 上記以外のHTTPエラー |
| `JobFailedError` | `wait()` 中にジョブが failed |
| `JobTimeoutError` | `wait()` がタイムアウト |
| `CredentialsNotFoundError` | APIキーが解決できない |
| `InvalidDetectionRequestError` | 必須パラメータの組合せ不正 |

## CLI

```bash
sateais login [--api-key sk_...]                  # APIキーを保存（省略時はプロンプト）
sateais detect <endpoint> [options] [--wait] [-o FILE]
sateais jobs status <job_id>
sateais jobs result <job_id> [-o FILE]
sateais jobs wait   <job_id> [-o FILE] [--poll-interval N] [--timeout N]
```

### 終了コード

| コード | 意味 |
|---|---|
| 0 | 成功 |
| 1 | 一般エラー（引数不正など） |
| 2 | ジョブが failed |
| 3 | wait タイムアウト |
| 4 | 認証エラー（401/403、APIキー欠落） |
| 5 | クレジット不足（402） |
| 6 | その他 4xx |
| 7 | サーバーエラー（5xx） |
| 130 | Ctrl-C |

## アーキテクチャ

軽量 Hexagonal 構成。HTTP 通信のみ `ApiClient` Protocol で抽象化されており、
テストや代替 transport で差し替え可能です。

```
__init__.py
   ↓
_client.py , cli.py        ← Client ファサード / CLI
   ↓
_http.py                   ← ApiClient Protocol + HttpApiClient
   ↓
_types.py , _errors.py     ← エンティティ / 例外
```

詳細は [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)、開発者向けは [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md)。

## ライセンス

MIT — [LICENSE](LICENSE) 参照。
