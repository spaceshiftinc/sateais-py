"""エンティティ + DetectionRequest.validate のテスト"""

from __future__ import annotations

import pytest

from sateais import (
    DetectionRequest,
    DetectionType,
    InvalidDetectionRequestError,
    Job,
    JobStatus,
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


class TestDetectionType:
    def test_input_pattern_flags(self) -> None:
        assert DetectionType.SHIP.accepts_scene_or_polygon_date
        assert DetectionType.OILSLICK.accepts_scene_or_polygon_date
        assert not DetectionType.NEWBUILDING.accepts_scene_or_polygon_date

        assert DetectionType.NEWBUILDING.requires_date_range
        assert DetectionType.DISAPPEARBUILDING.requires_date_range
        assert DetectionType.TIMESERIES.requires_date_range
        assert not DetectionType.SHIP.requires_date_range


class TestDetectionRequestValidate:
    def test_ship_with_scene_id_ok(self) -> None:
        DetectionRequest(DetectionType.SHIP, scene_id="S1A_X").validate()

    def test_ship_with_polygon_and_date_ok(self) -> None:
        DetectionRequest(DetectionType.SHIP, polygon="POLY", date="2024-06-15").validate()

    def test_ship_with_neither_raises(self) -> None:
        with pytest.raises(InvalidDetectionRequestError):
            DetectionRequest(DetectionType.SHIP).validate()

    def test_ship_with_both_raises(self) -> None:
        with pytest.raises(InvalidDetectionRequestError):
            DetectionRequest(
                DetectionType.SHIP, scene_id="S1A_X", polygon="POLY", date="2024-01-01"
            ).validate()

    def test_newbuilding_requires_all_three(self) -> None:
        with pytest.raises(InvalidDetectionRequestError):
            DetectionRequest(DetectionType.NEWBUILDING, polygon="POLY").validate()

    def test_newbuilding_with_date_range_ok(self) -> None:
        DetectionRequest(
            DetectionType.NEWBUILDING,
            polygon="POLY",
            date_start="2024-01-01",
            date_end="2024-12-01",
        ).validate()


class TestDetectionRequestToBody:
    def test_drops_none_fields(self) -> None:
        body = DetectionRequest(
            DetectionType.NEWBUILDING,
            polygon="POLY",
            date_start="2024-01-01",
            date_end="2024-12-01",
        ).to_body()
        assert "orbit_direction" not in body
        assert "scene_id" not in body
        assert body["polygon"] == "POLY"
        assert body["satellite_id"] == "sentinel-1"
