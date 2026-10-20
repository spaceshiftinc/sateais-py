# sateais

**日本語** | [English](https://github.com/spaceshiftinc/sateais-py/blob/v0.2.0/README.en.md)

SateAIs の公式 Python SDK および CLI です。SAR 衛星画像の解析 API
（船舶検出 / オイルスリック検出 / 新規・消失建物検出 / 時系列変化検出）と、
Sentinel-2 を併用した土地利用・土地被覆分類（LULC）に、
プログラムおよびコマンドラインから統一的にアクセスできます。

```bash
pip install sateais
```

本パッケージには、**SDK と CLI の両方** が含まれます。

## クイックスタート

```python
from sateais import Client

client = Client()                                  # 認証は自動解決
job = client.analyze.ship(scene_id="S1A_IW_GRDH_...")
result = client.jobs.wait(job.job_id)              # 完了まで同期 polling
print(len(result["features"]), "ships detected")
```

```bash
sateais login --api-key sk_live_xxxxx
sateais analyze ship --scene-id S1A_IW_GRDH_... --wait -o ships.geojson
```

投入前に「どの範囲が解析され、いくら消費するか」を確認したい場合は
[投入前プレビュー](#投入前プレビュー) を使います。

## 認証

API キーは [SateAIs コンソール](https://console.spcsft.com) で発行できます。

優先度: `api_key` 引数 > 環境変数 `SATEAIS_API_KEY` > `~/.sateais/credentials`

```bash
sateais login --api-key sk_live_xxxxx     # → ~/.sateais/credentials (0600)
# または
export SATEAIS_API_KEY=sk_live_xxxxx
```

## SDK

### 解析メソッド

| メソッド | 入力パターン |
|---|---|
| `client.analyze.ship(...)` | `scene_id` または `polygon`+`date` |
| `client.analyze.oilslick(...)` | 同上 |
| `client.analyze.newbuilding(...)` | `polygon`+`date_start`+`date_end` |
| `client.analyze.disappearbuilding(...)` | 同上 |
| `client.analyze.timeseries(...)` | 同上 |
| `client.analyze.lulc(...)` | `polygon`+`month`（結果は zip アーカイブ） |

詳細パラメータは [API リファレンス](https://docs.spcsft.com/) 参照。

### 投入前プレビュー

`client.preview.*` は `client.analyze.*` と**同じ引数**を取り、ジョブを作らずに
「どの範囲が解析されるか」と「消費見込み」を返します。クレジットは消費しません。

指定した polygon と実際に解析される範囲は一致しない（シーンが範囲全体を覆わない等）ため、
投入前に確認すると期間を広げる・範囲を分割するといった判断ができます。

```python
preview = client.preview.newbuilding(
    polygon="POLYGON((139.0 35.0, 139.11 35.0, 139.11 35.09, 139.0 35.09, 139.0 35.0))",
    date_start="2025-01-01",
    date_end="2025-06-30",
)

preview.area_sqkm            # 解析される見込みの面積 (km²)
preview.credits.estimated    # 消費見込み。None は「投入前には確定しない」（0 ではない）
preview.credits.balance      # 現在の残高
preview.credits.sufficient   # 残高で足りるか。estimated が None なら None
preview.credits.shortfall    # 不足額。足りていれば 0.0、判定できなければ None

if preview.coverage is not None:                 # 返らない入力もある（下記）
    preview.coverage.ratio                       # 指定範囲のうち解析される割合 (0.0〜1.0)
    preview.coverage.requested_area_sqkm         # 指定した範囲の面積 (km²)
    preview.coverage.polygon                     # 解析される範囲の WKT。再投入にそのまま使える

for w in preview.warnings:                       # 投入前に分かる警告
    print(w.code, w.message)

if preview.credits.sufficient:
    job = client.analyze.newbuilding(...)        # 同じ引数でそのまま投入
```

- 残高不足でも例外にはなりません（`credits.sufficient=False` で返る）。`InsufficientCreditsError` になるのは投入時だけです
- 残高以外の検証は投入と同じ関数を同じ順で通るため、**プレビューが通れば投入もほぼ通ります**（投入時点の状況で決まる同時実行数の上限 `429` と残高不足 `402` だけは別）
- 見積もりは指定範囲の面積から算出し、実際の課金は NoData を除いた実処理面積で決まるため、**実消費が見積もりを上回ることはありません**
- `coverage` は `polygon` を指定した入力で返ります（`scene_id` 指定や、シーン検索ができなかった場合は返りません）。`None` は「判定できない」という意味で、「100% 解析される」（`ratio=1.0`）とは区別されます
- `scene_id` 指定のように課金対象が指定範囲で決まらない入力では `credits.estimated` が `None` になり、`warnings` に `CREDITS_NOT_ESTIMABLE` が入ります

### 土地利用・土地被覆（LULC）

Sentinel-2 と Sentinel-1 の 1 年分の画像から、10 m 画素ごとに 15 クラスへ分類します。
結果は GeoJSON ではなく zip アーカイブ（`classes.tif` / `class_stats.json` /
`legend.json` / `visual.png`）なので、`jobs.wait_archive()` / `jobs.result_archive()` で
バイト列として受け取ります。

```python
from pathlib import Path

polygon = "POLYGON((136.27 36.23, 136.37 36.23, 136.37 36.33, 136.27 36.33, 136.27 36.23))"
preview = client.preview.lulc(polygon=polygon, month="2026-08")   # 外接矩形の面積で見積もり
job = client.analyze.lulc(polygon=polygon, month="2026-08")       # 2025-09〜2026-08 を解析
Path("lulc.zip").write_bytes(client.jobs.wait_archive(job.job_id))
```

- `month` は解析期間 12 ヶ月の最終月（`YYYY-MM`）。**偶数月のみ**・2018-02 以降・経過済みの月
- polygon の**外接矩形全体**が解析・課金されます（外接矩形の面積は 0.5〜350 km²）。矩形に近い形で指定してください
- `satellite_id` は `"sentinel-2"` 固定です（既定値。内部では Sentinel-1 も使いますが、権限は Sentinel-2 で判定されます）
- `scene_id` / `date*` / `orbit_direction` は指定できません
- 結果が zip のジョブに `jobs.wait()` を使うと、`SateAIsError` で `wait_archive()` を案内します

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
data = client.jobs.result_archive(job_id)   # 結果が zip のジョブ（lulc）は bytes で取得
data = client.jobs.wait_archive(job_id)     # 同上を完了まで待って取得（引数は wait と同じ）
job.result_is_archive                       # 結果が zip か（completed のときだけ判定できる）
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
| `UnknownJobStatusError` | `wait()` 中に未知ステータスが連続 |
| `CredentialsNotFoundError` | APIキーが解決できない |
| `InvalidAnalysisRequestError` | 必須パラメータの組合せ不正 |

## CLI

```bash
sateais login [--api-key sk_...]                  # APIキーを保存（省略時はプロンプト）
sateais analyze <endpoint> [options] [--wait] [-o FILE]
sateais preview <endpoint> [options] [-o FILE]     # 投入せず解析範囲と消費見込みを表示
sateais jobs status <job_id>
sateais jobs result <job_id> [-o FILE]           # zip のジョブ（lulc）は -o 必須
sateais jobs wait   <job_id> [-o FILE] [--poll-interval N] [--timeout N]
sateais scene <scene_id>                          # Sentinel-1 シーンIDを構成要素にデコード
```

### 投入前にプレビューする

`preview` は `analyze` と同じパラメータを取り、ジョブを作らずに解析範囲と消費見込みを
JSON で返します。残高不足でも終了コードは 0 です（API 側が 200 を返す仕様に合わせています）。

```bash
sateais preview newbuilding \
  --polygon "POLYGON((139.0 35.0, 139.11 35.0, 139.11 35.09, 139.0 35.09, 139.0 35.0))" \
  --date-start 2025-01-01 --date-end 2025-06-30
```

```json
{
  "endpoint_id": "newbuilding",
  "credits": { "estimated": 1.0, "balance": 480.0, "sufficient": true },
  "area_sqkm": 78.4,
  "coverage": {
    "method": "estimated",
    "requested_area_sqkm": 100.2,
    "ratio": 0.78,
    "polygon": "POLYGON ((139.000000 35.000000, ...))"
  },
  "warnings": [{ "code": "LOW_AOI_COVERAGE", "message": "Scenes cover only 78% of the requested area." }]
}
```

`credits.estimated` の `null` は「かからない」ではなく「投入前には確定しない」、
`coverage` の `null` は「判定できない」を表します。0 や 100% として扱わないでください。

### 土地利用・土地被覆（LULC）

結果は zip アーカイブなので、`--wait` / `jobs result` / `jobs wait` では `-o FILE` が必須です。
`analyze lulc --wait` で `-o` を忘れた場合は、クレジットを消費する投入の前にエラーになります。

```bash
sateais preview lulc --polygon "POLYGON((...))" --month 2026-08
sateais analyze lulc --polygon "POLYGON((...))" --month 2026-08 --wait -o lulc.zip
```

### パラメータを JSON でまとめて渡す

`analyze` / `preview` の解析パラメータは個別フラグの代わりに `--json` でまとめて指定できます。
個別フラグを併用した場合は、フラグ側の値が JSON の値を上書きします。

```bash
# JSON 文字列で指定
sateais analyze ship --json '{"scene_id": "S1A_IW_GRDH_..."}'

# ファイルから読み込む（@ プレフィクス）
sateais analyze timeseries --json @params.json

# 標準入力から読み込む（-）
cat params.json | sateais analyze newbuilding --json -

# JSON をベースに一部だけフラグで上書き
sateais analyze ship --json @base.json --scene-id S1A_OTHER
```

JSON に指定できるキー: `satellite_id` / `scene_id` / `polygon` / `date` /
`date_start` / `date_end` / `date_direction` / `orbit_direction` / `month`。
未知のキーはエラーになります。

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

詳細は [docs/ARCHITECTURE.md](https://github.com/spaceshiftinc/sateais-py/blob/v0.2.0/docs/ARCHITECTURE.md)、開発者向けは [docs/CONTRIBUTING.md](https://github.com/spaceshiftinc/sateais-py/blob/v0.2.0/docs/CONTRIBUTING.md)。

## サポート

技術的なお問い合わせは [console-support@spcsft.com](mailto:console-support@spcsft.com) までご連絡ください。

## ライセンス

MIT — [LICENSE](https://github.com/spaceshiftinc/sateais-py/blob/v0.2.0/LICENSE) 参照。
