# sateais

[日本語](https://github.com/spaceshiftinc/sateais-py/blob/v0.1.0/README.md) | **English**

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
sateais jobs status <job_id>
sateais jobs result <job_id> [-o FILE]
sateais jobs wait   <job_id> [-o FILE] [--poll-interval N] [--timeout N]
```

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

For details, see [docs/ARCHITECTURE.md](https://github.com/spaceshiftinc/sateais-py/blob/v0.1.0/docs/ARCHITECTURE.md), and [docs/CONTRIBUTING.md](https://github.com/spaceshiftinc/sateais-py/blob/v0.1.0/docs/CONTRIBUTING.md) for contributors.

## Support

For technical inquiries, please contact [console-support@spcsft.com](mailto:console-support@spcsft.com).

## License

MIT — see [LICENSE](https://github.com/spaceshiftinc/sateais-py/blob/v0.1.0/LICENSE).
