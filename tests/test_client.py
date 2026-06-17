"""Client / Analyze / Jobs のテスト

FakeApiClient で HTTP を排除し、time.sleep / time.monotonic は monkeypatch する。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from sateais import (
    AnalysisType,
    Client,
    CredentialsNotFoundError,
    InvalidAnalysisRequestError,
    JobFailedError,
    JobStatus,
    JobTimeoutError,
)
from tests.conftest import FakeApiClient, make_job


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """credentials ファイルへフォールバックされないように環境を隔離"""
    monkeypatch.delenv("SATEAIS_API_KEY", raising=False)
    monkeypatch.delenv("SATEAIS_BASE_URL", raising=False)
    monkeypatch.setattr("sateais._client.load_api_key", lambda: None)


def test_client_uses_explicit_api_key() -> None:
    api = FakeApiClient(next_job=make_job(status=JobStatus.PENDING))
    client = Client(api_key="sk_explicit", api=api)
    assert client.api_key == "sk_explicit"


def test_client_uses_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SATEAIS_API_KEY", "sk_env")
    api = FakeApiClient(next_job=make_job())
    client = Client(api=api)
    assert client.api_key == "sk_env"


def test_client_raises_when_no_credentials() -> None:
    with pytest.raises(CredentialsNotFoundError):
        Client(api=FakeApiClient())


def test_analyze_ship_dispatches_with_correct_request() -> None:
    api = FakeApiClient(next_job=make_job(status=JobStatus.PENDING))
    client = Client(api_key="sk", api=api)
    job = client.analyze.ship(scene_id="S1A_X")

    assert job.status is JobStatus.PENDING
    assert api.submitted[0].analysis_type is AnalysisType.SHIP
    assert api.submitted[0].scene_id == "S1A_X"


def test_analyze_validates_before_submitting() -> None:
    api = FakeApiClient(next_job=make_job())
    client = Client(api_key="sk", api=api)
    with pytest.raises(InvalidAnalysisRequestError):
        client.analyze.newbuilding(polygon="POLY", date_start="", date_end="")
    assert api.submitted == []


def test_jobs_status_returns_job() -> None:
    api = FakeApiClient(next_job=make_job(status=JobStatus.COMPLETED))
    client = Client(api_key="sk", api=api)
    assert client.jobs.status("j-1").is_completed
    assert api.fetched == ["j-1"]


def test_jobs_wait_polls_until_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    api = FakeApiClient(
        job_sequence=[
            make_job(status=JobStatus.PENDING),
            make_job(status=JobStatus.PROCESSING),
            make_job(status=JobStatus.COMPLETED),
        ],
        result={"features": [{"x": 1}]},
    )
    client = Client(api_key="sk", api=api)

    polls: list[str] = []
    result = client.jobs.wait(
        "j-1", poll_interval=5.0, on_poll=lambda j: polls.append(j.status.value)
    )

    assert polls == ["pending", "processing", "completed"]
    assert result == {"features": [{"x": 1}]}


def test_jobs_wait_raises_on_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    api = FakeApiClient(
        next_job=make_job(
            status=JobStatus.FAILED,
            error_code="VALIDATION_ERROR",
            error_message="bad",
        )
    )
    client = Client(api_key="sk", api=api)
    with pytest.raises(JobFailedError) as exc:
        client.jobs.wait("j-1", poll_interval=0)
    assert exc.value.job.error_code == "VALIDATION_ERROR"


def test_jobs_wait_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    ticks = iter([0.0, 0.5, 2.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(ticks))

    api = FakeApiClient(next_job=make_job(status=JobStatus.PROCESSING))
    client = Client(api_key="sk", api=api)
    with pytest.raises(JobTimeoutError):
        client.jobs.wait("j-1", poll_interval=0, timeout=1.0)


def test_context_manager_does_not_close_injected_api() -> None:
    api = FakeApiClient(next_job=make_job())
    with Client(api_key="sk", api=api):
        pass
    assert api.closed is False


def test_credentials_file_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """環境変数も引数も無いとき、`~/.sateais/credentials` から読まれる"""
    creds = tmp_path / "credentials"
    creds.write_text('{"api_key": "sk_from_file"}')
    monkeypatch.setattr("sateais._client.load_api_key", lambda: "sk_from_file")
    client = Client(api=FakeApiClient(next_job=make_job()))
    assert client.api_key == "sk_from_file"
