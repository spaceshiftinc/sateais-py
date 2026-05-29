"""HttpApiClient のテスト（httpx.MockTransport で完結）"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from sateais import (
    APIError,
    AuthenticationError,
    DetectionRequest,
    DetectionType,
    InsufficientCreditsError,
    JobStatus,
    NotFoundError,
    RateLimitError,
    ValidationError,
)
from sateais._http import HttpApiClient, _raise_api_error


def _make_client(handler: Callable[[httpx.Request], httpx.Response]) -> HttpApiClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(base_url="https://api.test", transport=transport, follow_redirects=True)
    return HttpApiClient("sk_test", base_url="https://api.test", http_client=http)


def test_submit_detection_posts_correct_path_and_body() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"job_id": "j-1", "status": "pending"})

    client = _make_client(handler)
    job = client.submit_detection(DetectionRequest(DetectionType.SHIP, scene_id="S1A_X"))

    assert job.job_id == "j-1"
    assert job.status is JobStatus.PENDING
    assert captured["url"].endswith("/api/v1/detect/ship")
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
