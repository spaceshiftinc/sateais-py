"""隠し要素（_fun）のテスト

純粋関数（シーンIDデコード）と描画関数の不変条件（行数一定）を検証する。
アニメーション自体は TTY 依存のため、ここでは描画関数の構造だけを確認する。
"""

from __future__ import annotations

import pytest

from sateais._fun import (
    make_aurora_render,
    make_decode_render,
    make_nightsky_render,
    parse_scene_id,
    render_orbit,
    render_ping,
)


def test_parse_scene_id_grd() -> None:
    info = parse_scene_id(
        "S1A_IW_GRDH_1SDV_20240101T000000_20240101T000025_052345_065ABC_1A2B"
    )
    assert info["mission"] == "Sentinel-1A"
    assert info["mode"] == "Interferometric Wide swath"
    assert info["product"] == "Ground Range Detected"
    assert info["resolution"] == "High"
    assert info["level"] == "L1"
    assert info["polarisation"] == "dual VV+VH"
    assert info["start"] == "2024-01-01 00:00:00 UTC"
    assert info["absolute_orbit"] == "52345"
    # 相対軌道 = (52345 - 73) % 175 + 1
    assert info["relative_orbit"] == str((52345 - 73) % 175 + 1)
    assert info["data_take"] == "065ABC"


def test_parse_scene_id_slc_double_underscore() -> None:
    # SLC は製品種別がパディング下線で割れる（SLC_ → 'SLC' + ''）
    info = parse_scene_id(
        "S1B_IW_SLC__1SSV_20200615T120000_20200615T120025_022000_029ABC_DEAD"
    )
    assert info["mission"] == "Sentinel-1B"
    assert info["product"] == "Single Look Complex"
    assert info["polarisation"] == "single VV"
    # S1B のオフセットは 27
    assert info["relative_orbit"] == str((22000 - 27) % 175 + 1)


def test_parse_scene_id_strips_extension() -> None:
    info = parse_scene_id(
        "S1A_IW_GRDH_1SDV_20240101T000000_20240101T000025_052345_065ABC_1A2B.SAFE"
    )
    assert info["mission"] == "Sentinel-1A"


@pytest.mark.parametrize("bad", ["", "not-a-scene", "S1A_IW_GRDH", "hello_world_foo"])
def test_parse_scene_id_invalid_raises(bad: str) -> None:
    with pytest.raises(ValueError, match="Sentinel-1 scene ID"):
        parse_scene_id(bad)


@pytest.mark.parametrize(
    "render",
    [
        render_orbit,
        render_ping,
        make_nightsky_render(False),
        make_aurora_render(False),
        make_decode_render("SATEAIS"),
    ],
)
def test_render_line_count_is_constant(render) -> None:  # type: ignore[no-untyped-def]
    # カーソル制御の前提として、行数はフレームによらず一定でなければならない
    counts = {len(render(f, "")) for f in (0, 1, 5, 17, 42)}
    assert len(counts) == 1


def test_decode_reveals_text_over_time() -> None:
    render = make_decode_render("ABC")
    # 十分に進めれば本文がそのまま現れる
    last = render(999, "")
    assert "ABC" in last[1]
