"""衛星スキャン・アニメーション（_spinner）のテスト

TTY 判定・有効/無効の切り替え・描画出力の中身を、TTY を装う擬似ストリームで検証する。
実時間に依存しないよう interval は 0 にし、threading の join で確実に終わらせる。
"""

from __future__ import annotations

import io
import os

import pytest

from sateais._spinner import _EMIT_STEPS, _LOOP, SatelliteSpinner, _make_render, _render


class _FakeTTY(io.StringIO):
    """isatty() が True を返す StringIO（対話端末のふり）"""

    def isatty(self) -> bool:
        return True


def test_render_has_satellite_body_and_status() -> None:
    line = _render(frame=0, status="pending")[0]
    assert "▭┋▣┋▭" in line  # 衛星本体（パネル ▭ ┋ 機体 ▣ ┋ パネル ▭）
    assert "pending" in line  # ステータス表示


def test_source_bright_on_emit_frames_dim_otherwise() -> None:
    # 発射フレーム（ループ内 {0,2,8,10}）だけ送信源が明（◉）、それ以外は暗（◎）
    for step in range(_LOOP):
        line = _render(frame=step, status="x")[0]
        if step in _EMIT_STEPS:
            assert "◉" in line and "◎" not in line, f"step={step}"
        else:
            assert "◎" in line and "◉" not in line, f"step={step}"


def test_heartbeat_quiet_gap_has_no_new_source_flash() -> None:
    # ハートビートの「間」では発射しない（例: step 4..7 は非発射）
    for step in (4, 5, 6, 7, 12, 13, 14, 15):
        assert step not in _EMIT_STEPS


def test_render_waves_flow_between_frames() -> None:
    # 信号波の位置はフレームごとに変化する（右へ流れる）
    first = _render(frame=1, status="x")[0]
    later = _render(frame=2, status="x")[0]
    assert first != later


def test_color_render_uses_teal_truecolor_escape() -> None:
    # カラー版は送信源にティール truecolor（発射時は全輝度 29;158;117）を使う
    line = _make_render(color=True)(frame=0, status="x")[0]
    assert "\x1b[38;2;29;158;117m" in line


def test_noncolor_far_wave_uses_dot_glyph() -> None:
    # 非カラー版は遠い波を `·` で表す（距離 3 段階の最遠ゾーン）
    # frame=0 では距離 6,8,14 に波が出る → 最遠の 14 は '·'
    line = _render(frame=0, status="x")[0]
    assert "·" in line


def test_static_line_when_disabled_and_text_given() -> None:
    stream = io.StringIO()
    with SatelliteSpinner(stream=stream, static_text="loading"):
        pass
    assert stream.getvalue() == "▭┋▣┋▭ loading...\n"


def test_disabled_when_stream_is_not_tty() -> None:
    spinner = SatelliteSpinner(stream=io.StringIO())
    assert spinner.enabled is False


def test_disabled_when_no_color_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    spinner = SatelliteSpinner(stream=_FakeTTY())
    assert spinner.enabled is False


def test_disabled_when_terminal_too_narrow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.get_terminal_size", lambda fallback=(80, 24): _size(20))
    spinner = SatelliteSpinner(stream=_FakeTTY())
    assert spinner.enabled is False


def test_disabled_spinner_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = io.StringIO()
    with SatelliteSpinner(stream=stream) as spinner:
        spinner.set_status("pending")
    assert stream.getvalue() == ""


def test_enabled_spinner_animates_and_cleans_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr("shutil.get_terminal_size", lambda fallback=(80, 24): _size(80))
    stream = _FakeTTY()
    with SatelliteSpinner(stream=stream, interval=0) as spinner:
        assert spinner.enabled is True
        spinner.set_status("pending")
    out = stream.getvalue()
    assert "\x1b[?25l" in out  # カーソル非表示
    assert "\x1b[?25h" in out  # カーソル復帰
    assert "▭┋▣┋▭" in out  # 衛星が描画された


def _size(columns: int) -> os.terminal_size:
    """shutil.get_terminal_size のスタブ。

    pytest 自身も `width, _ = shutil.get_terminal_size(...)` で戻り値を
    アンパックするため、本物と同じアンパック可能な os.terminal_size を返す。
    """
    return os.terminal_size((columns, 24))
