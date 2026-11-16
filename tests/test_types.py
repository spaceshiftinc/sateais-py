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

    def test_result_is_archive_follows_result_path(self) -> None:
        assert Job(
            "a", JobStatus.COMPLETED, result_path="/api/v1/jobs/a/result.zip"
        ).result_is_archive
        assert not Job(
            "a", JobStatus.COMPLETED, result_path="/api/v1/jobs/a/result.geojson"
        ).result_is_archive
        assert not Job("a", JobStatus.PROCESSING).result_is_archive


class TestAnalysisType:
    def test_input_pattern_flags(self) -> None:
        assert AnalysisType.SHIP.accepts_scene_or_polygon_date
        assert AnalysisType.OILSLICK.accepts_scene_or_polygon_date
        assert not AnalysisType.NEWBUILDING.accepts_scene_or_polygon_date

        assert AnalysisType.NEWBUILDING.requires_date_range
        assert AnalysisType.DISAPPEARBUILDING.requires_date_range
        assert AnalysisType.TIMESERIES.requires_date_range
        assert not AnalysisType.SHIP.requires_date_range

        assert AnalysisType.LULC.requires_month
        assert not AnalysisType.LULC.accepts_scene_or_polygon_date
        assert not AnalysisType.LULC.requires_date_range
        assert not AnalysisType.TIMESERIES.requires_month

        assert AnalysisType.EMBANKMENT.requires_date_range
        assert not AnalysisType.EMBANKMENT.requires_month

    def test_default_satellite_id(self) -> None:
        assert AnalysisType.LULC.default_satellite_id == "sentinel-2"
        assert AnalysisType.EMBANKMENT.default_satellite_id == "sentinel-2"
        assert AnalysisType.SHIP.default_satellite_id == "sentinel-1"

    def test_fixed_satellite_and_orbit_direction(self) -> None:
        assert AnalysisType.EMBANKMENT.fixed_satellite_id == "sentinel-2"
        assert AnalysisType.NEWBUILDING.fixed_satellite_id is None
        assert not AnalysisType.EMBANKMENT.accepts_orbit_direction
        assert not AnalysisType.LULC.accepts_orbit_direction
        assert AnalysisType.TIMESERIES.accepts_orbit_direction


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


class TestAnalysisRequestValidateLulc:
    def _lulc(self, **kwargs: str) -> AnalysisRequest:
        params = {"satellite_id": "sentinel-2", "polygon": "POLY", "month": "2026-08"}
        params.update(kwargs)
        return AnalysisRequest(AnalysisType.LULC, **params)

    def test_polygon_and_month_ok(self) -> None:
        self._lulc().validate()

    @pytest.mark.parametrize("missing", ["polygon", "month"])
    def test_requires_polygon_and_month(self, missing: str) -> None:
        with pytest.raises(InvalidAnalysisRequestError, match="requires polygon and month"):
            self._lulc(**{missing: ""}).validate()

    @pytest.mark.parametrize(
        "field",
        ["scene_id", "date", "date_start", "date_end", "date_direction", "orbit_direction"],
    )
    def test_rejects_other_inputs(self, field: str) -> None:
        with pytest.raises(InvalidAnalysisRequestError, match=field):
            self._lulc(**{field: "x"}).validate()

    def test_requires_sentinel_2(self) -> None:
        # dataclass の既定 satellite_id は sentinel-1 なので、直接組み立てた場合に弾く
        with pytest.raises(InvalidAnalysisRequestError, match="sentinel-2"):
            AnalysisRequest(AnalysisType.LULC, polygon="POLY", month="2026-08").validate()

    def test_other_types_reject_month(self) -> None:
        with pytest.raises(InvalidAnalysisRequestError, match="does not accept month"):
            AnalysisRequest(AnalysisType.SHIP, scene_id="S1A_X", month="2026-08").validate()


class TestAnalysisRequestValidateEmbankment:
    def _embankment(self, **kwargs: str) -> AnalysisRequest:
        params = {
            "satellite_id": "sentinel-2",
            "polygon": "POLY",
            "date_start": "2025-05-01",
            "date_end": "2026-05-01",
        }
        params.update(kwargs)
        return AnalysisRequest(AnalysisType.EMBANKMENT, **params)

    def test_polygon_and_date_range_ok(self) -> None:
        self._embankment().validate()

    @pytest.mark.parametrize("missing", ["polygon", "date_start", "date_end"])
    def test_requires_polygon_and_date_range(self, missing: str) -> None:
        with pytest.raises(InvalidAnalysisRequestError, match="requires polygon"):
            self._embankment(**{missing: ""}).validate()

    def test_rejects_orbit_direction(self) -> None:
        # Sentinel-2 には効かず API が黙って無視するので、投入前に止める
        with pytest.raises(InvalidAnalysisRequestError, match="orbit_direction"):
            self._embankment(orbit_direction="ascending").validate()

    @pytest.mark.parametrize("satellite_id", ["sentinel-1", "alos-2"])
    def test_requires_sentinel_2(self, satellite_id: str) -> None:
        with pytest.raises(InvalidAnalysisRequestError, match="sentinel-2"):
            self._embankment(satellite_id=satellite_id).validate()

    def test_rejects_month(self) -> None:
        with pytest.raises(InvalidAnalysisRequestError, match="does not accept month"):
            self._embankment(month="2026-08").validate()

    def test_other_date_range_types_still_accept_orbit_direction(self) -> None:
        AnalysisRequest(
            AnalysisType.NEWBUILDING,
            polygon="POLY",
            date_start="2025-01-01",
            date_end="2025-06-30",
            orbit_direction="ascending",
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
