#!/usr/bin/env python3
"""衛星アニメーションのギャラリー（受信＝ダウンリンク テーマ）

「衛星からデータを受信している」イメージのアスキーアニメーションを複数まとめて
順番に再生し、見比べられるサンプル。本番 CLI の `SatelliteSpinner` に描画関数
（RenderFn）を差し替えて表示する。

実行方法（対話端末で）:

    python examples/spinner_gallery.py

注意: stderr が TTY のときだけアニメーションする（本番 CLI と同じ挙動）。
各案はそれぞれ約6秒再生する。
"""

from __future__ import annotations

import sys
import time

from sateais._spinner import SatelliteSpinner

_DURATION = 6.0  # 各案の再生秒数


def _place(row: list[str], s: str, x: int) -> None:
    """文字列 s を行 row の x 列目に書き込む（はみ出しは無視）"""
    for i, ch in enumerate(s):
        if 0 <= x + i < len(row):
            row[x + i] = ch


def render_downlink(frame: int, status: str) -> list[str]:
    """案1: 衛星からデータのかたまりが受信アンテナへ降ってくる"""
    width = 26
    center = 12
    drift = (0, 1, 0, -1)[frame % 4]
    sat_x = center - 3 + drift
    rows = [list(" " * width) for _ in range(6)]

    _place(rows[0], "=|[o]|=", sat_x)  # 衛星
    _place(rows[0], ")" * (frame % 3 + 1), sat_x + 8)  # 送信波

    glyphs = "10░▒▓"  # 降ってくるデータ（ビット + SAR テクスチャ）
    for r in range(1, 5):
        for k in range(-r, r + 1):  # 下に広がるダウンリンク・ビーム
            if (frame + r * 2 + k) % 3 == 0:
                _place(rows[r], glyphs[(frame + r + k) % len(glyphs)], center + k)

    _place(rows[5], "\\___Y___/", center - 4)  # 受信アンテナ

    rx = "[*]" if frame % 2 == 0 else "[ ]"
    lines = ["".join(r) for r in rows]
    lines.append("   ==========  " + f"{rx} RX receiving {status}{'.' * (frame % 4)}")
    return lines


def render_dish(frame: int, status: str) -> list[str]:
    """案2: パラボラアンテナが衛星からの電波を受信する"""
    width = 28
    rows = [list(" " * width) for _ in range(7)]

    sat_x = 17 + (0, 1, 2, 1)[frame % 4]  # 右上を漂う衛星
    _place(rows[0], "=|[o]|=", sat_x)

    for i, (ry, rx) in enumerate(((1, 14), (2, 11), (3, 8))):  # 降りてくる電波の弧
        if (frame + i) % 3 != 0:
            _place(rows[ry], ")", rx)
            _place(rows[ry], ")", rx + 2)

    _place(rows[4], "\\     /", 2)  # パラボラ（上向き）
    _place(rows[5], " \\___/ ", 2)
    _place(rows[6], "===|===", 2)

    led = "(*)" if frame % 2 == 0 else "( )"
    lines = ["".join(r) for r in rows]
    lines[6] = lines[6] + f"  {led} downlink {status}{'.' * (frame % 4)}"
    return lines


# 表示する案（タイトル, 描画関数）
_GALLERY = (
    ("案1: ダウンリンク（データが降ってくる）", render_downlink),
    ("案2: パラボラ受信（電波の弧）", render_dish),
)


def main() -> int:
    if not sys.stderr.isatty():
        print(
            "アニメーションは TTY でのみ表示されます。"
            "対話端末で直接実行してください（パイプ / リダイレクト不可）。",
            file=sys.stderr,
        )
        return 0

    statuses = ("queued", "pending", "processing")
    for title, render in _GALLERY:
        print(f"\n=== {title} ===", file=sys.stderr)
        with SatelliteSpinner(render=render) as spinner:
            for i in range(int(_DURATION / 0.6)):
                spinner.set_status(statuses[min(i // 3, len(statuses) - 1)])
                time.sleep(0.6)

    print("\nどの案がよいか教えてください（本番 CLI の表示に差し替えられます）。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
