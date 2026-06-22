"""HttpApiClient のテスト（httpx.MockTransport で完結）"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from sateais import (
    AnalysisRequest,
    AnalysisType,
    APIError,
    AuthenticationError,
    InsufficientCreditsError,
    JobStatus,
    NotFoundError,
    RateLimitError,
    ValidationError,
)
from sateais._http import HttpApiClient, _raise_api_error


def _make_client(handler: Callable[[httpx.Request], httpx.Response]) -> HttpApiClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(
        base_url="https://api.test/api/v1", transport=transport, follow_redirects=True
    )
    return HttpApiClient("sk_test", base_url="https://api.test/api/v1", http_client=http)


def test_submit_analysis_posts_correct_path_and_body() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"job_id": "j-1", "status": "pending"})

    client = _make_client(handler)
    job = client.submit_analysis(AnalysisRequest(AnalysisType.SHIP, scene_id="S1A_X"))

    assert job.job_id == "j-1"
    assert job.status is JobStatus.PENDING
    assert captured["url"].endswith("/api/v1/analyze/ship")
    assert captured["body"] == {"satellite_id": "sentinel-1", "scene_id": "S1A_X"}


def test_get_job_and_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/result.geojson"):
            return httpx.Response(200, json={"type": "FeatureCollection", "features": []})
        return httpx.Response(
            200, json={"job_id": "j-1", "status": "completed", "result_path": "..."}
        )

    client = _make_client(handler)
    assert client.get_job("j-1").is_completed
    assert client.get_job_result("j-1")["type"] == "FeatureCollection"


def test_unknown_status_maps_to_unknown_enum() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"job_id": "j-1", "status": "weird"})

    client = _make_client(handler)
    assert client.get_job("j-1").status is JobStatus.UNKNOWN


def test_non_json_success_body_raises_api_error() -> None:
    """200 でも本文が非 JSON なら生の ValueError ではなく APIError に包む"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    client = _make_client(handler)
    with pytest.raises(APIError) as exc:
        client.get_job("j-1")
    assert exc.value.status_code == 200


def test_missing_job_id_wraps_to_api_error() -> None:
    """200 でも job_id 欠落なら生の KeyError ではなく APIError に包む"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "completed"})

    client = _make_client(handler)
    with pytest.raises(APIError) as exc:
        client.get_job("j-1")
    assert exc.value.status_code == 200
    assert "missing job_id" in exc.value.message


def test_non_dict_job_body_wraps_to_api_error() -> None:
    """200 でも本文が JSON 配列/スカラなら APIError に包む（job_id 取得不能）"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[1, 2, 3])

    client = _make_client(handler)
    with pytest.raises(APIError):
        client.get_job("j-1")


def test_non_dict_result_body_wraps_to_api_error() -> None:
    """result.geojson が JSON 配列/スカラなら dict 契約違反として APIError に包む"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[1, 2, 3])

    client = _make_client(handler)
    with pytest.raises(APIError) as exc:
        client.get_job_result("j-1")
    assert exc.value.status_code == 200


def test_network_failure_wraps_to_api_error_with_zero_status() -> None:
    """接続失敗等の通信エラーは status_code=0 の APIError に包む"""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = _make_client(handler)
    with pytest.raises(APIError) as exc:
        client.get_job("j-1")
    assert exc.value.status_code == 0


@pytest.mark.parametrize(
    "status_code,expected",
    [
        (400, ValidationError),
        (401, AuthenticationError),
        (402, InsufficientCreditsError),
        (403, AuthenticationError),
        (404, NotFoundError),
        (410, NotFoundError),
        (429, RateLimitError),
        (500, APIError),
        (502, APIError),
    ],
)
def test_http_errors_map_to_domain_exceptions(status_code: int, expected: type) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": {"code": "X", "message": "boom"}})

    client = _make_client(handler)
    with pytest.raises(expected):
        client.get_job("j-1")


def test_error_parsing_legacy_format() -> None:
    """status エンドポイントの error_code / error_message 形式に対応"""
    resp = httpx.Response(500, json={"error_code": "INTERNAL_ERROR", "error_message": "boom"})
    with pytest.raises(APIError) as exc:
        _raise_api_error(resp)
    assert exc.value.status_code == 500
