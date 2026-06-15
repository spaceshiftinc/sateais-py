"""CLI アプリケーション

argparse を使った delivery 層。`ApiClient` の差し替えだけテスト用に受け付ける。
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import sys
import time
from typing import Any

from ._client import ENV_API_KEY, ENV_BASE_URL, Jobs, PollCallback
from ._credentials import load_api_key, save_api_key
from ._errors import (
    APIError,
    CredentialsNotFoundError,
    JobFailedError,
    JobTimeoutError,
    SateAIsError,
)
from ._fun import (
    AURORA_STILL,
    NIGHTSKY_STILL,
    ORBIT_STILL,
    PING_STILL,
    decode_duration,
    format_scene_info,
    make_aurora_render,
    make_decode_render,
    make_nightsky_render,
    parse_scene_id,
    render_orbit,
    render_ping,
    supports_truecolor,
)
from ._http import DEFAULT_API_BASE_URL, ApiClient, HttpApiClient
from ._spinner import RenderFn, SatelliteSpinner
from ._types import AnalysisRequest, AnalysisType, Job
from ._version import __version__

ANALYZE_ENDPOINTS: tuple[AnalysisType, ...] = (
    AnalysisType.SHIP,
    AnalysisType.OILSLICK,
    AnalysisType.NEWBUILDING,
    AnalysisType.DISAPPEARBUILDING,
    AnalysisType.TIMESERIES,
)

# スペースシフトの MVV（Mission / Vision / Value）。`sateais mvv` で表示する。
_MVV_TEXT = """
SateAIs — Spaceshift Inc.

【 Mission 】
  衛星データ×AIで
  見えないものを可視化する

【 Vision 】
  宇宙からの視点を日常につなぎ
  人と地球とテクノロジーの共生へ

【 Value 】
  ・誠意を貫く
  ・失敗を恐れず挑戦を楽しむ
  ・大胆に変化する
  ・未来から逆算する
  ・新しい価値を共創する
""".strip()

# `sateais motomura` で歩くアヒル。waddle しながら右へ移動する CLI アニメーション。
_MOTOMURA_ART = "   ,~.\n _(o )>\n \\__/\n  ||"

_MOTOMURA_LEGS = ("/\\", "\\/")  # waddle（よちよち歩き）の脚 2 フレーム
_MOTOMURA_WIDTH = 8  # アヒル 1 体の概ねの幅（折り返し計算用）
_MOTOMURA_STEP = 2  # 何フレームに 1 マス進むか
_MOTOMURA_BLINK_LOOP = 24  # まばたきの周期（フレーム）

# --json でまとめて指定できる解析パラメータのキー
_PARAM_KEYS: tuple[str, ...] = (
    "satellite_id",
    "scene_id",
    "polygon",
    "date",
    "date_start",
    "date_end",
    "date_direction",
    "orbit_direction",
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
    _add_analyze(sub)
    _add_jobs(sub)
    _add_mvv(sub)
    _add_hidden(sub)
    return p


def _add_login(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("login", help="Save API key to ~/.sateais/credentials")
    p.add_argument("--api-key", "-k", help="API key (omit to prompt interactively)")
    p.set_defaults(func=_cmd_login)


def _add_analyze(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("analyze", help="Submit a new analysis job")
    analyze_sub = p.add_subparsers(dest="analyze_type", required=True, metavar="<analysis_type>")
    for dt in ANALYZE_ENDPOINTS:
        sp = analyze_sub.add_parser(dt.value, help=f"Submit a {dt.value} analysis")

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
            # 必須チェックは AnalysisRequest.validate() に集約する
            sp.add_argument("--polygon", help="WKT polygon (EPSG:4326)")
            sp.add_argument("--date-start", help="Start date YYYY-MM-DD")
            sp.add_argument("--date-end", help="End date YYYY-MM-DD")

        sp.add_argument(
            "--json",
            dest="json_params",
            metavar="JSON",
            help=(
                "Analysis parameters as a JSON object string, '@FILE' to read a file, "
                "or '-' for stdin. Individual flags override JSON values."
            ),
        )
        sp.add_argument(
            "--satellite-id",
            default=None,
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
        # 隠しフラグ: 待機スピナーをアヒルに差し替える
        sp.add_argument("--ducky", action="store_true", help=argparse.SUPPRESS)
        sp.set_defaults(func=_cmd_analyze, analysis_type=dt)


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
    sp.add_argument("--ducky", action="store_true", help=argparse.SUPPRESS)
    sp.set_defaults(func=_cmd_jobs_wait)


def _add_mvv(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("mvv", help="Show Spaceshift's Mission / Vision / Value")
    p.set_defaults(func=_cmd_mvv)


def _cmd_mvv(args: argparse.Namespace, api: ApiClient | None = None) -> int:
    del args, api  # 使わない（API キー不要）
    sys.stdout.write(_MVV_TEXT + "\n")
    return 0


def _add_hidden(sub: argparse._SubParsersAction) -> None:
    """遊び心のある隠しコマンドを登録する

    help を渡さないことで `sateais --help` の一覧には出さない（隠し要素）。
    metavar="<command>" によりサブコマンド候補も usage に列挙されない。
    """
    # 待機演出を流用したアニメーション系（共通で --duration を持つ）
    animations = {
        "motomura": _cmd_motomura,
        "orbit": _cmd_orbit,
        "ping": _cmd_ping,
        "aurora": _cmd_aurora,
        "nightsky": _cmd_nightsky,
    }
    for name, fn in animations.items():
        p = sub.add_parser(name)
        p.add_argument("--duration", type=float, default=6.0, help=argparse.SUPPRESS)
        p.set_defaults(func=fn)

    # decode: 任意のテキストをダウンリンク風に復元
    p = sub.add_parser("decode")
    p.add_argument("text", nargs="*", help=argparse.SUPPRESS)
    p.add_argument("--duration", type=float, default=None, help=argparse.SUPPRESS)
    p.set_defaults(func=_cmd_decode)

    # scene: Sentinel-1 シーンIDをデコード（地味に実用）
    p = sub.add_parser("scene")
    p.add_argument("scene_id")
    p.set_defaults(func=_cmd_scene)


def _render_motomura(frame: int, status: str) -> list[str]:
    """フレーム番号からアヒルの 4 行を描画する（SatelliteSpinner の RenderFn）

    アヒルは右へ歩き、端に達したら左へ折り返す。脚は 1 マス進むごとに
    `/\\` と `\\/` を交互に切り替えて waddle を表現し、たまにまばたきする。
    """
    del status  # ステータス表示は使わない
    width = shutil.get_terminal_size(fallback=(80, 24)).columns
    travel = max(1, width - _MOTOMURA_WIDTH)
    step = frame // _MOTOMURA_STEP
    pad = " " * (step % travel)
    legs = _MOTOMURA_LEGS[step % len(_MOTOMURA_LEGS)]
    eye = "-" if frame % _MOTOMURA_BLINK_LOOP < 2 else "o"
    return [
        f"{pad}   ,~.",
        f"{pad} _({eye} )>",
        f"{pad} \\__/",
        f"{pad}  {legs}",
    ]


def _play_animation(render: RenderFn, *, duration: float, still: str) -> int:
    """TTY ではアニメーションを duration 秒再生し、非 TTY では静止画を 1 回出す"""
    with SatelliteSpinner(stream=sys.stdout, render=render) as spinner:
        if spinner.enabled:
            time.sleep(duration)
        else:
            sys.stdout.write(still + "\n")
    return 0


def _cmd_motomura(args: argparse.Namespace, api: ApiClient | None = None) -> int:
    del api  # 使わない（API キー不要）
    return _play_animation(_render_motomura, duration=args.duration, still=_MOTOMURA_ART)


def _cmd_orbit(args: argparse.Namespace, api: ApiClient | None = None) -> int:
    del api
    return _play_animation(render_orbit, duration=args.duration, still=ORBIT_STILL)


def _cmd_ping(args: argparse.Namespace, api: ApiClient | None = None) -> int:
    del api
    return _play_animation(render_ping, duration=args.duration, still=PING_STILL)


def _cmd_aurora(args: argparse.Namespace, api: ApiClient | None = None) -> int:
    del api
    render = make_aurora_render(supports_truecolor())
    return _play_animation(render, duration=args.duration, still=AURORA_STILL)


def _cmd_nightsky(args: argparse.Namespace, api: ApiClient | None = None) -> int:
    del api
    render = make_nightsky_render(supports_truecolor())
    return _play_animation(render, duration=args.duration, still=NIGHTSKY_STILL)


def _cmd_decode(args: argparse.Namespace, api: ApiClient | None = None) -> int:
    del api
    text = " ".join(args.text) if args.text else "SATEAIS // SIGNAL ACQUIRED"
    duration = args.duration if args.duration is not None else decode_duration(text)
    return _play_animation(make_decode_render(text), duration=duration, still=text)


def _cmd_scene(args: argparse.Namespace, api: ApiClient | None = None) -> int:
    del api  # 使わない（API キー不要・ローカルでデコードするだけ）
    info = parse_scene_id(args.scene_id)
    sys.stdout.write(format_scene_info(args.scene_id, info) + "\n")
    return 0


def _cmd_login(args: argparse.Namespace, api: ApiClient) -> int:
    del api  # 使わない
    api_key = args.api_key or getpass.getpass("Enter API key: ")
    path = save_api_key(api_key)
    _eprint(f"API key saved to {path}")
    return 0


def _build_analysis_request(args: argparse.Namespace) -> AnalysisRequest:
    """CLI 引数（--json + 個別フラグ）から AnalysisRequest を組み立てる

    --json で渡した JSON オブジェクトをベースに、明示指定された個別フラグで上書きする。
    解析種別ごとに対応する引数が異なるため、未追加の属性は getattr で吸収する。
    """
    params = _load_json_params(getattr(args, "json_params", None))

    # 明示指定された個別フラグ（None でない）で JSON 値を上書きする
    for key in _PARAM_KEYS:
        value = getattr(args, key, None)
        if value is not None:
            params[key] = value

    return AnalysisRequest(
        analysis_type=args.analysis_type,
        satellite_id=params.get("satellite_id") or "sentinel-1",
        scene_id=params.get("scene_id"),
        polygon=params.get("polygon"),
        date=params.get("date"),
        date_start=params.get("date_start"),
        date_end=params.get("date_end"),
        date_direction=params.get("date_direction"),
        orbit_direction=params.get("orbit_direction"),
    )


def _load_json_params(raw: str | None) -> dict[str, Any]:
    """--json の値を読み込んで解析パラメータの dict に変換する

    raw が None なら空 dict を返す。'@PATH' でファイル読込、'-' で標準入力、
    それ以外は JSON 文字列そのものとして解釈する。

    Raises:
        ValueError: JSON が不正、オブジェクトでない、または未知のキーを含む場合
    """
    if raw is None:
        return {}

    if raw == "-":
        text = sys.stdin.read()
    elif raw.startswith("@"):
        with open(raw[1:], encoding="utf-8") as f:
            text = f.read()
    else:
        text = raw

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"--json: invalid JSON: {e}") from e

    if not isinstance(data, dict):
        raise ValueError("--json: must be a JSON object")

    unknown = set(data) - set(_PARAM_KEYS)
    if unknown:
        raise ValueError(f"--json: unknown keys: {', '.join(sorted(unknown))}")

    return data


def _cmd_analyze(args: argparse.Namespace, api: ApiClient | None = None) -> int:
    with _open_api(api) as api_client:
        request = _build_analysis_request(args)
        request.validate()
        job = api_client.submit_analysis(request)

        if args.wait:
            result = _wait_for_job(
                Jobs(api_client),
                job.job_id,
                poll_interval=args.poll_interval,
                timeout=args.timeout,
                ducky=args.ducky,
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
        result = _wait_for_job(
            Jobs(api_client),
            args.job_id,
            poll_interval=args.poll_interval,
            timeout=args.timeout,
            ducky=args.ducky,
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


def _wait_for_job(
    jobs: Jobs,
    job_id: str,
    *,
    poll_interval: float,
    timeout: float | None,
    ducky: bool = False,
) -> dict[str, Any]:
    """ジョブ完了を待ち、結果 GeoJSON を返す

    対話端末（stderr が TTY）では衛星スキャンのアスキーアニメーションを表示し、
    パイプ/リダイレクト/テスト時は変化時のみ 1 行の進捗ログにフォールバックする。
    隠しフラグ ``--ducky`` 指定時はスピナーを歩くアヒルに差し替える。
    """
    render: RenderFn | None = _render_motomura if ducky else None
    with SatelliteSpinner(render=render) as spinner:
        on_poll = _spinner_callback(spinner) if spinner.enabled else _process_callback()
        return jobs.wait(
            job_id,
            poll_interval=poll_interval,
            timeout=timeout,
            on_poll=on_poll,
        )


def _spinner_callback(spinner: SatelliteSpinner) -> PollCallback:
    """ポーリングごとにスピナーの表示ステータスを更新するコールバック"""

    def _cb(job: Job) -> None:
        spinner.set_status(job.status.value)

    return _cb


def _process_callback() -> PollCallback:
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
