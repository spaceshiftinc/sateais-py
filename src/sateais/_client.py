"""SDK Client + Analyze / Jobs リソース

`Client` がユーザー向けエントリポイント兼 composition root。
`Analyze` と `Jobs` は `Client` 経由でのみ使うのが想定。
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

from ._credentials import load_api_key
from ._errors import CredentialsNotFoundError, JobFailedError, JobTimeoutError
from ._http import DEFAULT_API_BASE_URL, ApiClient, HttpApiClient
from ._types import AnalysisRequest, AnalysisType, Job

ENV_API_KEY = "SATEAIS_API_KEY"
ENV_BASE_URL = "SATEAIS_BASE_URL"

PollCallback = Callable[[Job], None]


class Client:
    """SateAIs API クライアント

    Example:
        >>> from sateais import Client
        >>> client = Client(api_key="sk_...")
        >>> job = client.analyze.ship(scene_id="S1A_...")
        >>> result = client.jobs.wait(job.job_id)

    Args:
        api_key: APIキー。未指定時は環境変数 `SATEAIS_API_KEY`、
                 次に `~/.sateais/credentials` から読み込む。
        base_url: APIベースURL。未指定時は環境変数 `SATEAIS_BASE_URL`、
                  次に既定の本番URLを使う。
        timeout: HTTPリクエストのタイムアウト秒数。
        api: ApiClient の差し替え（テスト・カスタム実装用）。指定された場合
             `base_url`/`timeout` は使われず、認証も注入した ApiClient の責務となる。
             APIキーは best-effort で解決され（できなければ `client.api_key` は None）、
             解決できなくても例外にはならない。

    Raises:
        CredentialsNotFoundError: `api` 未指定で、かつ APIキーがどこからも
            解決できなかった場合。
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = 30.0,
        api: ApiClient | None = None,
    ):
        resolved_key = api_key or os.environ.get(ENV_API_KEY) or load_api_key()
        self.base_url = base_url or os.environ.get(ENV_BASE_URL) or DEFAULT_API_BASE_URL
        self.api_key: str | None
        self._api: ApiClient
        if api is not None:
            # カスタム ApiClient 注入時は認証も注入側の責務とみなし、
            # APIキーが解決できなくても例外にしない（解決できれば属性に保持）。
            self.api_key = resolved_key
            self._api = api
            self._owns_api = False
        else:
            if not resolved_key:
                raise CredentialsNotFoundError(
                    "API key not found. Pass api_key=, set SATEAIS_API_KEY env var, "
                    "or run `sateais login`."
                )
            self.api_key = resolved_key
            self._api = HttpApiClient(
                api_key=resolved_key, base_url=self.base_url, timeout=timeout
            )
            self._owns_api = True

        self.analyze = Analyze(self._api)
        self.jobs = Jobs(self._api)

    def close(self) -> None:
        """通信リソースを解放する（外部注入された ApiClient は解放しない）"""
        if self._owns_api:
            self._api.close()

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()


class Analyze:
    """解析ジョブ投入用ファサード

    各メソッドは AnalysisRequest を構築・検証して ApiClient に投げる。
    """

    def __init__(self, api: ApiClient):
        self._api = api

    def ship(
        self,
        *,
        scene_id: str | None = None,
        polygon: str | None = None,
        date: str | None = None,
        date_direction: str | None = None,
        orbit_direction: str | None = None,
        satellite_id: str = "sentinel-1",
    ) -> Job:
        """船舶検知ジョブを作成する

        `scene_id` 指定、または `polygon + date` 指定のどちらかを与える。
        """
        return self._submit(
            AnalysisRequest(
                analysis_type=AnalysisType.SHIP,
                scene_id=scene_id,
                polygon=polygon,
                date=date,
                date_direction=date_direction,
                orbit_direction=orbit_direction,
                satellite_id=satellite_id,
            )
        )

    def oilslick(
        self,
        *,
        scene_id: str | None = None,
        polygon: str | None = None,
        date: str | None = None,
        date_direction: str | None = None,
        orbit_direction: str | None = None,
        satellite_id: str = "sentinel-1",
    ) -> Job:
        """オイルスリック検知ジョブを作成する

        `scene_id` 指定、または `polygon + date` 指定のどちらかを与える。
        """
        return self._submit(
            AnalysisRequest(
                analysis_type=AnalysisType.OILSLICK,
                scene_id=scene_id,
                polygon=polygon,
                date=date,
                date_direction=date_direction,
                orbit_direction=orbit_direction,
                satellite_id=satellite_id,
            )
        )

    def newbuilding(
        self,
        *,
        polygon: str,
        date_start: str,
        date_end: str,
        orbit_direction: str | None = None,
        satellite_id: str = "sentinel-1",
    ) -> Job:
        """新規建物検知ジョブを作成する

        polygon + date_start + date_end が必須。ポリゴン面積上限 30,000 km²。
        """
        return self._submit(
            AnalysisRequest(
                analysis_type=AnalysisType.NEWBUILDING,
                satellite_id=satellite_id,
                polygon=polygon,
                date_start=date_start,
                date_end=date_end,
                orbit_direction=orbit_direction,
            )
        )

    def disappearbuilding(
        self,
        *,
        polygon: str,
        date_start: str,
        date_end: str,
        orbit_direction: str | None = None,
        satellite_id: str = "sentinel-1",
    ) -> Job:
        """消失建物検知ジョブを作成する

        polygon + date_start + date_end が必須。ポリゴン面積上限 30,000 km²。
        """
        return self._submit(
            AnalysisRequest(
                analysis_type=AnalysisType.DISAPPEARBUILDING,
                satellite_id=satellite_id,
                polygon=polygon,
                date_start=date_start,
                date_end=date_end,
                orbit_direction=orbit_direction,
            )
        )

    def timeseries(
        self,
        *,
        polygon: str,
        date_start: str,
        date_end: str,
        orbit_direction: str | None = None,
        satellite_id: str = "sentinel-1",
    ) -> Job:
        """時系列変化解析ジョブを作成する

        polygon + date_start + date_end が必須。面積 50 km² 以下、期間 3 年以内。
        """
        return self._submit(
            AnalysisRequest(
                analysis_type=AnalysisType.TIMESERIES,
                satellite_id=satellite_id,
                polygon=polygon,
                date_start=date_start,
                date_end=date_end,
                orbit_direction=orbit_direction,
            )
        )

    def _submit(self, request: AnalysisRequest) -> Job:
        request.validate()
        return self._api.submit_analysis(request)


class Jobs:
    """ジョブ管理用ファサード"""

    def __init__(self, api: ApiClient) -> None:
        self._api = api

    def status(self, job_id: str) -> Job:
        """ジョブのステータスを取得する"""
        return self._api.get_job(job_id)

    def result(self, job_id: str) -> dict[str, Any]:
        """完了したジョブの結果 GeoJSON を取得する"""
        return self._api.get_job_result(job_id)

    def wait(
        self,
        job_id: str,
        *,
        poll_interval: float = 10.0,
        timeout: float | None = None,
        on_poll: PollCallback | None = None,
    ) -> dict[str, Any]:
        """ジョブが完了するまで待機し、結果 GeoJSON を返す

        Args:
            job_id: ジョブID
            poll_interval: ポーリング間隔（秒）
            timeout: タイムアウト秒数。None で無限待機
            on_poll: 毎回のポーリング後に呼ばれるコールバック

        Raises:
            JobFailedError: ジョブが failed 状態で終了した場合
            JobTimeoutError: timeout を超えても完了しなかった場合
        """
        start = time.monotonic()
        while True:
            job = self._api.get_job(job_id)
            if on_poll is not None:
                on_poll(job)

            if job.is_completed:
                return self._api.get_job_result(job_id)
            if job.is_failed:
                raise JobFailedError(job)

            if timeout is not None and time.monotonic() - start > timeout:
                raise JobTimeoutError(
                    f"Job {job_id} did not complete within {timeout}s "
                    f"(last status={job.status.value})"
                )

            time.sleep(poll_interval)
