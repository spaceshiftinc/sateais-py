#!/usr/bin/env python3
"""衛星「信号パルス」アニメーションのデモ（本番 CLI の既定表示）

`--wait` で表示される待機アニメーションを、API キーやジョブ投入なしで確認するための
サンプルスクリプト。ジョブが queued → pending → processing と進む様子を擬似再現する。

実行方法（対話端末で）:

    python examples/spinner_demo.py

挙動:

- 標準出力が TTY のときだけアニメーションする（約 9fps、Ctrl-C でカーソル復帰）。
- パイプ / リダイレクト時や `NO_COLOR` 指定時はアニメーションせず、
  `▭┋▣┋▭ message...` の静的な 1 行だけ出す。
"""

from __future__ import annotations

import sys
import time

from sateais._spinner import SatelliteSpinner

# (ステータス, その状態を見せておく秒数)
_TIMELINE: tuple[tuple[str, float], ...] = (
    ("queued", 2.0),
    ("pending", 3.0),
    ("processing", 4.0),
)


def main() -> int:
    # 標準出力に出す。非 TTY のときは static_text の静的 1 行にフォールバックする。
    with SatelliteSpinner(stream=sys.stdout, static_text="analyzing") as spinner:
        for status, hold in _TIMELINE:
            spinner.set_status(status)
            time.sleep(hold)

    if spinner.enabled:
        print("done: completed (これは結果の出力イメージです)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
