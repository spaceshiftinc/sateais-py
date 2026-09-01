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
    UnknownJobStatusError,
)
from tests.conftest import FakeApiClient, make_job, make_preview


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
    # api 未指定でキーがどこからも解決できない場合のみ例外
    with pytest.raises(CredentialsNotFoundError):
        Client()


def test_client_injected_api_does_not_require_key() -> None:
    # カスタム ApiClient 注入時はキーが無くても生成でき、api_key は None
    api = FakeApiClient(next_job=make_job(status=JobStatus.PENDING))
    client = Client(api=api)
    assert client.api_key is None
    assert client.analyze.ship(scene_id="S1A_X").job_id == "j-1"


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
    """環境変数も引数も無いとき、`~/.sateais/credentials` から読まれる（api 非注入時）"""
    creds = tmp_path / "credentials"
    creds.write_text('{"api_key": "sk_from_file"}')
    monkeypatch.setattr("sateais._client.load_api_key", lambda: "sk_from_file")
    client = Client()
    assert client.api_key == "sk_from_file"


def test_injected_api_does_not_read_credentials_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """api 注入時はディスク（認証ファイル）を読まない（テスト分離・最小権限）"""
    called = {"n": 0}

    def _boom() -> str | None:
        called["n"] += 1
        return "sk_from_file"

    monkeypatch.setattr("sateais._client.load_api_key", _boom)
    client = Client(api=FakeApiClient(next_job=make_job()))
    assert called["n"] == 0
    assert client.api_key is None


def test_jobs_wait_aborts_on_persistent_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    """UNKNOWN が連続したら無限ループせず UnknownJobStatusError で抜ける"""
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    api = FakeApiClient(next_job=make_job(status=JobStatus.UNKNOWN))
    client = Client(api_key="sk", api=api)
    with pytest.raises(UnknownJobStatusError):
        client.jobs.wait("j-1", poll_interval=0, timeout=None, max_unknown_polls=3)
    # 有限回（max_unknown_polls 回）で打ち切られる
    assert len(api.fetched) == 3


def test_jobs_wait_unknown_streak_resets(monkeypatch: pytest.MonkeyPatch) -> None:
    """UNKNOWN が連続せず間に既知ステータスを挟めば打ち切られない"""
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    api = FakeApiClient(
        job_sequence=[
            make_job(status=JobStatus.UNKNOWN),
            make_job(status=JobStatus.PROCESSING),
            make_job(status=JobStatus.UNKNOWN),
            make_job(status=JobStatus.COMPLETED),
        ],
        result={"features": []},
    )
    client = Client(api_key="sk", api=api)
    result = client.jobs.wait("j-1", poll_interval=0, max_unknown_polls=2)
    assert result == {"features": []}


def test_preview_dispatches_to_preview_endpoint() -> None:
    api = FakeApiClient(next_preview=make_preview("newbuilding", estimated=215.99))
    client = Client(api_key="sk", api=api)
    preview = client.preview.newbuilding(
        polygon="POLY", date_start="2025-01-01", date_end="2025-06-30"
    )

    assert preview.endpoint_id == "newbuilding"
    assert preview.credits.estimated == 215.99
    assert api.previewed[0].analysis_type is AnalysisType.NEWBUILDING
    assert api.previewed[0].polygon == "POLY"
    # プレビューはジョブを作らない
    assert api.submitted == []


def test_preview_validates_before_requesting() -> None:
    """検証は投入と同一。プレビューが通れば投入も通る、を SDK 側でも保つ"""
    api = FakeApiClient(next_preview=make_preview())
    client = Client(api_key="sk", api=api)
    with pytest.raises(InvalidAnalysisRequestError):
        client.preview.ship(scene_id="S1A_X", polygon="POLY", date="2025-01-01")
    assert api.previewed == []


def test_preview_insufficient_credits_does_not_raise() -> None:
    api = FakeApiClient(
        next_preview=make_preview("ship", estimated=500.0, balance=30.0, sufficient=False)
    )
    client = Client(api_key="sk", api=api)
    preview = client.preview.ship(scene_id="S1A_X")

    assert preview.credits.sufficient is False
    assert preview.credits.shortfall == 470.0
