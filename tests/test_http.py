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
    CoverageMethod,
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


def test_preview_analysis_posts_to_preview_path_with_same_body() -> None:
    """プレビューのボディは投入と同一で、パスだけ /preview が付く"""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "endpoint_id": "newbuilding",
                "area_sqkm": 78.4,
                "coverage": {
                    "method": "estimated",
                    "requested_area_sqkm": 100.2,
                    "ratio": 0.78,
                    "polygon": "POLYGON ((139 35, ...))",
                },
                "credits": {"estimated": 1.0, "balance": 480.0, "sufficient": True},
                "warnings": [{"code": "LOW_AOI_COVERAGE", "message": "Scenes cover only 78%."}],
            },
        )

    client = _make_client(handler)
    request = AnalysisRequest(
        AnalysisType.NEWBUILDING,
        polygon="POLYGON((0 0,1 0,1 1,0 0))",
        date_start="2025-01-01",
        date_end="2025-06-30",
    )
    preview = client.preview_analysis(request)

    assert captured["url"].endswith("/api/v1/analyze/newbuilding/preview")
    assert captured["body"] == request.to_body()
    assert preview.endpoint_id == "newbuilding"
    assert preview.area_sqkm == 78.4
    assert preview.coverage is not None
    assert preview.coverage.method is CoverageMethod.ESTIMATED
    assert preview.coverage.ratio == 0.78
    # 解析される範囲の WKT は投入前でも返る（そのまま再投入に使える）
    assert preview.coverage.polygon == "POLYGON ((139 35, ...))"
    assert preview.credits.estimated == 1.0
    assert preview.credits.sufficient is True
    assert preview.warnings[0].code == "LOW_AOI_COVERAGE"


def test_preview_insufficient_credits_is_not_an_error() -> None:
    """残高不足は 402 ではなく 200 + sufficient=False で返る"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "endpoint_id": "newbuilding",
                "area_sqkm": 5000.0,
                "credits": {"estimated": 500.0, "balance": 30.0, "sufficient": False},
            },
        )

    client = _make_client(handler)
    preview = client.preview_analysis(
        AnalysisRequest(
            AnalysisType.NEWBUILDING,
            polygon="POLY",
            date_start="2025-01-01",
            date_end="2025-06-30",
        )
    )

    assert preview.credits.sufficient is False
    assert preview.credits.shortfall == 470.0
    assert preview.coverage is None
    assert preview.warnings == ()


def test_preview_returns_coverage_for_ship_with_polygon_and_date() -> None:
    """ship / oilslick も polygon 指定なら coverage が返る（ASF フットプリント経路）"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "endpoint_id": "ship",
                "area_sqkm": 63.0,
                "coverage": {
                    "method": "estimated",
                    "requested_area_sqkm": 100.0,
                    "ratio": 0.63,
                    "polygon": "POLYGON ((139 35, ...))",
                },
                "credits": {"estimated": 1.0, "balance": 480.0, "sufficient": True},
                "warnings": [],
            },
        )

    client = _make_client(handler)
    preview = client.preview_analysis(
        AnalysisRequest(AnalysisType.SHIP, polygon="POLY", date="2025-03-01")
    )

    assert preview.coverage is not None
    assert preview.coverage.ratio == 0.63
    assert preview.coverage.polygon == "POLYGON ((139 35, ...))"


def test_preview_coverage_with_null_fields_stays_none() -> None:
    """coverage はあるが ratio / requested_area_sqkm が null という形もある"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "endpoint_id": "timeseries",
                "coverage": {
                    "method": "estimated",
                    "requested_area_sqkm": None,
                    "ratio": None,
                    "polygon": None,
                },
                "credits": {"estimated": 1.0, "balance": 2.0, "sufficient": True},
            },
        )

    client = _make_client(handler)
    preview = client.preview_analysis(
        AnalysisRequest(
            AnalysisType.TIMESERIES, polygon="POLY", date_start="2025-01-01", date_end="2025-02-01"
        )
    )

    assert preview.coverage is not None
    assert preview.coverage.method is CoverageMethod.ESTIMATED
    assert preview.coverage.ratio is None
    assert preview.coverage.requested_area_sqkm is None


def test_preview_warning_without_message_is_not_the_string_none() -> None:
    """message が欠落・null でも "None" という文字列にしない"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "endpoint_id": "ship",
                "credits": {"estimated": None, "balance": 1.0, "sufficient": None},
                "warnings": [
                    {"code": "CREDITS_NOT_ESTIMABLE", "message": None},
                    {"code": "LOW_AOI_COVERAGE"},
                    {"message": "code の無い要素は落とす"},
                ],
            },
        )

    client = _make_client(handler)
    preview = client.preview_analysis(AnalysisRequest(AnalysisType.SHIP, scene_id="S1A_X"))

    assert [(w.code, w.message) for w in preview.warnings] == [
        ("CREDITS_NOT_ESTIMABLE", ""),
        ("LOW_AOI_COVERAGE", ""),
    ]


def test_preview_omitted_estimate_stays_none() -> None:
    """estimated=null は 0 に潰さず None のまま返す（確定しないことを伝えるため）"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "endpoint_id": "ship",
                "area_sqkm": None,
                "credits": {"estimated": None, "balance": 480.0, "sufficient": None},
                "warnings": [{"code": "CREDITS_NOT_ESTIMABLE", "message": "Not estimable."}],
            },
        )

    client = _make_client(handler)
    preview = client.preview_analysis(AnalysisRequest(AnalysisType.SHIP, scene_id="S1A_X"))

    assert preview.credits.estimated is None
    assert preview.credits.sufficient is None
    assert preview.credits.shortfall is None
    assert preview.area_sqkm is None
    assert [w.code for w in preview.warnings] == ["CREDITS_NOT_ESTIMABLE"]


def test_preview_unknown_coverage_method_falls_back() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "endpoint_id": "timeseries",
                "coverage": {"method": "guessed", "ratio": 0.5},
                "credits": {"estimated": 1.0, "balance": 2.0, "sufficient": True},
            },
        )

    client = _make_client(handler)
    preview = client.preview_analysis(
        AnalysisRequest(
            AnalysisType.TIMESERIES, polygon="POLY", date_start="2025-01-01", date_end="2025-02-01"
        )
    )
    assert preview.coverage is not None
    assert preview.coverage.method is CoverageMethod.UNKNOWN
    assert preview.coverage.polygon is None


@pytest.mark.parametrize(
    "body",
    [
        {"credits": {"balance": 1.0}},  # endpoint_id 欠落
        {"endpoint_id": "ship"},  # credits 欠落
        {"endpoint_id": "ship", "credits": "nope"},  # credits が非オブジェクト
        [],  # そもそもオブジェクトでない
    ],
)
def test_malformed_preview_body_wraps_to_api_error(body: object) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    client = _make_client(handler)
    with pytest.raises(APIError):
        client.preview_analysis(AnalysisRequest(AnalysisType.SHIP, scene_id="S1A_X"))
