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
from ._types import AnalysisRequest, Job, JobStatus
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
        return _job_from_dict(_decode_json(response))

    def get_job(self, job_id: str) -> Job:
        response = self._request("GET", f"/jobs/{job_id}")
        return _job_from_dict(_decode_json(response))

    def get_job_result(self, job_id: str) -> dict[str, Any]:
        resp = self._request("GET", f"/jobs/{job_id}/result.geojson")
        return _decode_json(resp)

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


def _job_from_dict(data: dict[str, Any]) -> Job:
    """API レスポンス dict を Job に変換する"""
    return Job(
        job_id=data["job_id"],
        status=JobStatus.parse(data.get("status")),
        created_at=data.get("created_at"),
        completed_at=data.get("completed_at"),
        result_path=data.get("result_path"),
        error_code=data.get("error_code") or data.get("error"),
        error_message=data.get("error_message"),
    )


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
