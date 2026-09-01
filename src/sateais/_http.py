"""HTTP 通信層

ApiClient Protocol を定義し、httpx ベースの実装 HttpApiClient を提供する。
これ1ファイルが SDK で唯一の I/O 境界（filesystem を除く）。

Port を Protocol で切ることでテスト時の Fake 差し替えを可能にする。
それ以外（時刻、スリープ、認証ファイル）は Protocol を切らず直接利用する。
"""

from __future__ import annotations

from typing import Any, NoReturn, Protocol, runtime_checkable

import httpx

from ._errors import (
    APIError,
    AuthenticationError,
    InsufficientCreditsError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)
from ._types import (
    AnalysisPreview,
    AnalysisRequest,
    Coverage,
    CoverageMethod,
    Job,
    JobStatus,
    PreviewCredits,
    SceneWarning,
)
from ._version import __version__

DEFAULT_API_BASE_URL = "https://api.spcsft.com/api/v1"

_STATUS_CODE_MAP: dict[int, type[APIError]] = {
    400: ValidationError,
    401: AuthenticationError,
    402: InsufficientCreditsError,
    403: AuthenticationError,
    404: NotFoundError,
    410: NotFoundError,
    429: RateLimitError,
}


@runtime_checkable
class ApiClient(Protocol):
    """SateAIs API への通信ポート

    HttpApiClient が標準実装。テスト時には Fake と差し替える。
    """

    def submit_analysis(self, request: AnalysisRequest) -> Job: ...
    def preview_analysis(self, request: AnalysisRequest) -> AnalysisPreview: ...
    def get_job(self, job_id: str) -> Job: ...
    def get_job_result(self, job_id: str) -> dict[str, Any]: ...
    def close(self) -> None: ...


class HttpApiClient:
    """httpx を使った ApiClient 実装

    Args:
        api_key: 認証用APIキー
        base_url: APIベースURL（末尾スラッシュは削除される）
        timeout: HTTPリクエストのタイムアウト秒数
        http_client: テスト時に httpx.Client を差し替える注入口
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_API_BASE_URL,
        timeout: float = 30.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

        if http_client is not None:
            self._http = http_client
            self.owns_http = False
        else:
            self._http = httpx.Client(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": f"sateais-py/{__version__}",
                },
                timeout=timeout,
                follow_redirects=True,
            )
            self.owns_http = True

    def submit_analysis(self, request: AnalysisRequest) -> Job:
        response = self._request(
            "POST",
            f"/analyze/{request.analysis_type.value}",
            json_body=request.to_body(),
        )
        return _job_from_dict(_decode_json(response), response.status_code)

    def preview_analysis(self, request: AnalysisRequest) -> AnalysisPreview:
        response = self._request(
            "POST",
            f"/analyze/{request.analysis_type.value}/preview",
            json_body=request.to_body(),
        )
        return _preview_from_dict(_decode_json(response), response.status_code)

    def get_job(self, job_id: str) -> Job:
        response = self._request("GET", f"/jobs/{job_id}")
        return _job_from_dict(_decode_json(response), response.status_code)

    def get_job_result(self, job_id: str) -> dict[str, Any]:
        resp = self._request("GET", f"/jobs/{job_id}/result.geojson")
        body = _decode_json(resp)
        # 戻り型は dict 契約。JSON 配列/スカラが返った場合は下流の AttributeError を
        # 防ぐため、生のままではなく SateAIsError 階層の APIError に包む。
        if not isinstance(body, dict):
            raise APIError(
                resp.status_code,
                None,
                f"expected JSON object in response body, got {type(body).__name__}",
            )
        return body

    def close(self) -> None:
        if self.owns_http:
            self._http.close()

    def _request(
        self, method: str, path: str, *, json_body: dict[str, Any] | None = None
    ) -> httpx.Response:
        try:
            response = self._http.request(method, path, json=json_body)
        except httpx.HTTPError as e:
            raise APIError(0, None, f"HTTP request failed: {str(e)}") from e

        if response.is_success:
            return response
        _raise_api_error(response)


def _decode_json(response: httpx.Response) -> Any:
    """成功レスポンスの JSON ボディをデコードする

    本来 JSON が返るはずのエンドポイントで非 JSON ボディが返った場合でも、
    生の ValueError ではなく SateAIsError 階層の APIError に包んで送出する。
    """
    try:
        return response.json()
    except ValueError as e:
        raise APIError(response.status_code, None, f"Invalid JSON in response body: {e}") from e


def _job_from_dict(data: Any, status_code: int) -> Job:
    """API レスポンス dict を Job に変換する

    JSON だがオブジェクトでない／必須の job_id が欠落しているケースでも、
    生の KeyError/AttributeError ではなく SateAIsError 階層の APIError に包む。
    """
    if not isinstance(data, dict) or "job_id" not in data:
        raise APIError(status_code, None, "missing job_id in response")
    return Job(
        job_id=data["job_id"],
        status=JobStatus.parse(data.get("status")),
        created_at=data.get("created_at"),
        completed_at=data.get("completed_at"),
        result_path=data.get("result_path"),
        error_code=data.get("error_code") or data.get("error"),
        error_message=data.get("error_message"),
    )


def _preview_from_dict(data: Any, status_code: int) -> AnalysisPreview:
    """API レスポンス dict を AnalysisPreview に変換する

    `endpoint_id` / `credits` が欠けた応答はプレビューとして解釈できないため、
    生の KeyError/AttributeError ではなく SateAIsError 階層の APIError に包む。
    それ以外のフィールドは欠落を許容する（入力によっては API が返さないため）。
    """
    if not isinstance(data, dict) or "endpoint_id" not in data:
        raise APIError(status_code, None, "missing endpoint_id in response")
    credits = data.get("credits")
    if not isinstance(credits, dict):
        raise APIError(status_code, None, "missing credits in response")

    return AnalysisPreview(
        endpoint_id=str(data["endpoint_id"]),
        credits=PreviewCredits(
            estimated=_as_float(credits.get("estimated")),
            balance=_as_float(credits.get("balance")),
            sufficient=_as_bool(credits.get("sufficient")),
        ),
        area_sqkm=_as_float(data.get("area_sqkm")),
        coverage=_coverage_from_dict(data.get("coverage")),
        warnings=_warnings_from_list(data.get("warnings")),
    )


def _coverage_from_dict(data: Any) -> Coverage | None:
    """coverage オブジェクトを Coverage に変換する（欠落・非オブジェクトは None）

    API は判定できない入力では coverage 自体を返さない。推測値で埋めず None のまま
    返し、「情報が無い」ことを利用者に伝える。
    """
    if not isinstance(data, dict):
        return None
    return Coverage(
        method=CoverageMethod.parse(data.get("method")),
        requested_area_sqkm=_as_float(data.get("requested_area_sqkm")),
        ratio=_as_float(data.get("ratio")),
        polygon=_as_str(data.get("polygon")),
    )


def _warnings_from_list(data: Any) -> tuple[SceneWarning, ...]:
    """warnings 配列を SceneWarning のタプルに変換する（code を持つ要素のみ）

    message が欠落・非文字列の場合は空文字にする。`str()` で包むと null が
    "None" という文字列になって表示に出てしまうため。
    """
    if not isinstance(data, list):
        return ()
    return tuple(
        SceneWarning(code=item["code"], message=_as_str(item.get("message")) or "")
        for item in data
        if isinstance(item, dict) and isinstance(item.get("code"), str)
    )


def _as_float(value: Any) -> float | None:
    """JSON の数値を float に正規化する（None / 非数値は None）

    bool は数値として扱わない（`true` が 1.0 になるのを避けるため）。
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _as_str(value: Any) -> str | None:
    """JSON の文字列だけを通す（None / 非文字列は None）"""
    return value if isinstance(value, str) else None


def _as_bool(value: Any) -> bool | None:
    """JSON の真偽値だけを通す（None / 非真偽値は None）"""
    return value if isinstance(value, bool) else None


def _raise_api_error(response: httpx.Response) -> NoReturn:
    """エラーレスポンスを APIError サブクラスに変換して送出する"""
    try:
        body = response.json()
    except ValueError:
        body = {}

    code: str | None = None
    message: str = response.text or f"HTTP {response.status_code}"

    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            code = err.get("code")
            message = err.get("message", message)
        elif isinstance(err, str):
            code = err
            message = body.get("error_message") or body.get("message") or message
        else:
            code = body.get("error_code")
            message = body.get("error_message") or body.get("message") or message

    cls = _STATUS_CODE_MAP.get(response.status_code, APIError)
    raise cls(response.status_code, code, message)
