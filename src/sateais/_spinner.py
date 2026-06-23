"""待機中に表示する遊び心のある衛星「信号パルス」アスキーアニメーション

ジョブ完了待ちの間、ターミナルに「衛星が右へ信号波を流している」様子を 1 行で
アニメーション表示する delivery 層のユーティリティ。波は送信源から発生して毎フレーム
右へ進み、距離に応じて減衰する。発射リズムは心拍（ハートビート）パターン。

見た目（1 行）例::

    ▭┋▣┋▭─◉ )  )   )

- 左に衛星本体 `▭┋▣┋▭`（中央 `▣` が機体、両脇 `▭` がソーラーパネル）
- すぐ右に短いブーム `─` と送信源 `◉`（発射フレーム）/ `◎`（非発射フレーム）
- 送信源から右へ信号波 `)` が流れる

設計方針:

- **出力先が TTY のときだけ動く**。パイプ/リダイレクト/テスト時は無効化され、
  呼び出し側は 1 行ログにフォールバックできる（`enabled` 属性で判定）。
  `static_text` を渡せば、非 TTY 時に `▭┋▣┋▭ メッセージ...` の静的 1 行を出す。
- カラー対応端末（truecolor）ではティール系で距離減衰を表現し、非対応端末では
  グリフの濃淡（`) → ) → ·`）で代用する。
- 標準ライブラリのみに依存（`os` / `shutil` / `sys` / `threading`）。
- アニメーションは daemon スレッドで回し、`set_status()` で表示ステータスだけ更新する。
"""

from __future__ import annotations

import os
import shutil
import sys
import threading
from collections.abc import Callable
from types import TracebackType
from typing import IO

# フレーム番号と表示ステータスから複数行の描画文字列を返す描画関数の型
RenderFn = Callable[[int, str], list[str]]

# ANSI 制御シーケンス
_ESC = "\x1b"
_CLEAR_EOL = f"{_ESC}[K"  # カーソル位置から行末までクリア
_HIDE_CURSOR = f"{_ESC}[?25l"
_SHOW_CURSOR = f"{_ESC}[?25h"
_RESET = f"{_ESC}[0m"

# 衛星の構成要素
_BODY = "▭┋▣┋▭"  # 衛星本体（パネル ▭ ┋ 機体 ▣ ┋ パネル ▭）
_BOOM = "─"  # 送信源へつながる短いブーム
_SRC_ON = "◉"  # 発射フレームの送信源（明）
_SRC_OFF = "◎"  # 非発射フレームの送信源（暗）
_WAVE = ")"  # 信号波

# 信号波の挙動
_FIELD_W = 16  # 表示幅（端に達した波は消える）
_LOOP = 16  # ハートビート 1 ループのフレーム数
_EMIT_STEPS = frozenset({0, 2, 8, 10})  # 波を撃つループ内フレーム（ピッ・ピッ……ピッ・ピッ）

# 減衰表現
_TEAL = (29, 158, 117)  # カラー端末の基本色（ティール）
_GLYPH_TIERS = (")", ")", "·")  # 非カラー端末の距離 3 段階（近 → 遠）

_MARGIN = "  "  # 左余白
_MIN_TERM_W = 40  # これ未満の端末幅ではアニメーションしない
_INTERVAL = 0.11  # フレーム間隔（秒, 約 9fps）


def _teal(brightness: float) -> str:
    """ティール基本色を brightness 倍した truecolor 前景色エスケープを返す"""
    r, g, b = (round(c * brightness) for c in _TEAL)
    return f"{_ESC}[38;2;{r};{g};{b}m"


def _make_render(color: bool) -> RenderFn:
    """信号パルス描画関数を生成する（color でカラー / グリフ濃淡を切り替える）

    距離 `d` の波が現在フレームに存在する条件は `(frame - d) % _LOOP in _EMIT_STEPS`。
    これは「位置 0 で発射 → 毎フレーム右へ 1 進む」を閉じた式で表したもの。
    """

    def render(frame: int, status: str) -> list[str]:
        cells: list[str] = []
        for d in range(1, _FIELD_W):  # 距離 1.._FIELD_W-1（_FIELD_W に達したら消える）
            if (frame - d) % _LOOP not in _EMIT_STEPS:
                cells.append(" ")
                continue
            if color:
                # 遠いほど暗く（明度 max(0.18, 1 - 距離/幅) 倍）
                cells.append(f"{_teal(max(0.18, 1 - d / _FIELD_W))}{_WAVE}{_RESET}")
            else:
                zone = min((d - 1) * len(_GLYPH_TIERS) // (_FIELD_W - 1), len(_GLYPH_TIERS) - 1)
                cells.append(_GLYPH_TIERS[zone])

        firing = frame % _LOOP in _EMIT_STEPS
        src = _SRC_ON if firing else _SRC_OFF
        if color:
            src = f"{_teal(1.0 if firing else 0.45)}{src}{_RESET}"

        dots = "." * (frame % 4)
        return [f"{_MARGIN}{_BODY}{_BOOM}{src} {''.join(cells)}  {status}{dots}"]

    return render


# 既定の描画関数（非カラー）。テストや非カラー端末で使う。
_render = _make_render(color=False)


class SatelliteSpinner:
    """衛星「信号パルス」アニメーションを表示する context manager

    Example:
        >>> with SatelliteSpinner() as spinner:
        ...     spinner.set_status("pending")  # ポーリングごとに更新

    Args:
        stream: 出力先。未指定なら stderr。
        interval: フレーム間隔（秒）。
        render: 描画関数の差し替え。未指定なら端末のカラー対応に応じた既定を使う。
        static_text: 非 TTY 時に `▭┋▣┋▭ {static_text}...` の静的 1 行を出す。
                     None なら非 TTY 時は何も出さない（CLI のログ表示にフォールバック）。
    """

    def __init__(
        self,
        stream: IO[str] | None = None,
        *,
        interval: float = _INTERVAL,
        render: RenderFn | None = None,
        static_text: str | None = None,
    ) -> None:
        self._stream: IO[str] = stream if stream is not None else sys.stderr
        self._interval = interval
        self._status = "queued"
        self._static_text = static_text
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._first = True
        self._line_count = 0  # 直近に描画した行数（消去時に使う）
        self.enabled = self._should_animate()
        self.color = self._supports_truecolor()
        self._render = render if render is not None else _make_render(self.color)

    def _should_animate(self) -> bool:
        """TTY かつ十分な端末幅がある場合のみ True

        `NO_COLOR` は色の規約であって動きの抑制ではないため、アニメ可否の
        判定には用いない（モノクロでアニメーションは継続する）。
        """
        isatty = getattr(self._stream, "isatty", None)
        if not (callable(isatty) and isatty()):
            return False
        width = shutil.get_terminal_size(fallback=(80, 24)).columns
        return width >= _MIN_TERM_W

    def _supports_truecolor(self) -> bool:
        """truecolor（24bit カラー）対応端末かどうか（NO_COLOR を尊重）"""
        if not self.enabled or os.environ.get("NO_COLOR"):
            return False
        return os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit")

    def set_status(self, status: str) -> None:
        """表示中のステータス文字列を差し替える（スレッドセーフ）"""
        with self._lock:
            self._status = status

    def __enter__(self) -> SatelliteSpinner:
        if self.enabled:
            self._stream.write(_HIDE_CURSOR)
            self._stream.flush()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        elif self._static_text is not None:
            # 非 TTY: アニメーションせず静的な 1 行だけ出す
            self._stream.write(f"{_BODY} {self._static_text}...\n")
            self._stream.flush()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        if self.enabled:
            self._erase()
            self._stream.write(_SHOW_CURSOR)
            self._stream.flush()

    def _run(self) -> None:
        frame = 0
        while not self._stop.is_set():
            with self._lock:
                status = self._status
            self._paint(self._render(frame, status))
            frame += 1
            self._stop.wait(self._interval)

    def _paint(self, lines: list[str]) -> None:
        """複数行を所定位置に再描画する（2 回目以降はカーソルを先頭行へ戻す）"""
        buf: list[str] = []
        # 2 行以上のときだけ先頭行へカーソルを戻す。1 行描画では \r だけで足り、
        # ESC[0A は端末仕様（ECMA-48）上「1 行上へ」と解釈され行がせり上がってしまう。
        if not self._first and self._line_count > 1:
            buf.append(f"{_ESC}[{self._line_count - 1}A")
        for i, line in enumerate(lines):
            # 行頭へ戻して上書きし、末尾の残りを行末クリアで消す
            buf.append("\r" + line + _CLEAR_EOL)
            if i != len(lines) - 1:
                buf.append("\n")
        self._stream.write("".join(buf))
        self._stream.flush()
        self._first = False
        self._line_count = len(lines)

    def _erase(self) -> None:
        """描画した行をすべて消去し、カーソルを先頭行の行頭へ戻す"""
        if self._first or self._line_count == 0:
            return
        buf: list[str] = []
        for i in range(self._line_count):
            buf.append("\r" + _CLEAR_EOL)
            if i != self._line_count - 1:
                buf.append(f"{_ESC}[1A")
        self._stream.write("".join(buf))
        self._stream.flush()
