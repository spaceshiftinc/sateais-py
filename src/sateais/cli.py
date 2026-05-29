"""CLI アプリケーション

argparse を使った delivery 層。`ApiClient` の差し替えだけテスト用に受け付ける。
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from typing import Any

from ._client import ENV_API_KEY, ENV_BASE_URL, Jobs
from ._credentials import load_api_key, save_api_key
from ._errors import (
    APIError,
    CredentialsNotFoundError,
    JobFailedError,
    JobTimeoutError,
    SateAIsError,
)
from ._http import DEFAULT_API_BASE_URL, ApiClient, HttpApiClient
from ._types import DetectionRequest, DetectionType, Job
from ._version import __version__

DETECT_ENDPOINTS: tuple[DetectionType, ...] = (
    DetectionType.SHIP,
    DetectionType.OILSLICK,
    DetectionType.NEWBUILDING,
    DetectionType.DISAPPEARBUILDING,
    DetectionType.TIMESERIES,
)


def main(argv: list[str] | None = None, *, api: ApiClient | None = None) -> int:
    """CLI エントリポイント

    Args:
        argv: コマンドライン引数（テスト時に指定）
        api: ApiClient の差し替え（テスト時に指定）

    Returns:
        プロセス終了コード
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        return args.func(args, api=api)  # type: ignore[no-any-return]
    except APIError as e:
        _eprint(f"API error: {e}")
        return _exit_code_for_status(e.status_code)
    except JobFailedError as e:
        _eprint(str(e))
        return 2
    except JobTimeoutError as e:
        _eprint(str(e))
        return 3
    except CredentialsNotFoundError as e:
        _eprint(f"Error: {e}")
        return 4
    except (SateAIsError, ValueError) as e:
        _eprint(f"Error: {e}")
        return 1
    except KeyboardInterrupt:
        _eprint("Interrupted.")
        return 130


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sateais",
        description="SateAIs CLI - Satellite image analysis",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True, metavar="<command>")

    _add_login(sub)
    _add_detect(sub)
    _add_jobs(sub)
    return p


def _add_login(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("login", help="Save API key to ~/.sateais/credentials")
    p.add_argument("--api-key", "-k", help="API key (omit to prompt interactively)")
    p.set_defaults(func=_cmd_login)


def _add_detect(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("detect", help="Submit a new detection job")
    detect_sub = p.add_subparsers(dest="detect_type", required=True, metavar="<detection_type>")
    for dt in DETECT_ENDPOINTS:
        sp = detect_sub.add_parser(dt.value, help=f"Submit a {dt.value} detection")

        if dt.accepts_scene_or_polygon_date:
            # ship / oilslick: scene_id か polygon+date のどちらか
            sp.add_argument("--scene-id", help="Scene ID to analyze")
            sp.add_argument("--polygon", help="WKT polygon (EPSG:4326)")
            sp.add_argument(
                "--date", help="Reference date YYYY-MM-DD (required if --polygon is used)"
            )
            sp.add_argument(
                "--date-direction",
                choices=["before", "after", "nearest"],
                help="Direction for date range filtering",
            )
            sp.add_argument(
                "--orbit-direction",
                choices=["ascending", "descending"],
                help="Orbit direction for the scene",
            )
        elif dt.requires_date_range:
            # newbuilding / disappearbuilding / timeseries: polygon + date_start + date_end が必須
            # 必須チェックは DetectionRequest.validate() に集約する
            sp.add_argument("--polygon", help="WKT polygon (EPSG:4326)")
            sp.add_argument("--date-start", help="Start date YYYY-MM-DD")
            sp.add_argument("--date-end", help="End date YYYY-MM-DD")

        sp.add_argument(
            "--satellite-id",
            default="sentinel-1",
            help="Satellite ID. Currently 'sentinel-1' is the only supported value (default).",
        )
        sp.add_argument(
            "--wait",
            action="store_true",
            help="Block until job completes, then output result GeoJSON",
        )
        sp.add_argument(
            "--poll-interval",
            type=float,
            default=10.0,
            help="Polling interval in seconds (default: 10)",
        )
        sp.add_argument(
            "--timeout",
            type=float,
            default=None,
            help="Wait timeout in seconds (default: no timeout)",
        )
        sp.add_argument("-o", "--output", help="Write output to file instead of stdout")
        sp.set_defaults(func=_cmd_detect, detection_type=dt)


def _add_jobs(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("jobs", help="Manage jobs")
    jobs_sub = p.add_subparsers(dest="action", required=True, metavar="<action>")

    sp = jobs_sub.add_parser("status", help="Check job status")
    sp.add_argument("job_id")
    sp.add_argument("-o", "--output", help="Write output to file instead of stdout")
    sp.set_defaults(func=_cmd_jobs_status)

    sp = jobs_sub.add_parser("result", help="Download result GeoJSON")
    sp.add_argument("job_id")
    sp.add_argument("-o", "--output", help="Write output to file instead of stdout")
    sp.set_defaults(func=_cmd_jobs_result)

    sp = jobs_sub.add_parser("wait", help="Wait for job completion and download result")
    sp.add_argument("job_id")
    sp.add_argument("--poll-interval", type=float, default=10.0)
    sp.add_argument("--timeout", type=float, default=None)
    sp.add_argument("-o", "--output", help="Write output to file instead of stdout")
    sp.set_defaults(func=_cmd_jobs_wait)


def _cmd_login(args: argparse.Namespace, api: ApiClient) -> int:
    del api  # 使わない
    api_key = args.api_key or getpass.getpass("Enter API key: ")
    path = save_api_key(api_key)
    _eprint(f"API key saved to {path}")
    return 0


def _cmd_detect(args: argparse.Namespace, api: ApiClient | None = None) -> int:
    with _open_api(api) as api_client:
        # 検出種別ごとに対応する引数が異なるため、未追加の属性は getattr で吸収する
        request = DetectionRequest(
            detection_type=args.detection_type,
            satellite_id=args.satellite_id,
            polygon=getattr(args, "polygon", None),
            scene_id=getattr(args, "scene_id", None),
            date=getattr(args, "date", None),
            date_start=getattr(args, "date_start", None),
            date_end=getattr(args, "date_end", None),
            date_direction=getattr(args, "date_direction", None),
            orbit_direction=getattr(args, "orbit_direction", None),
        )

        request.validate()
        job = api_client.submit_detection(request)

        if args.wait:
            result = Jobs(api_client).wait(
                job.job_id,
                poll_interval=args.poll_interval,
                timeout=args.timeout,
                on_poll=_process_callback(),
            )
            _output_json(result, args.output)
        else:
            _output_json(_job_to_dict(job), args.output)
    return 0


def _cmd_jobs_status(args: argparse.Namespace, api: ApiClient | None = None) -> int:
    with _open_api(api) as api_client:
        job = Jobs(api_client).status(args.job_id)
        _output_json(_job_to_dict(job), args.output)
    return 0


def _cmd_jobs_result(args: argparse.Namespace, api: ApiClient | None = None) -> int:
    with _open_api(api) as api_client:
        result = Jobs(api_client).result(args.job_id)
        _output_json(result, args.output)
    return 0


def _cmd_jobs_wait(args: argparse.Namespace, api: ApiClient | None = None) -> int:
    with _open_api(api) as api_client:
        result = Jobs(api_client).wait(
            args.job_id,
            poll_interval=args.poll_interval,
            timeout=args.timeout,
            on_poll=_process_callback(),
        )
        _output_json(result, args.output)
    return 0


class _ApiClientContext:
    """ApiClient のクローズを保証する context manager"""

    def __init__(self, client: ApiClient, owns: bool) -> None:
        self.client = client
        self.owns = owns

    def __enter__(self) -> ApiClient:
        return self.client

    def __exit__(self, *ext_info: Any) -> None:
        if self.owns:
            self.client.close()


def _open_api(injected: ApiClient | None = None) -> _ApiClientContext:
    """CLI コマンドのための composition root

    注入された ApiClient があればそれを使い、なければ環境変数 / 認証ファイルから
    APIキーを解決して HttpApiClient を生成する。
    """
    if injected is not None:
        return _ApiClientContext(injected, owns=False)

    api_key = os.environ.get(ENV_API_KEY) or load_api_key()
    if not api_key:
        raise CredentialsNotFoundError(
            "API key not found. Set SATEAIS_API_KEY env var or run `sateais login`."
        )
    base_url = os.environ.get(ENV_BASE_URL) or DEFAULT_API_BASE_URL
    return _ApiClientContext(HttpApiClient(api_key=api_key, base_url=base_url), owns=True)


def _job_to_dict(job: Job) -> dict[str, Any]:
    """Job オブジェクトを JSON シリアライズ可能な dict に変換する"""
    fields = {
        "job_id": job.job_id,
        "status": job.status.value,
        "created_at": job.created_at,
        "completed_at": job.completed_at,
        "result_path": job.result_path,
        "error_code": job.error_code,
        "error_message": job.error_message,
    }
    return {k: v for k, v in fields.items() if v is not None}


def _output_json(data: dict[str, Any], output_path: str | None) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(text)
            f.write("\n")
        _eprint(f"Wrote {output_path}")
    else:
        sys.stdout.write(text + "\n")


def _process_callback() -> Any:
    """wait 中の進捗を stderr に出すコールバック（同じ status は重複表示しない）"""
    last: dict[str, str] = {}

    def _cb(job: Job) -> None:
        if last.get("status") != job.status.value:
            _eprint(f"[{job.job_id}] status={job.status.value}")
            last["status"] = job.status.value

    return _cb


def _exit_code_for_status(status_code: int) -> int:
    if status_code in (401, 403):
        return 4
    elif status_code == 402:
        return 5
    elif 400 <= status_code < 500:
        return 6
    return 7


def _eprint(msg: str) -> None:
    print(msg, file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
