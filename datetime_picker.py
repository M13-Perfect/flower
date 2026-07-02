"""深色风日期/时间选择器（CustomTkinter）。

用途：替代「定时抓取 · 重抓起点」原先的手填文本框——让操作员点开月历选日期 + 选时分，
而不是手敲 `2026-06-19 02:25`。输出字符串仍是 `YYYY-MM-DD HH:MM`，喂给原 `scrape_from_var`，
故上层「应用 / 清空」逻辑零改动。未来 Phase 2 调度起止区间可直接复用本控件。

设计取舍：
- 月历用标准库 `calendar` 算（无需手搓月份数学、无新依赖），周日起列。
- 弹窗用调用方传入的 `toplevel_factory`（默认 `CTkToplevel`）——flower 传 `_themed_toplevel`
  以复用其 DWM 深色标题栏兜底。
- 纯解析/排版函数（`parse_dt` / `month_weeks` / `format_dt`）不依赖 Tk，便于单测。
"""

from __future__ import annotations

import calendar
import tkinter as tk
from datetime import datetime

try:  # UI 必需；缺它由上层引导切 .venv-win，这里安静降级便于无 GUI 环境导入纯函数
    import customtkinter as ctk
except Exception:  # pragma: no cover - 无 GUI 环境
    ctk = None  # type: ignore[assignment]

# 周日起的列头（与 month_weeks 的 firstweekday=6 对齐）。
WEEKDAY_LABELS = ["日", "一", "二", "三", "四", "五", "六"]

_PARSE_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")


def parse_dt(text: str | None) -> datetime | None:
    """宽松解析 `YYYY-MM-DD HH:MM`（或带秒 / 仅日期）→ datetime；失败返回 None。"""
    raw = (text or "").strip()
    for fmt in _PARSE_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def format_dt(value: datetime) -> str:
    """统一输出格式 `YYYY-MM-DD HH:MM`（与 store/服务端付款时间字符串一致）。"""
    return value.strftime("%Y-%m-%d %H:%M")


def month_weeks(year: int, month: int) -> list[list[int]]:
    """该月按周分组的日期表（每周 7 项，0 表示非本月空格）；周日起。标准库，稳。"""
    return calendar.Calendar(firstweekday=6).monthdayscalendar(year, month)


if ctk is not None:

    class CTkDateTimePicker(ctk.CTkFrame):
        """一个「显示当前值的按钮 + 点开的月历/时分弹窗」复合控件，绑定到外部 StringVar。

        选定后把 `YYYY-MM-DD HH:MM` 写回 `textvariable`；不直接驱动业务，交上层「应用」。
        """

        def __init__(
            self,
            master,
            textvariable: tk.StringVar,
            colors: dict,
            *,
            toplevel_factory=None,
            placeholder: str = "选择时间",
            width: int = 170,
            **kwargs,
        ) -> None:
            super().__init__(master, fg_color="transparent", **kwargs)
            self._var = textvariable
            self._c = colors
            self._toplevel_factory = toplevel_factory
            self._placeholder = placeholder
            self._popup: "ctk.CTkToplevel | None" = None
            self._view_year = 0
            self._view_month = 0
            self._sel_hour = 0
            self._sel_minute = 0
            self._sel_day = 0
            self._grid_box = None

            self.columnconfigure(0, weight=1)
            self._button = ctk.CTkButton(
                self,
                text="",
                command=self._open,
                anchor="w",
                width=width,
                height=30,
                corner_radius=6,
                fg_color=colors.get("input", "#1b1e23"),
                hover_color=colors.get("accent_soft", "#2a3c5e"),
                text_color=colors.get("text", "#e7eaee"),
                border_width=1,
                border_color=colors.get("border", "#3a4049"),
            )
            self._button.grid(row=0, column=0, sticky="ew")
            self._trace = self._var.trace_add("write", lambda *_: self._sync_button())
            self._sync_button()

        # ---- 显示同步 ----
        def _sync_button(self) -> None:
            value = (self._var.get() or "").strip()
            self._button.configure(text=f"{value}    ▾" if value else f"{self._placeholder}    ▾")

        # ---- 弹窗 ----
        def _open(self) -> None:
            if self._popup is not None:
                try:
                    self._popup.focus()
                    return
                except Exception:
                    self._popup = None
            base = parse_dt(self._var.get()) or datetime.now()
            self._view_year, self._view_month = base.year, base.month
            self._sel_day = base.day
            self._sel_hour, self._sel_minute = base.hour, base.minute

            popup = self._toplevel_factory() if self._toplevel_factory else ctk.CTkToplevel(self)
            popup.title("选择日期时间")
            popup.configure(fg_color=self._c.get("background", "#1c1f24"))
            popup.resizable(False, False)
            self._popup = popup
            popup.protocol("WM_DELETE_WINDOW", self._close)

            wrap = ctk.CTkFrame(popup, fg_color=self._c.get("panel", "#262a31"), corner_radius=10)
            wrap.pack(padx=12, pady=12)

            head = ctk.CTkFrame(wrap, fg_color="transparent")
            head.pack(fill="x", padx=10, pady=(10, 4))
            self._btn(head, "‹", lambda: self._shift_month(-1), width=34).pack(side="left")
            self._head_label = ctk.CTkLabel(
                head, text="", font=ctk.CTkFont(size=14, weight="bold"),
                text_color=self._c.get("text", "#e7eaee"),
            )
            self._head_label.pack(side="left", expand=True)
            self._btn(head, "›", lambda: self._shift_month(1), width=34).pack(side="right")

            week_row = ctk.CTkFrame(wrap, fg_color="transparent")
            week_row.pack(fill="x", padx=10)
            for i, lbl in enumerate(WEEKDAY_LABELS):
                week_row.columnconfigure(i, weight=1, uniform="wk")
                ctk.CTkLabel(
                    week_row, text=lbl, width=32,
                    text_color=self._c.get("muted", "#9aa4ae"), font=ctk.CTkFont(size=11),
                ).grid(row=0, column=i, padx=1, pady=2)

            self._grid_box = ctk.CTkFrame(wrap, fg_color="transparent")
            self._grid_box.pack(fill="x", padx=10, pady=(0, 6))

            time_row = ctk.CTkFrame(wrap, fg_color="transparent")
            time_row.pack(fill="x", padx=10, pady=(2, 6))
            ctk.CTkLabel(
                time_row, text="时间", text_color=self._c.get("muted", "#9aa4ae"),
                font=ctk.CTkFont(size=12),
            ).pack(side="left", padx=(0, 8))
            self._hour_var = tk.StringVar(value=f"{self._sel_hour:02d}")
            self._minute_var = tk.StringVar(value=f"{self._sel_minute:02d}")
            self._option(time_row, self._hour_var, [f"{h:02d}" for h in range(24)]).pack(side="left")
            ctk.CTkLabel(time_row, text=":", text_color=self._c.get("text", "#e7eaee")).pack(side="left", padx=2)
            self._option(time_row, self._minute_var, [f"{m:02d}" for m in range(60)]).pack(side="left")

            foot = ctk.CTkFrame(wrap, fg_color="transparent")
            foot.pack(fill="x", padx=10, pady=(2, 10))
            self._btn(foot, "今天", self._pick_today, width=56).pack(side="left")
            self._btn(foot, "取消", self._close, width=56).pack(side="right")
            self._btn(foot, "确定", self._confirm, width=56, primary=True).pack(side="right", padx=(0, 6))

            self._render_grid()
            self._position(popup)
            try:
                popup.transient(self.winfo_toplevel())
                popup.after(120, popup.grab_set)  # CTkToplevel 早 grab 偶发失焦，延后更稳
            except Exception:
                pass

        def _render_grid(self) -> None:
            box = self._grid_box
            if box is None:
                return
            for child in box.winfo_children():
                child.destroy()
            self._head_label.configure(text=f"{self._view_year} 年 {self._view_month} 月")
            for c in range(7):
                box.columnconfigure(c, weight=1, uniform="day")
            for r, week in enumerate(month_weeks(self._view_year, self._view_month)):
                for c, day in enumerate(week):
                    if day == 0:
                        continue
                    selected = day == self._sel_day
                    btn = ctk.CTkButton(
                        box, text=str(day), width=32, height=28, corner_radius=6,
                        command=lambda d=day: self._pick_day(d),
                        fg_color=self._c.get("accent", "#3b76e0") if selected else "transparent",
                        hover_color=self._c.get("accent_soft", "#2a3c5e"),
                        text_color="#ffffff" if selected else self._c.get("text", "#e7eaee"),
                        font=ctk.CTkFont(size=12),
                    )
                    btn.grid(row=r, column=c, padx=1, pady=1, sticky="ew")

        # ---- 行为 ----
        def _shift_month(self, delta: int) -> None:
            month = self._view_month + delta
            year = self._view_year
            while month < 1:
                month += 12
                year -= 1
            while month > 12:
                month -= 12
                year += 1
            self._view_year, self._view_month = year, month
            self._render_grid()

        def _pick_day(self, day: int) -> None:
            self._sel_day = day
            self._render_grid()

        def _pick_today(self) -> None:
            now = datetime.now()
            self._view_year, self._view_month, self._sel_day = now.year, now.month, now.day
            self._hour_var.set(f"{now.hour:02d}")
            self._minute_var.set(f"{now.minute:02d}")
            self._render_grid()

        def _confirm(self) -> None:
            try:
                hour = int(self._hour_var.get())
                minute = int(self._minute_var.get())
                value = datetime(self._view_year, self._view_month, self._sel_day, hour, minute)
            except (ValueError, TypeError):
                return
            self._var.set(format_dt(value))
            self._close()

        def _close(self) -> None:
            if self._popup is not None:
                try:
                    self._popup.grab_release()
                except Exception:
                    pass
                try:
                    self._popup.destroy()
                except Exception:
                    pass
                self._popup = None

        # ---- 小工具 ----
        def _position(self, popup) -> None:
            try:
                self.update_idletasks()
                x = self.winfo_rootx()
                y = self.winfo_rooty() + self.winfo_height() + 4
                popup.geometry(f"+{x}+{y}")
            except Exception:
                pass

        def _btn(self, parent, text, command, *, width=58, primary=False):
            return ctk.CTkButton(
                parent, text=text, command=command, width=width, height=28, corner_radius=6,
                fg_color=self._c.get("accent", "#3b76e0") if primary else self._c.get("input", "#1b1e23"),
                hover_color=self._c.get("accent_soft", "#2a3c5e"),
                text_color="#ffffff" if primary else self._c.get("text", "#e7eaee"),
                border_width=0 if primary else 1, border_color=self._c.get("border", "#3a4049"),
                font=ctk.CTkFont(size=12),
            )

        def _option(self, parent, var, values):
            return ctk.CTkOptionMenu(
                parent, variable=var, values=values, width=64, height=28,
                fg_color=self._c.get("input", "#1b1e23"),
                button_color=self._c.get("accent", "#3b76e0"),
                button_hover_color=self._c.get("accent_soft", "#2a3c5e"),
                text_color=self._c.get("text", "#e7eaee"), font=ctk.CTkFont(size=12),
            )
