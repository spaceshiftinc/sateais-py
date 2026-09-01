"""SDK Client + Analyze / Preview / Jobs リソース

`Client` がユーザー向けエントリポイント兼 composition root。
`Analyze` / `Preview` / `Jobs` は `Client` 経由でのみ使うのが想定。
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any, Generic, TypeVar

from ._credentials import load_api_key
from ._errors import (
    CredentialsNotFoundError,
    JobFailedError,
    JobTimeoutError,
    UnknownJobStatusError,
)
from ._http import DEFAULT_API_BASE_URL, ApiClient, HttpApiClient
from ._types import AnalysisPreview, AnalysisRequest, AnalysisType, Job, JobStatus

ENV_API_KEY = "SATEAIS_API_KEY"
ENV_BASE_URL = "SATEAIS_BASE_URL"

PollCallback = Callable[[Job], None]

#: `_AnalysisEndpoints` の戻り値（投入なら Job、プレビューなら AnalysisPreview）
T = TypeVar("T")


class Client:
    """SateAIs API クライアント

    Example:
        >>> from sateais import Client
        >>> client = Client(api_key="sk_...")
        >>> job = client.analyze.ship(scene_id="S1A_...")
        >>> result = client.jobs.wait(job.job_id)

        投入前プレビュー（ジョブを作らず、解析される範囲と消費見込みを返す）:

        >>> preview = client.preview.newbuilding(
        ...     polygon="POLYGON((...))", date_start="2025-01-01", date_end="2025-06-30"
        ... )

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
        self.base_url = base_url or os.environ.get(ENV_BASE_URL) or DEFAULT_API_BASE_URL
        self.api_key: str | None
        self._api: ApiClient
        if api is not None:
            # カスタム ApiClient 注入時は認証も注入側の責務とみなす。
            # APIキーは env までの best-effort 解決に留め、ディスク（認証ファイル）には
            # 触れない（テスト分離・最小権限のため）。解決できなくても例外にしない。
            self.api_key = api_key or os.environ.get(ENV_API_KEY)
            self._api = api
            self._owns_api = False
        else:
            resolved_key = api_key or os.environ.get(ENV_API_KEY) or load_api_key()
            if not resolved_key:
                raise CredentialsNotFoundError(
                    "API key not found. Pass api_key=, set SATEAIS_API_KEY env var, "
                    "or run `sateais login`."
                )
            self.api_key = resolved_key
            self._api = HttpApiClient(api_key=resolved_key, base_url=self.base_url, timeout=timeout)
            self._owns_api = True

        self.analyze = Analyze(self._api)
        self.preview = Preview(self._api)
        self.jobs = Jobs(self._api)

    def close(self) -> None:
        """通信リソースを解放する（外部注入された ApiClient は解放しない）"""
        if self._owns_api:
            self._api.close()

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()


class _AnalysisEndpoints(Generic[T]):
    """解析種別ごとの入力を組み立てる共通メソッド群

    ジョブ投入（`Analyze`）と投入前プレビュー（`Preview`）は入力が完全に同じで、
    送り先だけが違う。入力の組み立てと検証をここに集約し、サブクラスは
    `_dispatch` で送り先だけを決める。

    直接使わず `Client.analyze` / `Client.preview` から使う。
    """

    def __init__(self, api: ApiClient) -> None:
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
    ) -> T:
        """船舶検知の入力を送る

        `scene_id` 指定、または `polygon + date` 指定のどちらかを与える。
        """
        return self._dispatch(
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
    ) -> T:
        """オイルスリック検知の入力を送る

        `scene_id` 指定、または `polygon + date` 指定のどちらかを与える。
        """
        return self._dispatch(
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
    ) -> T:
        """新規建物検知の入力を送る

        polygon + date_start + date_end が必須。ポリゴン面積上限 30,000 km²。
        """
        return self._dispatch(
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
    ) -> T:
        """消失建物検知の入力を送る

        polygon + date_start + date_end が必須。ポリゴン面積上限 30,000 km²。
        """
        return self._dispatch(
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
    ) -> T:
        """時系列変化解析の入力を送る

        polygon + date_start + date_end が必須。面積 50 km² 以下、期間 3 年以内。
        """
        return self._dispatch(
            AnalysisRequest(
                analysis_type=AnalysisType.TIMESERIES,
                satellite_id=satellite_id,
                polygon=polygon,
                date_start=date_start,
                date_end=date_end,
                orbit_direction=orbit_direction,
            )
        )

    def _dispatch(self, request: AnalysisRequest) -> T:
        """検証済みの入力をどこへ送るかをサブクラスが決める"""
        raise NotImplementedError


class Analyze(_AnalysisEndpoints[Job]):
    """解析ジョブ投入用ファサード

    各メソッドは AnalysisRequest を構築・検証して ApiClient に投げ、
    投入された `Job` を返す。
    """

    def _dispatch(self, request: AnalysisRequest) -> Job:
        request.validate()
        return self._api.submit_analysis(request)


class Preview(_AnalysisEndpoints[AnalysisPreview]):
    """投入前プレビュー用ファサード

    入力は `Analyze` と完全に同じで、ジョブは作らずクレジットも消費しない。
    どの範囲が解析されるか（`coverage`）と消費見込み（`credits`）を投入前に返す。

    残高不足は例外にならず `credits.sufficient=False` として返る
    （いくら足りないかを知ることがプレビューの目的の一つのため）。

    残高以外の検証は投入と同じ関数を同じ順で通るため、プレビューが通れば投入もほぼ通る。
    投入時点の状況で決まるもの（同時実行数の上限 429・残高不足 402）だけは事前に分からない。

    Example:
        >>> preview = client.preview.newbuilding(
        ...     polygon="POLYGON((...))", date_start="2025-01-01", date_end="2025-06-30"
        ... )
        >>> preview.credits.estimated, preview.credits.sufficient
        (1.0, True)
    """

    def _dispatch(self, request: AnalysisRequest) -> AnalysisPreview:
        request.validate()
        return self._api.preview_analysis(request)


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
        max_unknown_polls: int = 10,
    ) -> dict[str, Any]:
        """ジョブが完了するまで待機し、結果 GeoJSON を返す

        Args:
            job_id: ジョブID
            poll_interval: ポーリング間隔（秒）
            timeout: タイムアウト秒数。None で無限待機
            on_poll: 毎回のポーリング後に呼ばれるコールバック
            max_unknown_polls: ステータスが UNKNOWN のまま連続して許容するポーリング回数。
                これを超えたら `UnknownJobStatusError` を送出する。既定 `timeout=None`
                でも API が未知ステータスを返し続けるハングを避けるためのガード。

        Raises:
            JobFailedError: ジョブが failed 状態で終了した場合
            JobTimeoutError: timeout を超えても完了しなかった場合
            UnknownJobStatusError: UNKNOWN が max_unknown_polls 回連続した場合
        """
        start = time.monotonic()
        unknown_streak = 0
        while True:
            job = self._api.get_job(job_id)
            if on_poll is not None:
                on_poll(job)

            if job.is_completed:
                return self._api.get_job_result(job_id)
            if job.is_failed:
                raise JobFailedError(job)

            if job.status is JobStatus.UNKNOWN:
                unknown_streak += 1
                if unknown_streak >= max_unknown_polls:
                    raise UnknownJobStatusError(
                        f"Job {job_id} stayed in an unrecognized status for "
                        f"{unknown_streak} consecutive polls; aborting wait."
                    )
            else:
                unknown_streak = 0

            if timeout is not None and time.monotonic() - start > timeout:
                raise JobTimeoutError(
                    f"Job {job_id} did not complete within {timeout}s "
                    f"(last status={job.status.value})"
                )

            time.sleep(poll_interval)
