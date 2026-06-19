"""CLI のテスト

main() に FakeApiClient を注入し、認証ファイルアクセスは monkeypatch で抑止する。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from sateais import JobStatus
from sateais.cli import main
from tests.conftest import FakeApiClient, make_job


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SATEAIS_API_KEY", raising=False)
    monkeypatch.delenv("SATEAIS_BASE_URL", raising=False)
    monkeypatch.setattr("sateais.cli.load_api_key", lambda: "sk_test")
    monkeypatch.setattr(time, "sleep", lambda _s: None)


def test_login_writes_to_credentials_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    creds = tmp_path / "credentials"
    saved: dict = {}

    def fake_save(key: str) -> Path:
        creds.write_text(f'{{"api_key": "{key}"}}')
        saved["key"] = key
        return creds

    monkeypatch.setattr("sateais.cli.save_api_key", fake_save)
    rc = main(["login", "--api-key", "sk_abc"])
    assert rc == 0
    assert saved["key"] == "sk_abc"


def test_analyze_outputs_job_json(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeApiClient(next_job=make_job(status=JobStatus.PENDING))
    rc = main(["analyze", "ship", "--scene-id", "S1A_X"], api=api)
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["job_id"] == "j-1"
    assert out["status"] == "pending"
    assert api.submitted[0].scene_id == "S1A_X"


def test_analyze_with_wait_outputs_geojson(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeApiClient(
        next_job=make_job(status=JobStatus.PENDING),
        job_sequence=[make_job(status=JobStatus.COMPLETED)],
        result={"type": "FeatureCollection", "features": []},
    )
    rc = main(
        ["analyze", "ship", "--scene-id", "S1A_X", "--wait", "--poll-interval", "0"],
        api=api,
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["type"] == "FeatureCollection"


def test_analyze_with_json_params(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeApiClient(next_job=make_job(status=JobStatus.PENDING))
    rc = main(
        [
            "analyze",
            "newbuilding",
            "--json",
            '{"polygon": "POLYGON((0 0,1 0,1 1,0 0))", '
            '"date_start": "2024-01-01", "date_end": "2024-02-01"}',
        ],
        api=api,
    )
    assert rc == 0
    req = api.submitted[0]
    assert req.polygon == "POLYGON((0 0,1 0,1 1,0 0))"
    assert req.date_start == "2024-01-01"
    assert req.date_end == "2024-02-01"


def test_analyze_flag_overrides_json(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeApiClient(next_job=make_job(status=JobStatus.PENDING))
    rc = main(
        [
            "analyze",
            "ship",
            "--json",
            '{"scene_id": "S1A_FROM_JSON"}',
            "--scene-id",
            "S1A_FROM_FLAG",
        ],
        api=api,
    )
    assert rc == 0
    assert api.submitted[0].scene_id == "S1A_FROM_FLAG"


def test_analyze_json_from_file(tmp_path: Path) -> None:
    api = FakeApiClient(next_job=make_job(status=JobStatus.PENDING))
    params = tmp_path / "params.json"
    params.write_text('{"scene_id": "S1A_FILE"}')
    rc = main(["analyze", "ship", "--json", f"@{params}"], api=api)
    assert rc == 0
    assert api.submitted[0].scene_id == "S1A_FILE"


def test_analyze_json_from_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    import io

    api = FakeApiClient(next_job=make_job(status=JobStatus.PENDING))
    monkeypatch.setattr("sys.stdin", io.StringIO('{"scene_id": "S1A_STDIN"}'))
    rc = main(["analyze", "ship", "--json", "-"], api=api)
    assert rc == 0
    assert api.submitted[0].scene_id == "S1A_STDIN"


def test_analyze_json_invalid_returns_error(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeApiClient(next_job=make_job())
    rc = main(["analyze", "ship", "--json", "{not json}"], api=api)
    assert rc == 1
    assert "invalid JSON" in capsys.readouterr().err


def test_analyze_json_unknown_key_returns_error(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeApiClient(next_job=make_job())
    rc = main(["analyze", "ship", "--json", '{"scene_id": "S1A_X", "bogus": 1}'], api=api)
    assert rc == 1
    assert "unknown keys: bogus" in capsys.readouterr().err


def test_analyze_json_not_object_returns_error(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeApiClient(next_job=make_job())
    rc = main(["analyze", "ship", "--json", "[1, 2]"], api=api)
    assert rc == 1
    assert "must be a JSON object" in capsys.readouterr().err


def test_analyze_json_missing_file_returns_error(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    # 存在しない @FILE はトレースバックではなくクリーンなエラーになる
    api = FakeApiClient(next_job=make_job())
    missing = tmp_path / "nope.json"
    rc = main(["analyze", "ship", "--json", f"@{missing}"], api=api)
    assert rc == 1
    assert "cannot read file" in capsys.readouterr().err


def test_exit_code_for_network_failure_is_general_error() -> None:
    from sateais.cli import _exit_code_for_status

    # HTTP ステータスを持たない通信失敗（status_code=0）は一般エラー(1)
    assert _exit_code_for_status(0) == 1
    assert _exit_code_for_status(401) == 4
    assert _exit_code_for_status(402) == 5
    assert _exit_code_for_status(404) == 6
    assert _exit_code_for_status(503) == 7


def test_jobs_status(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeApiClient(next_job=make_job(status=JobStatus.COMPLETED))
    rc = main(["jobs", "status", "j-1"], api=api)
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "completed"


def test_jobs_result_to_file(tmp_path: Path) -> None:
    api = FakeApiClient(result={"type": "FeatureCollection", "features": [{"x": 1}]})
    out_file = tmp_path / "out.geojson"
    rc = main(["jobs", "result", "j-1", "-o", str(out_file)], api=api)
    assert rc == 0
    assert json.loads(out_file.read_text())["features"] == [{"x": 1}]


def test_no_credentials_returns_exit_code_4(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sateais.cli.load_api_key", lambda: None)
    rc = main(["jobs", "status", "j-1"])
    assert rc == 4
    assert "API key not found" in capsys.readouterr().err


def test_invalid_analysis_request_returns_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    api = FakeApiClient(next_job=make_job())
    rc = main(["analyze", "newbuilding"], api=api)
    assert rc == 1
    assert "requires polygon" in capsys.readouterr().err


def test_mvv_outputs_mission_vision_value(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["mvv"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Mission" in out
    assert "Vision" in out
    assert "Value" in out
    assert "見えないものを可視化する" in out


def test_motomura_non_tty_outputs_static_art(capsys: pytest.CaptureFixture[str]) -> None:
    # capsys 配下では TTY でないため静的なアヒルを 1 回だけ出す
    rc = main(["motomura"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "_(o )>" in out
    assert "\\__/" in out


def test_motomura_render_walks_and_waddles() -> None:
    from sateais.cli import _render_motomura

    first = _render_motomura(0, "")
    later = _render_motomura(20, "")
    assert len(first) == 4
    # フレームが進むと水平位置（左パディング）が変わる
    assert first != later
    # 脚は waddle で交互に切り替わる
    assert first[3].strip() in ("/\\", "\\/")
    assert _render_motomura(0, "")[3] != _render_motomura(2, "")[3]


@pytest.mark.parametrize("cmd", ["orbit", "ping", "aurora", "nightsky"])
def test_hidden_animation_commands_run(cmd: str, capsys: pytest.CaptureFixture[str]) -> None:
    # 非 TTY（capsys）では静止画 1 枚を出して終了する
    rc = main([cmd])
    assert rc == 0
    assert capsys.readouterr().out.strip() != ""


def test_decode_outputs_text(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["decode", "HELLO", "WORLD"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "HELLO WORLD"


def test_scene_decodes_sentinel1_id(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["scene", "S1A_IW_GRDH_1SDV_20240101T000000_20240101T000025_052345_065ABC_1A2B"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Sentinel-1A" in out
    assert "dual VV+VH" in out


def test_scene_invalid_returns_error(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["scene", "not-a-scene-id"])
    assert rc == 1
    assert "Sentinel-1 scene ID" in capsys.readouterr().err


def test_analyze_ducky_flag_is_accepted(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeApiClient(
        next_job=make_job(status=JobStatus.PENDING),
        job_sequence=[make_job(status=JobStatus.COMPLETED)],
        result={"type": "FeatureCollection", "features": []},
    )
    rc = main(
        ["analyze", "ship", "--scene-id", "S1A_X", "--wait", "--poll-interval", "0", "--ducky"],
        api=api,
    )
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["type"] == "FeatureCollection"


def test_hidden_commands_absent_from_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    help_text = capsys.readouterr().out
    # 隠しコマンド（mvv 含む）は --help の一覧に出さない
    for hidden in ("orbit", "ping", "mvv", "decode", "aurora", "nightsky", "motomura"):
        assert hidden not in help_text
    # 公開コマンドは --help の一覧に出す
    assert "scene" in help_text


def test_external_api_is_not_closed_by_cli() -> None:
    api = FakeApiClient(next_job=make_job(status=JobStatus.PENDING))
    main(["analyze", "ship", "--scene-id", "S1A_X"], api=api)
    assert api.closed is False
