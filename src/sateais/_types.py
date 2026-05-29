"""エンティティ・値オブジェクト

Job / JobStatus / DetectionType / DetectionRequest を提供する。
ドメインルールの検証 (`DetectionRequest.validate`) もここに置く。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ._errors import InvalidDetectionRequestError


class JobStatus(str, Enum):
    """ジョブのステータス値

    API が将来未知のステータスを返した場合は UNKNOWN にフォールバックする。
    """

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"

    @classmethod
    def parse(cls, raw: str | None) -> JobStatus:
        if raw is None:
            return cls.UNKNOWN
        try:
            return cls(raw)
        except ValueError:
            return cls.UNKNOWN
    

@dataclass
class Job:
    """ジョブの状態を表すエンティティ

    Attributes:
        job_id: ジョブID（UUID）
        status: ジョブの現在のステータス
        created_at: 作成日時（ISO 8601）
        completed_at: 完了日時（ISO 8601）
        result_path: 結果ファイル取得用のAPIパス
        error_code: エラーコード（failed 時）
        error_message: エラー詳細（failed 時）
    """

    job_id: str
    status: JobStatus
    created_at: str | None = None
    completed_at: str | None = None
    result_path: str | None = None
    error_code: str | None = None
    error_message: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in (JobStatus.COMPLETED, JobStatus.FAILED)
    
    @property
    def is_completed(self) -> bool:
        return self.status == JobStatus.COMPLETED
    

    @property
    def is_failed(self) -> bool:
        return self.status == JobStatus.FAILED
    

class DetectionType(str, Enum):
    """検出ジョブの種別"""

    SHIP = "ship"
    OILSLICK = "oilslick"
    NEWBUILDING = "newbuilding"
    DISAPPEARBUILDING = "disappearbuilding"
    TIMESERIES = "timeseries"

    @property
    def accepts_scene_or_polygon_date(self) -> bool:
        """この種別のジョブが scene_id / polygon + date データを受け入れるか"""
        return self in (DetectionType.SHIP, DetectionType.OILSLICK)
    
    @property
    def requires_date_range(self) -> bool:
        """この種別のジョブが polygon + start_date / end_date データを必須とするか"""
        return self in (
            DetectionType.NEWBUILDING, 
            DetectionType.DISAPPEARBUILDING,
            DetectionType.TIMESERIES,
        )


@dataclass(frozen=True)
class DetectionRequest:
    """検出ジョブの入力パラメータ（統一形式）

    全種別を扱える共通 DTO。組み合わせの妥当性は `validate()` で検証する。

    Attributes:
        detection_type: 検出種別
        satellite_id: 衛星ID。現状の対応値は "sentinel-1"（デフォルト）。
            今後対応衛星が増えた場合は他の値も指定可能になる。
        scene_id: シーンID（ship/oilslick のシーン指定モード）
        polygon: WKT polygon (EPSG:4326)
        date: 基準日 YYYY-MM-DD（ship/oilslick の polygon モード）
        date_start: 開始日 YYYY-MM-DD（範囲指定型エンドポイント）
        date_end: 終了日 YYYY-MM-DD（同上）
        date_direction: "before" / "after" / "nearest"
        orbit_direction: "ascending" / "descending"
    """

    detection_type: DetectionType
    satellite_id: str = "sentinel-1"
    scene_id: str | None = None
    polygon: str | None = None
    date: str | None = None
    date_start: str | None = None
    date_end: str | None = None
    date_direction: str | None = None
    orbit_direction: str | None = None

    def validate(self) -> None:
        """必須パラメータの組み合わせを検証する

        Raises:
            InvalidDetectionRequestError: 組み合わせが不正な場合
        """
        t = self.detection_type
        if t.accepts_scene_or_polygon_date:
            has_scene = bool(self.scene_id)
            has_polygon_date = bool(self.polygon) and bool(self.date)
            if has_scene == has_polygon_date:
                raise InvalidDetectionRequestError(
                    f"{t.value}: specify exactly one of scene_id OR polygon+date "
                    f"(got scene_id={has_scene}, polygon={bool(self.polygon)}, "
                    f"date={bool(self.date)})"
                )
        elif t.requires_date_range:
            if not (self.polygon and self.date_start and self.date_end):
                raise InvalidDetectionRequestError(
                    f"{t.value} requires polygon, date_start, and date_end"
                )
    
    def to_body(self) -> dict[str, str]:
        """APIリクエストボディ dict に変換する（None フィールドは除外）"""
        fields = {
            "satellite_id": self.satellite_id,
            "scene_id": self.scene_id,
            "polygon": self.polygon,
            "date": self.date,
            "date_start": self.date_start,
            "date_end": self.date_end,
            "date_direction": self.date_direction,
            "orbit_direction": self.orbit_direction,
        }
        return {k: v for k, v in fields.items() if v is not None}