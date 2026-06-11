"""遊び心のある隠し要素の実装（CLI 専用・stdlib のみ依存）

`cli.py` を肥大させないため、隠しコマンドの描画関数・パーサ・アスキー図解を集約する。
すべて公開 API ではない（`_` 始まりモジュール）。アニメーション系は
`SatelliteSpinner` の `render=` に渡す `RenderFn`（`(frame, status) -> list[str]`）として実装し、
各フレームの行数は一定に保つ（カーソル制御の前提）。

設計方針:

- 依存は `math` / `os` / `random` のみ。`SatelliteSpinner` には依存しない（描画関数を渡すだけ）。
- カラーは truecolor 対応端末でのみ使い、非対応時はグリフ濃淡で代用する。
- 各種コマンドの会社カラー（Sentinel-1 / SAR / MVV）をキャプションに織り込む。
"""

from __future__ import annotations

import math
import os
import random
import re
from collections.abc import Callable

# (frame, status) -> 複数行の描画文字列
RenderFn = Callable[[int, str], list[str]]

_ESC = "\x1b"
_RESET = f"{_ESC}[0m"


def _fg(r: int, g: int, b: int) -> str:
    """truecolor 前景色のエスケープシーケンスを返す"""
    return f"{_ESC}[38;2;{r};{g};{b}m"


def supports_truecolor() -> bool:
    """truecolor（24bit カラー）対応端末かどうか（NO_COLOR を尊重）"""
    if os.environ.get("NO_COLOR"):
        return False
    return os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit")


# ===========================================================================
# orbit: 衛星が地球を周回するループアニメ
# ===========================================================================

_ORBIT_H = 9
_ORBIT_W = 31


def render_orbit(frame: int, status: str) -> list[str]:
    """地球 `⊕` の周りを衛星 `▣` が周回する（10 行固定）"""
    del status
    cx, cy = _ORBIT_W // 2, _ORBIT_H // 2
    rx, ry = 13, 3
    grid = [[" "] * _ORBIT_W for _ in range(_ORBIT_H)]

    # 軌道のガイド点線
    for deg in range(0, 360, 15):
        a = math.radians(deg)
        gx = cx + round(rx * math.cos(a))
        gy = cy + round(ry * math.sin(a))
        if 0 <= gy < _ORBIT_H and 0 <= gx < _ORBIT_W and grid[gy][gx] == " ":
            grid[gy][gx] = "·"

    grid[cy][cx] = "⊕"  # 地球（中心）

    # 衛星（周回）と直前のフレーム位置の淡い残像
    for offset, glyph in ((-0.30, "+"), (0.0, "▣")):
        a = frame * 0.30 + offset
        sx = cx + round(rx * math.cos(a))
        sy = cy + round(ry * math.sin(a))
        if 0 <= sy < _ORBIT_H and 0 <= sx < _ORBIT_W:
            grid[sy][sx] = glyph

    lines = ["".join(row) for row in grid]
    lines.append("   Sentinel-1  ·  LEO ~693 km")
    return lines


ORBIT_STILL = "\n".join(render_orbit(0, ""))


# ===========================================================================
# ping: 地上局 → 衛星 → 地上局 の通信往復
# ===========================================================================

_PING_H = 7
_PING_W = 36
_PING_STEPS = 16


def render_ping(frame: int, status: str) -> list[str]:
    """地上局 `[≡]` と衛星 `▣` の間をパルス `◉` が往復する（8 行固定）"""
    del status
    grid = [[" "] * _PING_W for _ in range(_PING_H)]
    sat = (0, _PING_W - 4)
    gnd = (_PING_H - 1, 0)

    # 経路（地上局→衛星の直線）を点で描く
    path: list[tuple[int, int]] = []
    for i in range(_PING_STEPS + 1):
        t = i / _PING_STEPS
        r = round(gnd[0] + (sat[0] - gnd[0]) * t)
        c = round(gnd[1] + (sat[1] - gnd[1]) * t)
        path.append((r, c))
        if grid[r][c] == " ":
            grid[r][c] = "."

    # 往復するパルス（上り → 下り）
    period = 2 * _PING_STEPS
    p = frame % period
    up = p <= _PING_STEPS
    idx = p if up else period - p
    pr, pc = path[idx]
    grid[pr][pc] = "◉"

    # 衛星 ▣ と地上局 [≡] は最後に描き、端点ではパルスより前面に出す
    grid[sat[0]][sat[1]] = "▣"
    for j, ch in enumerate("[≡]"):
        grid[gnd[0]][j] = ch

    lines = ["".join(row) for row in grid]
    label = "uplink   ▲" if up else "downlink ▼"
    lines.append(f"   {label}   RTT ~5 ms")
    return lines


PING_STILL = "\n".join(render_ping(0, ""))


# ===========================================================================
# decode: 衛星ダウンリンク風タイプライター演出
# ===========================================================================

_DECODE_NOISE = "#%&$*+=?/\\|<>~"
_DECODE_HOLD = 2  # 1 文字確定までのフレーム数
_DECODE_WINDOW = 6  # 確定位置の先にノイズを出す幅


def make_decode_render(text: str) -> RenderFn:
    """`text` をノイズから 1 文字ずつ復元するタイプライター描画関数を作る（2 行固定）"""
    length = len(text)

    def render(frame: int, status: str) -> list[str]:
        del status
        reveal = min(length, frame // _DECODE_HOLD)
        chars: list[str] = []
        for i, ch in enumerate(text):
            if i < reveal:
                chars.append(ch)
            elif ch == " ":
                chars.append(" ")
            elif i < reveal + _DECODE_WINDOW:
                chars.append(random.choice(_DECODE_NOISE))
            else:
                chars.append("·")
        blink = (frame // 3) % 2 == 0 and reveal < length
        header = "  ▸ receiving telemetry ◂" if blink else "  ▸                      ◂"
        return [header, "  " + "".join(chars)]

    return render


def decode_duration(text: str) -> float:
    """decode を最後まで再生するのに十分な秒数を見積もる"""
    return max(3.0, len(text) * 0.28 + 1.5)


# ===========================================================================
# nightsky: 瞬く星空
# ===========================================================================

_SKY_H = 8
_SKY_W = 38
_SKY_GLYPHS = (" ", ".", "·", "+", "*")


def _star_field() -> list[tuple[int, int, int]]:
    """決定的に散らした星の (行, 列, 位相シード) リストを作る

    Knuth の乗法ハッシュで列を散らす（単純な線形合同では `_SKY_W` と
    係数が干渉して列が偏るため）。重複位置は除いて均す。
    """
    seen: set[tuple[int, int]] = set()
    stars: list[tuple[int, int, int]] = []
    for i in range(1, 60):
        x = (i * 2654435761) % _SKY_W
        y = (i * 40503) % _SKY_H
        if (y, x) in seen:
            continue
        seen.add((y, x))
        stars.append((y, x, i))
    return stars


_STARS = _star_field()


def make_nightsky_render(color: bool) -> RenderFn:
    """星が三角波で瞬く星空の描画関数を作る（9 行固定）"""

    def render(frame: int, status: str) -> list[str]:
        del status
        grid = [[" "] * _SKY_W for _ in range(_SKY_H)]
        for y, x, seed in _STARS:
            phase = (frame // 2 + seed) % 8
            level = phase if phase <= 4 else 8 - phase  # 0..4 の三角波
            glyph = _SKY_GLYPHS[level]
            if glyph == " ":
                continue
            if color:
                b = 90 + level * 40
                grid[y][x] = f"{_fg(b, b, min(255, b + 30))}{glyph}{_RESET}"
            else:
                grid[y][x] = glyph
        lines = ["".join(row) for row in grid]
        lines.append("   make the invisible visible")
        return lines

    return render


NIGHTSKY_STILL = "\n".join(make_nightsky_render(False)(0, ""))


# ===========================================================================
# aurora: 揺れるカラーのオーロラ
# ===========================================================================

_AURORA_H = 7
_AURORA_W = 36
_AURORA_SHADE = "░▒▓"


def make_aurora_render(color: bool) -> RenderFn:
    """カーテン状に揺らめくオーロラの描画関数を作る（8 行固定）"""

    def render(frame: int, status: str) -> list[str]:
        del status
        rows: list[str] = []
        for y in range(_AURORA_H):
            chars: list[str] = []
            for x in range(_AURORA_W):
                wave = math.sin(x / 5.0 + frame * 0.20 + y * 0.5) + math.sin(
                    x / 9.0 - frame * 0.13
                )
                band = (wave + 2) / 4  # 0..1
                level = band * (_AURORA_H - 1)
                if abs(level - y) >= 1.1:
                    chars.append(" ")
                    continue
                shade = _AURORA_SHADE[min(2, int(band * 3))]
                if color:
                    g = 150 + int(80 * math.sin(frame * 0.1 + x * 0.2))
                    chars.append(f"{_fg(40, max(80, min(230, g)), 140)}{shade}{_RESET}")
                else:
                    chars.append(shade)
            rows.append("".join(chars))
        rows.append("   from space to everyday")
        return rows

    return render


AURORA_STILL = "\n".join(make_aurora_render(False)(0, ""))


# ===========================================================================
# scene: Sentinel-1 シーンIDのデコード
# ===========================================================================

_MISSION = {
    "S1A": "Sentinel-1A",
    "S1B": "Sentinel-1B",
    "S1C": "Sentinel-1C",
}
_MODE = {
    "IW": "Interferometric Wide swath",
    "EW": "Extra Wide swath",
    "SM": "Stripmap",
    "WV": "Wave",
}
_PRODUCT = {
    "SLC": "Single Look Complex",
    "GRD": "Ground Range Detected",
    "OCN": "Ocean",
    "RAW": "Raw",
}
_RESOLUTION = {"F": "Full", "H": "High", "M": "Medium"}
_POLARISATION = {
    "SH": "single HH",
    "SV": "single VV",
    "DH": "dual HH+HV",
    "DV": "dual VV+VH",
    "HH": "HH",
    "VV": "VV",
}
# 相対軌道番号の計算に使うミッション別オフセット（ESA 定義）
_REL_ORBIT_OFFSET = {"S1A": 73, "S1B": 27}
_REL_ORBIT_CYCLE = 175

_DATETIME_RE = re.compile(r"^\d{8}T\d{6}$")


def _fmt_datetime(token: str) -> str:
    """`YYYYMMDDTHHMMSS` を `YYYY-MM-DD HH:MM:SS UTC` に整形する"""
    d, t = token.split("T")
    return f"{d[0:4]}-{d[4:6]}-{d[6:8]} {t[0:2]}:{t[2:4]}:{t[4:6]} UTC"


def parse_scene_id(scene_id: str) -> dict[str, str]:
    """Sentinel-1 のシーンIDを各フィールドにデコードする

    例: ``S1A_IW_GRDH_1SDV_20240101T000000_20240101T000025_052345_065ABC_1A2B``

    Raises:
        ValueError: Sentinel-1 のシーンIDとして解釈できない場合
    """
    sid = scene_id.strip()
    for suffix in (".SAFE", ".zip"):
        if sid.upper().endswith(suffix.upper()):
            sid = sid[: -len(suffix)]
    tokens = sid.split("_")

    # 開始/終了の日時トークンで構造をアンカーする
    dt_idx = [i for i, tok in enumerate(tokens) if _DATETIME_RE.match(tok)]
    if len(tokens) < 8 or len(dt_idx) < 2 or dt_idx[0] < 3:
        raise ValueError(f"not a Sentinel-1 scene ID: {scene_id}")

    mission = tokens[0]
    mode = tokens[1]
    # 製品種別はパディング下線で分割され得るため連結する（例: SLC + '' → SLC）
    product_raw = "".join(tokens[2 : dt_idx[0] - 1])
    lfpp = tokens[dt_idx[0] - 1]
    start, stop = tokens[dt_idx[0]], tokens[dt_idx[1]]
    tail = tokens[dt_idx[1] + 1 :]

    info: dict[str, str] = {
        "mission": _MISSION.get(mission, mission),
        "mode": _MODE.get(mode, mode),
        "product": _PRODUCT.get(product_raw[:3], product_raw[:3]),
    }
    if len(product_raw) >= 4 and product_raw[3] in _RESOLUTION:
        info["resolution"] = _RESOLUTION[product_raw[3]]
    if len(lfpp) >= 4:
        info["level"] = f"L{lfpp[0]}"
        info["polarisation"] = _POLARISATION.get(lfpp[2:4], lfpp[2:4])
    info["start"] = _fmt_datetime(start)
    info["stop"] = _fmt_datetime(stop)
    if tail:
        abs_orbit = tail[0]
        info["absolute_orbit"] = str(int(abs_orbit))
        offset = _REL_ORBIT_OFFSET.get(mission)
        if offset is not None:
            rel = (int(abs_orbit) - offset) % _REL_ORBIT_CYCLE + 1
            info["relative_orbit"] = str(rel)
    if len(tail) >= 2:
        info["data_take"] = tail[1]
    return info


# 表示順とラベル（日本語）
_SCENE_LABELS = (
    ("mission", "衛星"),
    ("mode", "観測モード"),
    ("product", "製品種別"),
    ("resolution", "解像度クラス"),
    ("level", "処理レベル"),
    ("polarisation", "偏波"),
    ("start", "取得開始"),
    ("stop", "取得終了"),
    ("absolute_orbit", "絶対軌道番号"),
    ("relative_orbit", "相対軌道番号"),
    ("data_take", "データテイクID"),
)


def format_scene_info(scene_id: str, info: dict[str, str]) -> str:
    """デコード結果を人間可読のブロックに整形する"""
    width = max(len(label) for _, label in _SCENE_LABELS)
    lines = [f"Scene ID: {scene_id.strip()}", ""]
    for key, label in _SCENE_LABELS:
        if key in info:
            lines.append(f"  {label.ljust(width)} : {info[key]}")
    lines.append("")
    lines.append("  ※ 昇交/降交（asc/desc）はシーンIDに含まれません（メタデータ参照）")
    return "\n".join(lines)
