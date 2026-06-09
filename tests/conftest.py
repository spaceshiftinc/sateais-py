"""テスト共通の Fake 実装

`ApiClient` Protocol を満たすインメモリの FakeApiClient。
Client / CLI のテストで HTTP 通信を排除するために使う。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sateais import ApiClient
from sateais._types import AnalysisRequest, Job, JobStatus


@dataclass
class FakeApiClient:
    """Fake ApiClient

    Attributes:
        submitted: 投入された AnalysisRequest のリスト
        fetched: get_job() で問い合わせられた job_id のリスト
        fetched_results: get_job_result() で問い合わせられた job_id のリスト
        next_job: get_job / submit_analysis が返す Job
        job_sequence: 指定されている場合、get_job 呼び出しごとに先頭から消費
        result: get_job_result が返す GeoJSON dict
        closed: close() が呼ばれたかのフラグ
    """

    submitted: list[AnalysisRequest] = field(default_factory=list)
    fetched: list[str] = field(default_factory=list)
    fetched_results: list[str] = field(default_factory=list)
    next_job: Job | None = None
    job_sequence: list[Job] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    closed: bool = False

    def submit_analysis(self, request: AnalysisRequest) -> Job:
        self.submitted.append(request)
        assert self.next_job is not None, "FakeApiClient.next_job not set"
        return self.next_job

    def get_job(self, job_id: str) -> Job:
        self.fetched.append(job_id)
        if self.job_sequence:
            return self.job_sequence.pop(0)
        assert self.next_job is not None, "FakeApiClient.next_job not set"
        return self.next_job

    def get_job_result(self, job_id: str) -> dict[str, Any]:
        self.fetched_results.append(job_id)
        return self.result

    def close(self) -> None:
        self.closed = True


def make_job(
    job_id: str = "j-1",
    status: JobStatus = JobStatus.PENDING,
    **extra: Any,
) -> Job:
    """テスト用の Job 生成ヘルパー"""
    return Job(job_id=job_id, status=status, **extra)


# Protocol 適合の静的確認（mypy がチェック）
_a: ApiClient = FakeApiClient()
