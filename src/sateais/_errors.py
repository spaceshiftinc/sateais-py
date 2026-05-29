"""例外階層

SDK が送出する例外はすべて SateAIsError を継承する。
HTTP エラーは _http モジュールで APIError サブクラスへマップされる。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._types import Job


class SateAIsError(Exception):
    """SDK の基底例外"""


class APIError(SateAIsError):
    """API がエラーレスポンスを返した

    Attributes:
        status_code: HTTPステータスコード
        code: APIエラーコード（VALIDATION_ERROR など）
        message: エラーメッセージ
    """

    def __init__(self, status_code: int, code: str | None, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        suffix = f"[{code}] " if code else ""
        super().__init__(f"HTTP {status_code}: {suffix}{message}")


class AuthenticationError(APIError):
    """認証エラー（401 / 403）"""


class ValidationError(APIError):
    """リクエスト形式が不正（400）"""


class InsufficientCreditsError(APIError):
    """クレジット不足（402）"""


class NotFoundError(APIError):
    """リソースが見つからない（404 / 410）"""


class RateLimitError(APIError):
    """レート制限超過（429）"""


class JobFailedError(SateAIsError):
    """ジョブが failed 状態で終了した

    Attributes:
        job: 失敗した Job エンティティ
    """

    def __init__(self, job: Job) -> None:
        self.job = job
        code = job.error_code or "UNKNOWN"
        msg = job.error_message or "(no message)"
        super().__init__(f"Job {job.job_id} failed: [{code}] {msg}")


class JobTimeoutError(SateAIsError):
    """ジョブがタイムアウト時間内に完了しなかった"""


class CredentialsNotFoundError(SateAIsError):
    """APIキーが解決できなかった"""


class InvalidDetectionRequestError(SateAIsError):
    """DetectionRequest のパラメータ組み合わせが不正"""
