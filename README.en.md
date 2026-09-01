# sateais

[日本語](https://github.com/spaceshiftinc/sateais-py/blob/v0.2.0/README.md) | **English**

The official Python SDK and CLI for SateAIs. It provides unified programmatic and
command-line access to the SAR satellite image analysis APIs (ship detection,
oil slick detection, new / disappeared building detection, and time-series change
detection). The currently supported satellite is Sentinel-1, with additional
satellites planned in future releases.

```bash
pip install sateais
```

This package includes **both the SDK and the CLI**.

## Quickstart

```python
from sateais import Client

client = Client()                                  # credentials resolved automatically
job = client.analyze.ship(scene_id="S1A_IW_GRDH_...")
result = client.jobs.wait(job.job_id)              # synchronous polling until completion
print(len(result["features"]), "ships detected")
```

```bash
sateais login --api-key sk_live_xxxxx
sateais analyze ship --scene-id S1A_IW_GRDH_... --wait -o ships.geojson
```

To see which area would be analyzed and what it would cost before submitting, use
[Preview before submitting](#preview-before-submitting).

## Authentication

API keys can be issued from the [SateAIs Console](https://console.spcsft.com).

Resolution order: `api_key` argument > `SATEAIS_API_KEY` environment variable > `~/.sateais/credentials`

```bash
sateais login --api-key sk_live_xxxxx     # → ~/.sateais/credentials (0600)
# or
export SATEAIS_API_KEY=sk_live_xxxxx
```

## SDK

### Analysis methods

| Method | Input pattern |
|---|---|
| `client.analyze.ship(...)` | `scene_id`, or `polygon`+`date` |
| `client.analyze.oilslick(...)` | Same as above |
| `client.analyze.newbuilding(...)` | `polygon`+`date_start`+`date_end` |
| `client.analyze.disappearbuilding(...)` | Same as above |
| `client.analyze.timeseries(...)` | Same as above |

See the [API reference](https://docs.spcsft.com/) for detailed parameters.

### Preview before submitting

`client.preview.*` takes the **same arguments** as `client.analyze.*` and returns which
area would be analyzed and how many credits it would consume, without creating a job.
No credits are spent.

The polygon you specify and the area actually analyzed do not always match (scenes may
not cover the whole area), so checking beforehand lets you widen the period or split the
area instead of finding out after submission.

```python
preview = client.preview.newbuilding(
    polygon="POLYGON((139.0 35.0, 139.11 35.0, 139.11 35.09, 139.0 35.09, 139.0 35.0))",
    date_start="2025-01-01",
    date_end="2025-06-30",
)

preview.area_sqkm            # estimated analyzed area (km²)
preview.credits.estimated    # estimated cost. None means "not determinable yet", not 0
preview.credits.balance      # current balance
preview.credits.sufficient   # whether the balance covers it. None if estimated is None
preview.credits.shortfall    # missing amount. 0.0 if sufficient, None if undeterminable

if preview.coverage is not None:                 # not returned for some inputs (see below)
    preview.coverage.ratio                       # fraction of the requested area (0.0-1.0)
    preview.coverage.requested_area_sqkm         # area you requested (km²)
    preview.coverage.polygon                     # WKT of the analyzed area, reusable as input

for w in preview.warnings:                       # warnings known before submission
    print(w.code, w.message)

if preview.credits.sufficient:
    job = client.analyze.newbuilding(...)        # submit with the same arguments
```

- An insufficient balance is **not** an error here (`credits.sufficient=False`); only submission raises `InsufficientCreditsError`
- Validation other than the balance runs the same functions in the same order as submission, so **if the preview passes, submission almost always passes** (the exceptions depend on the state at submission time: the concurrency limit `429` and an insufficient balance `402`)
- The estimate comes from the requested area while billing uses the actual processed area (NoData excluded), so **actual usage never exceeds the estimate**
- `coverage` is returned for inputs that specify a `polygon` (not for `scene_id` inputs, and not when the scene search is unavailable). `None` means "cannot be determined", which is different from "100% will be analyzed" (`ratio=1.0`)
- For inputs where the billed area is not the requested polygon (e.g. `scene_id`), `credits.estimated` is `None` and `warnings` contains `CREDITS_NOT_ESTIMABLE`

### Job management

```python
job = client.jobs.status(job_id)            # fetch the current state once
geojson = client.jobs.result(job_id)        # result of a completed job
geojson = client.jobs.wait(
    job_id,
    poll_interval=10,                       # seconds
    timeout=600,                            # seconds, None for no limit
    on_poll=lambda j: print(j.status),      # progress callback
)
```

### Exceptions

| Exception | Condition |
|---|---|
| `AuthenticationError` | 401 / 403 |
| `ValidationError` | 400 |
| `InsufficientCreditsError` | 402 |
| `NotFoundError` | 404 / 410 |
| `RateLimitError` | 429 |
| `APIError` | Other HTTP errors |
| `JobFailedError` | Job failed during `wait()` |
| `JobTimeoutError` | `wait()` timed out |
| `CredentialsNotFoundError` | API key could not be resolved |
| `InvalidAnalysisRequestError` | Invalid combination of required parameters |

## CLI

```bash
sateais login [--api-key sk_...]                  # save the API key (prompts if omitted)
sateais analyze <endpoint> [options] [--wait] [-o FILE]
sateais preview <endpoint> [options] [-o FILE]    # analyzed area and cost estimate, no job
sateais jobs status <job_id>
sateais jobs result <job_id> [-o FILE]
sateais jobs wait   <job_id> [-o FILE] [--poll-interval N] [--timeout N]
sateais scene <scene_id>                          # decode a Sentinel-1 scene ID into its components
```

### Previewing before submission

`preview` takes the same parameters as `analyze` and prints the analyzed area and cost
estimate as JSON without creating a job. The exit code is 0 even when the balance is
insufficient (matching the API, which returns 200 for that case).

```bash
sateais preview newbuilding \
  --polygon "POLYGON((139.0 35.0, 139.11 35.0, 139.11 35.09, 139.0 35.09, 139.0 35.0))" \
  --date-start 2025-01-01 --date-end 2025-06-30
```

```json
{
  "endpoint_id": "newbuilding",
  "area_sqkm": 78.4,
  "coverage": {
    "method": "estimated",
    "requested_area_sqkm": 100.2,
    "ratio": 0.78,
    "polygon": "POLYGON ((139.000000 35.000000, ...))"
  },
  "credits": { "estimated": 1.0, "balance": 480.0, "sufficient": true },
  "warnings": [{ "code": "LOW_AOI_COVERAGE", "message": "Scenes cover only 78% of the requested area." }]
}
```

A `null` in `credits.estimated` means "not determinable before submission", not "free",
and a `null` `coverage` means "cannot be determined". Do not render them as 0 or 100%.

### Passing parameters as JSON

Instead of individual flags, `analyze` / `preview` parameters can be supplied together via
`--json`. When both are given, individual flags override the JSON values.

```bash
# Inline JSON string
sateais analyze ship --json '{"scene_id": "S1A_IW_GRDH_..."}'

# Read from a file (@ prefix)
sateais analyze timeseries --json @params.json

# Read from stdin (-)
cat params.json | sateais analyze newbuilding --json -

# Use JSON as a base and override individual fields with flags
sateais analyze ship --json @base.json --scene-id S1A_OTHER
```

Accepted keys: `satellite_id` / `scene_id` / `polygon` / `date` /
`date_start` / `date_end` / `date_direction` / `orbit_direction`.
Unknown keys raise an error.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | General error (e.g. invalid arguments) |
| 2 | Job failed |
| 3 | wait timed out |
| 4 | Authentication error (401/403, missing API key) |
| 5 | Insufficient credits (402) |
| 6 | Other 4xx |
| 7 | Server error (5xx) |
| 130 | Ctrl-C |

## Architecture

A lightweight Hexagonal design. Only HTTP communication is abstracted behind the
`ApiClient` Protocol, so it can be swapped out for tests or alternative transports.

```
__init__.py
   ↓
_client.py , cli.py        ← Client facade / CLI
   ↓
_http.py                   ← ApiClient Protocol + HttpApiClient
   ↓
_types.py , _errors.py     ← entities / exceptions
```

For details, see [docs/ARCHITECTURE.md](https://github.com/spaceshiftinc/sateais-py/blob/v0.2.0/docs/ARCHITECTURE.md), and [docs/CONTRIBUTING.md](https://github.com/spaceshiftinc/sateais-py/blob/v0.2.0/docs/CONTRIBUTING.md) for contributors.

## Support

For technical inquiries, please contact [console-support@spcsft.com](mailto:console-support@spcsft.com).

## License

MIT — see [LICENSE](https://github.com/spaceshiftinc/sateais-py/blob/v0.2.0/LICENSE).
