"""エンティティ + AnalysisRequest.validate のテスト"""

from __future__ import annotations

import pytest

from sateais import (
    AnalysisRequest,
    AnalysisType,
    CoverageMethod,
    InvalidAnalysisRequestError,
    Job,
    JobStatus,
    PreviewCredits,
)


class TestJobStatus:
    def test_parse_known(self) -> None:
        assert JobStatus.parse("pending") is JobStatus.PENDING
        assert JobStatus.parse("completed") is JobStatus.COMPLETED

    def test_parse_unknown_falls_back(self) -> None:
        assert JobStatus.parse(None) is JobStatus.UNKNOWN
        assert JobStatus.parse("alien") is JobStatus.UNKNOWN


class TestJob:
    def test_terminal_flags(self) -> None:
        pending = Job("a", JobStatus.PENDING)
        completed = Job("a", JobStatus.COMPLETED)
        failed = Job("a", JobStatus.FAILED, error_code="X")

        assert not pending.is_terminal
        assert completed.is_terminal and completed.is_completed
        assert failed.is_terminal and failed.is_failed


class TestAnalysisType:
    def test_input_pattern_flags(self) -> None:
        assert AnalysisType.SHIP.accepts_scene_or_polygon_date
        assert AnalysisType.OILSLICK.accepts_scene_or_polygon_date
        assert not AnalysisType.NEWBUILDING.accepts_scene_or_polygon_date

        assert AnalysisType.NEWBUILDING.requires_date_range
        assert AnalysisType.DISAPPEARBUILDING.requires_date_range
        assert AnalysisType.TIMESERIES.requires_date_range
        assert not AnalysisType.SHIP.requires_date_range


class TestAnalysisRequestValidate:
    def test_ship_with_scene_id_ok(self) -> None:
        AnalysisRequest(AnalysisType.SHIP, scene_id="S1A_X").validate()

    def test_ship_with_polygon_and_date_ok(self) -> None:
        AnalysisRequest(AnalysisType.SHIP, polygon="POLY", date="2024-06-15").validate()

    def test_ship_with_neither_raises(self) -> None:
        with pytest.raises(InvalidAnalysisRequestError):
            AnalysisRequest(AnalysisType.SHIP).validate()

    def test_ship_with_both_raises(self) -> None:
        with pytest.raises(InvalidAnalysisRequestError):
            AnalysisRequest(
                AnalysisType.SHIP, scene_id="S1A_X", polygon="POLY", date="2024-01-01"
            ).validate()

    def test_newbuilding_requires_all_three(self) -> None:
        with pytest.raises(InvalidAnalysisRequestError):
            AnalysisRequest(AnalysisType.NEWBUILDING, polygon="POLY").validate()

    def test_newbuilding_with_date_range_ok(self) -> None:
        AnalysisRequest(
            AnalysisType.NEWBUILDING,
            polygon="POLY",
            date_start="2024-01-01",
            date_end="2024-12-01",
        ).validate()


class TestAnalysisRequestToBody:
    def test_drops_none_fields(self) -> None:
        body = AnalysisRequest(
            AnalysisType.NEWBUILDING,
            polygon="POLY",
            date_start="2024-01-01",
            date_end="2024-12-01",
        ).to_body()
        assert "orbit_direction" not in body
        assert "scene_id" not in body
        assert body["polygon"] == "POLY"
        assert body["satellite_id"] == "sentinel-1"


class TestCoverageMethod:
    def test_known_values_parse(self) -> None:
        assert CoverageMethod.parse("measured") is CoverageMethod.MEASURED
        assert CoverageMethod.parse("estimated") is CoverageMethod.ESTIMATED

    def test_unknown_and_missing_fall_back_to_unknown(self) -> None:
        assert CoverageMethod.parse("weird") is CoverageMethod.UNKNOWN
        assert CoverageMethod.parse(None) is CoverageMethod.UNKNOWN


class TestPreviewCredits:
    def test_shortfall_is_zero_when_balance_is_enough(self) -> None:
        assert PreviewCredits(estimated=10.0, balance=30.0, sufficient=True).shortfall == 0.0

    def test_shortfall_is_the_missing_amount(self) -> None:
        assert PreviewCredits(estimated=50.0, balance=30.0, sufficient=False).shortfall == 20.0

    def test_shortfall_is_none_when_estimate_is_not_available(self) -> None:
        # estimated=None は「かからない」ではなく「投入前には確定しない」
        assert PreviewCredits(estimated=None, balance=30.0).shortfall is None
