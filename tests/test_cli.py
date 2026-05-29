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


def test_detect_outputs_job_json(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeApiClient(next_job=make_job(status=JobStatus.PENDING))
    rc = main(["detect", "ship", "--scene-id", "S1A_X"], api=api)
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["job_id"] == "j-1"
    assert out["status"] == "pending"
    assert api.submitted[0].scene_id == "S1A_X"


def test_detect_with_wait_outputs_geojson(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeApiClient(
        next_job=make_job(status=JobStatus.PENDING),
        job_sequence=[make_job(status=JobStatus.COMPLETED)],
        result={"type": "FeatureCollection", "features": []},
    )
    rc = main(
        ["detect", "ship", "--scene-id", "S1A_X", "--wait", "--poll-interval", "0"],
        api=api,
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["type"] == "FeatureCollection"


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


def test_invalid_detection_request_returns_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    api = FakeApiClient(next_job=make_job())
    rc = main(["detect", "newbuilding"], api=api)
    assert rc == 1
    assert "requires polygon" in capsys.readouterr().err


def test_external_api_is_not_closed_by_cli() -> None:
    api = FakeApiClient(next_job=make_job(status=JobStatus.PENDING))
    main(["detect", "ship", "--scene-id", "S1A_X"], api=api)
    assert api.closed is False
