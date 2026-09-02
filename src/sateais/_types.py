"""エンティティ・値オブジェクト

Job / JobStatus / AnalysisType / AnalysisRequest と、投入前プレビューの
エンティティ（AnalysisPreview / PreviewCredits / Coverage / SceneWarning）を提供する。
ドメインルールの検証 (`AnalysisRequest.validate`) もここに置く。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ._errors import InvalidAnalysisRequestError


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


@dataclass(frozen=True)
class Job:
    """ジョブの状態を表すエンティティ（取得時点のスナップショット、不変）

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


class AnalysisType(str, Enum):
    """解析ジョブの種別"""

    SHIP = "ship"
    OILSLICK = "oilslick"
    NEWBUILDING = "newbuilding"
    DISAPPEARBUILDING = "disappearbuilding"
    TIMESERIES = "timeseries"

    @property
    def accepts_scene_or_polygon_date(self) -> bool:
        """この種別のジョブが scene_id / polygon + date データを受け入れるか"""
        return self in (AnalysisType.SHIP, AnalysisType.OILSLICK)

    @property
    def requires_date_range(self) -> bool:
        """この種別のジョブが polygon + start_date / end_date データを必須とするか"""
        return self in (
            AnalysisType.NEWBUILDING,
            AnalysisType.DISAPPEARBUILDING,
            AnalysisType.TIMESERIES,
        )


@dataclass(frozen=True)
class AnalysisRequest:
    """解析ジョブの入力パラメータ（統一形式）

    全種別を扱える共通 DTO。組み合わせの妥当性は `validate()` で検証する。

    Attributes:
        analysis_type: 解析種別
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

    analysis_type: AnalysisType
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
            InvalidAnalysisRequestError: 組み合わせが不正な場合
        """
        t = self.analysis_type
        if t.accepts_scene_or_polygon_date:
            has_scene = bool(self.scene_id)
            has_polygon_date = bool(self.polygon) and bool(self.date)
            if has_scene == has_polygon_date:
                raise InvalidAnalysisRequestError(
                    f"{t.value}: specify exactly one of scene_id OR polygon+date "
                    f"(got scene_id={has_scene}, polygon={bool(self.polygon)}, "
                    f"date={bool(self.date)})"
                )
        elif t.requires_date_range:
            if not (self.polygon and self.date_start and self.date_end):
                raise InvalidAnalysisRequestError(
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


class CoverageMethod(str, Enum):
    """被覆率をどうやって出したか

    API が将来未知の値を返した場合は UNKNOWN にフォールバックする。
    """

    #: NoData を除外した実データ境界から測定した
    MEASURED = "measured"
    #: シーンのフットプリントと要求範囲の交差から推定した
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"

    @classmethod
    def parse(cls, raw: str | None) -> CoverageMethod:
        if raw is None:
            return cls.UNKNOWN
        try:
            return cls(raw)
        except ValueError:
            return cls.UNKNOWN


@dataclass(frozen=True)
class Coverage:
    """指定範囲のうち、実際に解析される範囲

    指定した polygon と実際に解析される範囲は一致しない（シーンが範囲全体を
    覆っていない、NoData が含まれる等）。判定できない入力では API が coverage
    自体を返さないため `None` になる。「情報が無い」と「100% 解析される」は
    別のことなので、`ratio` を 1.0 で埋めることはしない。

    Attributes:
        method: 被覆率の算出方法。投入前プレビューは必ず ESTIMATED
        requested_area_sqkm: 指定した範囲の面積（km²）
        ratio: 解析される割合（0.0〜1.0）
        polygon: 実際に解析される範囲の WKT。リクエストの `polygon` と同じ形式
            なので、覆えなかった範囲を指定し直す用途にそのまま使える。
            範囲を WKT にできない場合（交差が空・簡略化しても大きすぎる）は None
    """

    method: CoverageMethod
    requested_area_sqkm: float | None = None
    ratio: float | None = None
    polygon: str | None = None


@dataclass(frozen=True)
class SceneWarning:
    """シーン選定の警告（ジョブ自体は失敗しない）

    Attributes:
        code: 警告コード（LOW_AOI_COVERAGE, CREDITS_NOT_ESTIMABLE など）
        message: 人間向けの説明
    """

    code: str
    message: str


@dataclass(frozen=True)
class PreviewCredits:
    """投入前プレビューが返すクレジット情報

    `estimated` が None のときは「かからない」ではなく「投入前には確定しない」。
    0 として表示してはならない（理由は `AnalysisPreview.warnings` の
    `CREDITS_NOT_ESTIMABLE` で返る）。

    見積もりは要求範囲の面積から出すが、実際の課金は NoData を除いた実処理面積で
    決まるため、実消費が見積もりを上回ることはない。

    Attributes:
        estimated: 消費見込み。確定しない入力では None
        balance: 現在の残高
        sufficient: 足りるか。`estimated` が None なら判定できないので None
    """

    estimated: float | None = None
    balance: float | None = None
    sufficient: bool | None = None

    @property
    def shortfall(self) -> float | None:
        """残高の不足額。足りている場合は 0.0、判定できない場合は None"""
        if self.estimated is None or self.balance is None:
            return None
        return max(0.0, self.estimated - self.balance)


@dataclass(frozen=True)
class AnalysisPreview:
    """投入前プレビューの結果（取得時点のスナップショット、不変）

    ジョブは作られず、クレジットも消費されない。残高不足はエラーではなく
    `credits.sufficient=False` として返る（いくら足りないかを知ることが
    プレビューの目的の一つのため）。

    Attributes:
        endpoint_id: 解析種別（`AnalysisType` の値と同じ文字列）
        credits: 消費見込みと残高
        area_sqkm: 解析される見込みの面積（km²）
        coverage: 指定範囲のうち解析される見込みの割合。推定できない入力では None
        warnings: 投入前に分かる警告（実行しない判断に使える）
    """

    endpoint_id: str
    credits: PreviewCredits
    area_sqkm: float | None = None
    coverage: Coverage | None = None
    warnings: tuple[SceneWarning, ...] = ()
