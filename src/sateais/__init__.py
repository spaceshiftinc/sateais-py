"""SateAIs Python SDK

Sentinel-1 SAR 衛星画像解析プラットフォーム SateAIs の公式 Python SDK / CLI。

Quickstart:
    >>> from sateais import Client
    >>> client = Client(api_key="sk_...")
    >>> job = client.detect.ship(scene_id="S1A_IW_GRDH_...")
    >>> result = client.jobs.wait(job.job_id)

内部構造:
    軽量な Hexagonal 構成。HTTP 通信のみ Port (`ApiClient` Protocol) を介して
    差し替え可能で、それ以外（時刻・スリープ・認証ファイル）は具体実装を直接使う。
    詳細は docs/ARCHITECTURE.md 参照。
"""

from ._client import Client
from ._credentials import load_api_key, save_api_key
from ._errors import (
    APIError,
    AuthenticationError,
    CredentialsNotFoundError,
    InsufficientCreditsError,
    InvalidDetectionRequestError,
    JobFailedError,
    JobTimeoutError,
    NotFoundError,
    RateLimitError,
    SateAIsError,
    ValidationError,
)
from ._http import ApiClient
from ._types import DetectionRequest, DetectionType, Job, JobStatus
from ._version import __version__

__all__ = [
    "__version__",
    # facade
    "Client",
    # entities
    "Job",
    "JobStatus",
    "DetectionRequest",
    "DetectionType",
    # port (for advanced DI)
    "ApiClient",
    # credentials helpers
    "load_api_key",
    "save_api_key",
    # exceptions
    "SateAIsError",
    "APIError",
    "AuthenticationError",
    "ValidationError",
    "InsufficientCreditsError",
    "NotFoundError",
    "RateLimitError",
    "JobFailedError",
    "JobTimeoutError",
    "CredentialsNotFoundError",
    "InvalidDetectionRequestError",
]
