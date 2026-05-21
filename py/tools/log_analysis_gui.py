#!/usr/bin/env python3
"""GUI log analyzer for EPOS CSV hysteresis experiments.

Current plot support:
  - Tension loop: lc_ch0_N (input/start) vs lc_ch1_N (output/end)

The plotting code is intentionally organized around PlotSpec so later
linear-encoder columns can be added without changing the GUI flow.
"""

from __future__ import annotations

import csv
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QShortcut,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure


WORKSPACE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_LOG_DIR = WORKSPACE_DIR / "logs"


def float_or_nan(value: str | None) -> float:
    try:
        return float(value) if value not in (None, "") else float("nan")
    except ValueError:
        return float("nan")


def mean(values: list[float]) -> float:
    return sum(values) / max(1, len(values))


def subtract_baseline(values: list[float], baseline_samples: int) -> tuple[list[float], float]:
    n = max(1, min(baseline_samples, len(values)))
    baseline = mean(values[:n])
    return [v - baseline for v in values], baseline


def subtract_minimum(values: list[float]) -> tuple[list[float], float]:
    if not values:
        return [], float("nan")
    baseline = min(values)
    return [v - baseline for v in values], baseline


def loop_area(x: list[float], y: list[float]) -> float:
    if len(x) < 3:
        return 0.0
    area = 0.0
    for i in range(len(x)):
        j = (i + 1) % len(x)
        area += x[i] * y[j] - x[j] * y[i]
    return 0.5 * abs(area)


def finite_pairs(x: list[float], y: list[float]) -> tuple[list[float], list[float]]:
    px: list[float] = []
    py: list[float] = []
    for xv, yv in zip(x, y):
        if not math.isnan(xv) and not math.isnan(yv):
            px.append(xv)
            py.append(yv)
    return px, py


def moving_average(values: list[float], window: int) -> list[float]:
    if not values:
        return []
    window = max(3, min(int(window), len(values)))
    if window % 2 == 0:
        window += 1
    half = window // 2
    prefix = [0.0]
    for value in values:
        prefix.append(prefix[-1] + value)
    smoothed: list[float] = []
    for i in range(len(values)):
        lo = max(0, i - half)
        hi = min(len(values), i + half + 1)
        smoothed.append((prefix[hi] - prefix[lo]) / max(1, hi - lo))
    return smoothed


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return float("nan")
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    pos = max(0.0, min(100.0, pct)) / 100.0 * (len(xs) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    frac = pos - lo
    return xs[lo] * (1.0 - frac) + xs[hi] * frac


@dataclass(frozen=True)
class PlotSpec:
    key: str
    title: str
    x_col: str
    y_col: str
    x_label: str
    y_label: str

    def available(self, columns: set[str]) -> bool:
        return self.x_col in columns and self.y_col in columns


PLOT_SPECS = [
    PlotSpec(
        key="tension",
        title="Tension Loop",
        x_col="lc_ch0_N",
        y_col="lc_ch1_N",
        x_label="T_in / CH0 [N]",
        y_label="T_out / CH1 [N]",
    ),
    # Future example:
    # PlotSpec("linear_position", "Linear Encoder Loop",
    #          "linear_in_mm", "linear_out_mm", "P_in [mm]", "P_out [mm]"),
]

COLOR_CYCLE = [
    "#1f77b4",  # blue
    "#d62728",  # red
    "#2ca02c",  # green
    "#9467bd",  # purple
    "#ff7f0e",  # orange
    "#17becf",  # cyan
    "#8c564b",  # brown
    "#e377c2",  # pink
    "#7f7f7f",  # gray
    "#bcbd22",  # olive
]


def color_for_index(index: int) -> str:
    return COLOR_CYCLE[index % len(COLOR_CYCLE)]


@dataclass
class LogFile:
    path: Path
    label: str
    columns: list[str]
    data: dict[str, list[float]]
    row_count: int
    valid_count: int
    duration_s: float
    error: str = ""

    @property
    def column_set(self) -> set[str]:
        return set(self.columns)


def read_log(path: Path) -> LogFile:
    try:
        with path.open("r", newline="") as f:
            reader = csv.DictReader(f)
            columns = list(reader.fieldnames or [])
            data = {name: [] for name in columns}
            row_count = 0
            valid_count = 0
            for row in reader:
                row_count += 1
                any_valid = False
                for name in columns:
                    val = float_or_nan(row.get(name))
                    data[name].append(val)
                    any_valid = any_valid or not math.isnan(val)
                if any_valid:
                    valid_count += 1

        duration = 0.0
        times = [v for v in data.get("time_s", []) if not math.isnan(v)]
        if len(times) >= 2:
            duration = max(0.0, times[-1] - times[0])
        return LogFile(path, path.stem, columns, data, row_count, valid_count, duration)
    except Exception as exc:
        return LogFile(path, path.stem, [], {}, 0, 0, 0.0, str(exc))


class LargePlotWindow(QMainWindow):
    def __init__(self, owner: "LogAnalysisWindow"):
        super().__init__(owner, Qt.Window)
        self.owner = owner
        self.setWindowTitle("Hysteresis Plot - Large View")
        self.resize(1600, 1000)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        action_row = QHBoxLayout()
        self.btn_refresh = QPushButton("그래프 새로고침")
        self.btn_fullscreen = QPushButton("전체화면")
        self.btn_refresh.clicked.connect(self.redraw)
        self.btn_fullscreen.clicked.connect(self.toggle_fullscreen)
        action_row.addWidget(self.btn_refresh)
        action_row.addWidget(self.btn_fullscreen)
        action_row.addStretch()
        layout.addLayout(action_row)

        self.figure = Figure(figsize=(14, 9), constrained_layout=True)
        self.canvas = FigureCanvas(self.figure)
        self.toolbar = NavigationToolbar(self.canvas, self)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas, 1)

        QShortcut(QKeySequence("F11"), self, activated=self.toggle_fullscreen)
        QShortcut(QKeySequence("Escape"), self, activated=self.exit_fullscreen)

    def redraw(self):
        self.owner.draw_current_plot(self.figure, self.canvas)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.btn_fullscreen.setText("전체화면")
        else:
            self.showFullScreen()
            self.btn_fullscreen.setText("창 모드")

    def exit_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.btn_fullscreen.setText("전체화면")

    def closeEvent(self, event):
        self.owner.unregister_large_plot_window(self)
        super().closeEvent(event)


class LogAnalysisWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EPOS Log Hysteresis Analyzer")
        self.resize(1320, 820)
        self.logs: list[LogFile] = []
        self.large_plot_windows: list[LargePlotWindow] = []
        self.last_dir = DEFAULT_LOG_DIR if DEFAULT_LOG_DIR.exists() else WORKSPACE_DIR

        root = QWidget()
        self.setCentralWidget(root)
        main = QHBoxLayout(root)

        left = QVBoxLayout()
        main.addLayout(left, 0)

        file_row = QHBoxLayout()
        self.btn_add = QPushButton("로그 추가")
        self.btn_folder = QPushButton("폴더 추가")
        self.btn_remove = QPushButton("선택 제거")
        self.btn_clear = QPushButton("전체 비우기")
        file_row.addWidget(self.btn_add)
        file_row.addWidget(self.btn_folder)
        file_row.addWidget(self.btn_remove)
        file_row.addWidget(self.btn_clear)
        left.addLayout(file_row)

        opts = QHBoxLayout()
        self.combo_plot = QComboBox()
        self.combo_plot.addItems([spec.title for spec in PLOT_SPECS])
        self.combo_mode = QComboBox()
        self.combo_mode.addItem("Raw + Relative", ["raw", "relative"])
        self.combo_mode.addItem("Raw", ["raw"])
        self.combo_mode.addItem("Relative", ["relative"])
        self.chk_abs_tension = QCheckBox("|F| 장력")
        self.chk_abs_tension.setChecked(True)
        self.chk_overlay = QCheckBox("여러 로그 겹쳐보기")
        self.chk_overlay.setChecked(False)
        self.combo_rel_ref = QComboBox()
        self.combo_rel_ref.addItem("Min N", "min")
        self.combo_rel_ref.addItem("Initial mean", "initial")
        self.spin_baseline = QSpinBox()
        self.spin_baseline.setRange(1, 100000)
        self.spin_baseline.setValue(200)
        self.spin_baseline.setSuffix(" samples")
        self.spin_noise_window = QSpinBox()
        self.spin_noise_window.setRange(5, 1001)
        self.spin_noise_window.setSingleStep(10)
        self.spin_noise_window.setValue(51)
        self.spin_noise_window.setSuffix(" samples")
        opts.addWidget(QLabel("그래프:"))
        opts.addWidget(self.combo_plot)
        opts.addWidget(QLabel("모드:"))
        opts.addWidget(self.combo_mode)
        opts.addWidget(self.chk_abs_tension)
        self.combo_layout = QComboBox()
        self.combo_layout.addItems(["Loop View", "Paper Overview", "Noise Diagnostics"])
        opts.addWidget(QLabel("Layout:"))
        opts.addWidget(self.combo_layout)
        opts.addWidget(QLabel("Relative 기준:"))
        opts.addWidget(self.combo_rel_ref)
        opts.addWidget(QLabel("초기 samples:"))
        opts.addWidget(self.spin_baseline)
        opts.addWidget(QLabel("noise window:"))
        opts.addWidget(self.spin_noise_window)
        opts.addWidget(self.chk_overlay)
        left.addLayout(opts)

        time_opts = QHBoxLayout()
        self.chk_time_range = QCheckBox("Time range")
        self.spin_time_start = QDoubleSpinBox()
        self.spin_time_start.setRange(-999999.0, 999999.0)
        self.spin_time_start.setDecimals(3)
        self.spin_time_start.setSingleStep(0.1)
        self.spin_time_start.setSuffix(" s")
        self.spin_time_start.setValue(0.0)
        self.spin_time_end = QDoubleSpinBox()
        self.spin_time_end.setRange(-999999.0, 999999.0)
        self.spin_time_end.setDecimals(3)
        self.spin_time_end.setSingleStep(0.1)
        self.spin_time_end.setSuffix(" s")
        self.spin_time_end.setValue(0.0)
        self.btn_time_all = QPushButton("전체 시간")
        time_opts.addWidget(self.chk_time_range)
        time_opts.addWidget(QLabel("start:"))
        time_opts.addWidget(self.spin_time_start)
        time_opts.addWidget(QLabel("end:"))
        time_opts.addWidget(self.spin_time_end)
        time_opts.addWidget(self.btn_time_all)
        time_opts.addStretch()
        left.addLayout(time_opts)

        cycle_opts = QHBoxLayout()
        self.combo_cycle_source = QComboBox()
        self.combo_cycle_source.addItem("Auto target_vel", "auto")
        self.combo_cycle_source.addItem("Manual Hz", "hz")
        self.combo_cycle_source.addItem("CSV cycle column", "csv")
        self.spin_cycle_hz = QDoubleSpinBox()
        self.spin_cycle_hz.setRange(0.001, 1000.0)
        self.spin_cycle_hz.setDecimals(3)
        self.spin_cycle_hz.setSingleStep(0.1)
        self.spin_cycle_hz.setValue(0.1)
        self.spin_cycle_hz.setSuffix(" Hz")
        self.chk_cycle_filter = QCheckBox("Cycle #")
        self.spin_cycle_number = QSpinBox()
        self.spin_cycle_number.setRange(1, 10000)
        self.spin_cycle_number.setValue(1)
        self.combo_cycle_summary = QComboBox()
        self.combo_cycle_summary.addItem("Summary off", "off")
        self.combo_cycle_summary.addItem("Mean cycle", "mean")
        self.combo_cycle_summary.addItem("Median cycle", "median")
        self.combo_cycle_summary.setToolTip("여러 cycle을 phase 기준으로 맞춘 뒤 한 개 루프로 요약합니다. Median은 튀는 점에 더 강합니다.")
        self.chk_cycle_markers = QCheckBox("Cycle markers")
        self.chk_cycle_markers.setChecked(False)
        cycle_opts.addWidget(QLabel("Cycle 기준:"))
        cycle_opts.addWidget(self.combo_cycle_source)
        cycle_opts.addWidget(self.spin_cycle_hz)
        cycle_opts.addWidget(self.chk_cycle_filter)
        cycle_opts.addWidget(self.spin_cycle_number)
        cycle_opts.addWidget(QLabel("평균:"))
        cycle_opts.addWidget(self.combo_cycle_summary)
        cycle_opts.addWidget(self.chk_cycle_markers)
        cycle_opts.addStretch()
        left.addLayout(cycle_opts)

        action_row = QHBoxLayout()
        self.btn_plot = QPushButton("그래프 갱신")
        self.btn_large = QPushButton("큰 창으로 보기")
        self.btn_save = QPushButton("그림 저장")
        action_row.addWidget(self.btn_plot)
        action_row.addWidget(self.btn_large)
        action_row.addWidget(self.btn_save)
        action_row.addStretch()
        left.addLayout(action_row)

        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels([
            "색",
            "파일",
            "샘플",
            "시간[s]",
            "컬럼",
            "Tin0[N]",
            "Tout0[N]",
            "Raw 면적",
            "Relative 면적",
            "상태",
        ])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        left.addWidget(self.table, 1)

        self.info_label = QLabel("로그를 추가하면 컬럼과 기본 통계를 확인합니다.")
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("color: #555;")
        left.addWidget(self.info_label)

        right = QVBoxLayout()
        main.addLayout(right, 1)
        self.figure = Figure(figsize=(9, 6), constrained_layout=True)
        self.canvas = FigureCanvas(self.figure)
        self.toolbar = NavigationToolbar(self.canvas, self)
        right.addWidget(self.toolbar)
        right.addWidget(self.canvas, 1)

        self.btn_add.clicked.connect(self.add_files)
        self.btn_folder.clicked.connect(self.add_folder)
        self.btn_remove.clicked.connect(self.remove_selected)
        self.btn_clear.clicked.connect(self.clear_logs)
        self.btn_plot.clicked.connect(self.plot)
        self.btn_large.clicked.connect(self.open_large_plot)
        self.btn_save.clicked.connect(self.save_figure)
        self.combo_plot.currentIndexChanged.connect(self.plot)
        self.combo_mode.currentIndexChanged.connect(self.plot)
        self.chk_abs_tension.stateChanged.connect(self.refresh_table_and_plot)
        self.combo_layout.currentIndexChanged.connect(self.plot)
        self.chk_overlay.stateChanged.connect(self.plot)
        self.combo_rel_ref.currentIndexChanged.connect(self.on_relative_reference_changed)
        self.spin_baseline.valueChanged.connect(self.refresh_table_and_plot)
        self.spin_noise_window.valueChanged.connect(self.plot)
        self.chk_time_range.stateChanged.connect(self.refresh_table_and_plot)
        self.spin_time_start.valueChanged.connect(self.refresh_table_and_plot)
        self.spin_time_end.valueChanged.connect(self.refresh_table_and_plot)
        self.btn_time_all.clicked.connect(self.reset_time_range_to_logs)
        self.combo_cycle_source.currentIndexChanged.connect(self.on_cycle_source_changed)
        self.spin_cycle_hz.valueChanged.connect(self.refresh_table_and_plot)
        self.chk_cycle_filter.stateChanged.connect(self.on_cycle_filter_changed)
        self.spin_cycle_number.valueChanged.connect(self.refresh_table_and_plot)
        self.combo_cycle_summary.currentIndexChanged.connect(self.on_cycle_summary_changed)
        self.chk_cycle_markers.stateChanged.connect(self.plot)
        self.on_cycle_source_changed()
        self.on_cycle_filter_changed()
        self.on_cycle_summary_changed()
        self.on_relative_reference_changed()

    def time_filter_enabled(self) -> bool:
        return self.chk_time_range.isChecked()

    def time_range(self) -> tuple[float, float]:
        t0 = float(self.spin_time_start.value())
        t1 = float(self.spin_time_end.value())
        return (t0, t1) if t0 <= t1 else (t1, t0)

    def time_range_label(self) -> str:
        if not self.time_filter_enabled():
            return "full time"
        t0, t1 = self.time_range()
        return f"{t0:.3f}-{t1:.3f}s"

    def reset_time_range_to_logs(self):
        self.sync_time_range_to_logs()
        self.refresh_table_and_plot()

    def sync_time_range_to_logs(self):
        times: list[float] = []
        for log in self.logs:
            times.extend(v for v in log.data.get("time_s", []) if not math.isnan(v))
        t0 = min(times) if times else 0.0
        t1 = max(times) if times else 0.0
        self.spin_time_start.blockSignals(True)
        self.spin_time_end.blockSignals(True)
        self.spin_time_start.setValue(t0)
        self.spin_time_end.setValue(t1)
        self.spin_time_start.blockSignals(False)
        self.spin_time_end.blockSignals(False)

    def row_passes_time_filter(self, times: list[float], index: int) -> bool:
        if not self.time_filter_enabled() or not times:
            return True
        if index >= len(times):
            return False
        tv = times[index]
        if math.isnan(tv):
            return False
        t0, t1 = self.time_range()
        return t0 <= tv <= t1

    def cycle_source(self) -> str:
        return self.combo_cycle_source.currentData() or "auto"

    def cycle_label(self) -> str:
        summary = self.cycle_summary_mode()
        if summary != "off":
            return f"{summary} cycle ({self.cycle_source()})"
        if not self.chk_cycle_filter.isChecked():
            return "all cycles"
        return f"cycle {self.spin_cycle_number.value()} ({self.cycle_source()})"

    def cycle_summary_mode(self) -> str:
        return self.combo_cycle_summary.currentData() or "off"

    def cycle_summary_enabled(self) -> bool:
        return self.cycle_summary_mode() != "off"

    def on_cycle_source_changed(self):
        self.spin_cycle_hz.setEnabled(self.cycle_source() == "hz")
        self.refresh_table_and_plot()

    def on_cycle_filter_changed(self):
        self.spin_cycle_number.setEnabled(self.chk_cycle_filter.isChecked() and not self.cycle_summary_enabled())
        self.chk_cycle_filter.setEnabled(not self.cycle_summary_enabled())
        self.refresh_table_and_plot()

    def on_cycle_summary_changed(self):
        summary_on = self.cycle_summary_enabled()
        self.chk_cycle_filter.setEnabled(not summary_on)
        self.spin_cycle_number.setEnabled(self.chk_cycle_filter.isChecked() and not summary_on)
        self.refresh_table_and_plot()

    def cycle_column_name(self, log: LogFile) -> str | None:
        candidates = ["cycle", "cycle_index", "cycle_id", "cycle_no", "cycle_number"]
        for name in candidates:
            if name in log.data:
                return name
        return None

    def cycle_signal_column(self, log: LogFile) -> str | None:
        if "target_vel" in log.data and any(not math.isnan(v) for v in log.data["target_vel"]):
            return "target_vel"
        if "actual_vel" in log.data and any(not math.isnan(v) for v in log.data["actual_vel"]):
            return "actual_vel"
        return None

    def cycle_boundary_times(self, log: LogFile) -> list[float]:
        times = log.data.get("time_s", [])
        valid_times = [v for v in times if not math.isnan(v)]
        if len(valid_times) < 2:
            return []

        t_start = valid_times[0]
        t_end = valid_times[-1]
        source = self.cycle_source()
        if source == "hz":
            period = 1.0 / max(float(self.spin_cycle_hz.value()), 1e-9)
            count = int(math.ceil(max(0.0, t_end - t_start) / period)) + 1
            return [t_start + i * period for i in range(count + 1)]

        signal_col = self.cycle_signal_column(log)
        if not signal_col:
            return [t_start, t_end]

        signal = log.data.get(signal_col, [])
        boundaries = [t_start]
        for i in range(1, min(len(times), len(signal))):
            t0 = times[i - 1]
            t1 = times[i]
            a = signal[i - 1]
            b = signal[i]
            if math.isnan(t0) or math.isnan(t1) or math.isnan(a) or math.isnan(b):
                continue
            if a < 0.0 <= b:
                denom = b - a
                frac = 0.0 if abs(denom) < 1e-12 else (0.0 - a) / denom
                crossing = t0 + (t1 - t0) * frac
                if crossing > boundaries[-1] + 1e-6:
                    boundaries.append(crossing)
        if t_end > boundaries[-1] + 1e-6:
            boundaries.append(t_end)
        return boundaries if len(boundaries) >= 2 else [t_start, t_end]

    def selected_cycle_window(self, log: LogFile) -> tuple[float, float] | None:
        if not self.chk_cycle_filter.isChecked() or self.cycle_source() == "csv":
            return None
        boundaries = self.cycle_boundary_times(log)
        cycle_idx = self.spin_cycle_number.value() - 1
        if cycle_idx < 0 or cycle_idx + 1 >= len(boundaries):
            return None
        return boundaries[cycle_idx], boundaries[cycle_idx + 1]

    def row_passes_cycle_filter(
        self,
        log: LogFile,
        times: list[float],
        index: int,
        cycle_window: tuple[float, float] | None,
    ) -> bool:
        if not self.chk_cycle_filter.isChecked():
            return True

        if self.cycle_source() == "csv":
            col = self.cycle_column_name(log)
            if not col:
                return False
            values = [v for v in log.data.get(col, []) if not math.isnan(v)]
            if not values or index >= len(log.data[col]):
                return False
            raw_value = log.data[col][index]
            if math.isnan(raw_value):
                return False
            min_cycle = int(round(min(values)))
            target = self.spin_cycle_number.value() if min_cycle >= 1 else self.spin_cycle_number.value() - 1
            return int(round(raw_value)) == target

        if cycle_window is None or index >= len(times):
            return False
        tv = times[index]
        if math.isnan(tv):
            return False
        start, end = cycle_window
        return start <= tv < end

    def cycle_start_indices(self, log: LogFile) -> list[tuple[int, int]]:
        times = log.data.get("time_s", [])
        if not times:
            return []
        source = self.cycle_source()
        if source == "csv":
            col = self.cycle_column_name(log)
            if not col:
                return []
            values = log.data[col]
            finite_values = [v for v in values if not math.isnan(v)]
            if not finite_values:
                return []
            min_cycle = int(round(min(finite_values)))
            seen: set[int] = set()
            starts: list[tuple[int, int]] = []
            for i, value in enumerate(values):
                if math.isnan(value):
                    continue
                raw_cycle = int(round(value))
                cycle_no = raw_cycle if min_cycle >= 1 else raw_cycle + 1
                if cycle_no not in seen:
                    seen.add(cycle_no)
                    starts.append((cycle_no, i))
            return starts

        starts: list[tuple[int, int]] = []
        for cycle_no, boundary in enumerate(self.cycle_boundary_times(log)[:-1], start=1):
            best_index = None
            for i, tv in enumerate(times):
                if math.isnan(tv):
                    continue
                if tv >= boundary:
                    best_index = i
                    break
            if best_index is not None:
                starts.append((cycle_no, best_index))
        return starts

    @staticmethod
    def interpolate_at(xs: list[float], ys: list[float], xq: float) -> float:
        if not xs:
            return float("nan")
        if xq <= xs[0]:
            return ys[0]
        if xq >= xs[-1]:
            return ys[-1]
        for i in range(1, len(xs)):
            if xs[i] >= xq:
                x0, x1 = xs[i - 1], xs[i]
                y0, y1 = ys[i - 1], ys[i]
                denom = x1 - x0
                frac = 0.0 if abs(denom) < 1e-12 else (xq - x0) / denom
                return y0 + (y1 - y0) * frac
        return ys[-1]

    def cycle_summary_xy(self, log: LogFile, spec: PlotSpec) -> tuple[list[float], list[float]]:
        t, x, y, _ = self.finite_tension_indexed_rows(
            log,
            spec,
            apply_cycle_filter=False,
            normalize_time=False,
        )
        if len(t) < 3:
            return [], []

        boundaries = self.cycle_boundary_times(log)
        if len(boundaries) < 2:
            return [], []

        phase_grid = [i / 199.0 for i in range(200)]
        cycles_x: list[list[float]] = []
        cycles_y: list[list[float]] = []
        for start, end in zip(boundaries[:-1], boundaries[1:]):
            duration = end - start
            if duration <= 1e-9:
                continue
            local_t: list[float] = []
            local_x: list[float] = []
            local_y: list[float] = []
            for tv, xv, yv in zip(t, x, y):
                if start <= tv < end:
                    local_t.append((tv - start) / duration)
                    local_x.append(xv)
                    local_y.append(yv)
            if len(local_t) < 5:
                continue
            cycles_x.append([self.interpolate_at(local_t, local_x, p) for p in phase_grid])
            cycles_y.append([self.interpolate_at(local_t, local_y, p) for p in phase_grid])

        if not cycles_x:
            return [], []

        mode = self.cycle_summary_mode()
        out_x: list[float] = []
        out_y: list[float] = []
        for col in range(len(phase_grid)):
            xs = [cycle[col] for cycle in cycles_x if not math.isnan(cycle[col])]
            ys = [cycle[col] for cycle in cycles_y if not math.isnan(cycle[col])]
            if mode == "median":
                out_x.append(percentile(xs, 50.0))
                out_y.append(percentile(ys, 50.0))
            else:
                out_x.append(mean(xs))
                out_y.append(mean(ys))
        return out_x, out_y

    def filtered_row_summary(self, log: LogFile) -> tuple[int, float]:
        times = [v for v in log.data.get("time_s", []) if not math.isnan(v)]
        if not times:
            return log.row_count, log.duration_s
        all_times = log.data.get("time_s", [])
        cycle_window = self.selected_cycle_window(log)
        kept = [
            all_times[i]
            for i in range(len(all_times))
            if self.row_passes_time_filter(all_times, i)
            and self.row_passes_cycle_filter(log, all_times, i, cycle_window)
            and not math.isnan(all_times[i])
        ]
        if not self.time_filter_enabled() and not self.chk_cycle_filter.isChecked():
            return log.row_count, log.duration_s
        if len(kept) >= 2:
            return len(kept), max(0.0, max(kept) - min(kept))
        return len(kept), 0.0

    def relative_reference_mode(self) -> str:
        return self.combo_rel_ref.currentData() or "min"

    def relative_reference_label(self) -> str:
        return "min" if self.relative_reference_mode() == "min" else "initial"

    def relative_values(self, values: list[float]) -> tuple[list[float], float]:
        if self.relative_reference_mode() == "min":
            return subtract_minimum(values)
        return subtract_baseline(values, self.spin_baseline.value())

    def on_relative_reference_changed(self):
        self.spin_baseline.setEnabled(self.relative_reference_mode() == "initial")
        self.refresh_table_and_plot()

    def active_spec(self) -> PlotSpec:
        return PLOT_SPECS[self.combo_plot.currentIndex()]

    def selected_logs(self) -> list[LogFile]:
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
        if not rows:
            return self.logs
        return [self.logs[row] for row in rows if 0 <= row < len(self.logs)]

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "CSV 로그 선택",
            str(self.last_dir),
            "CSV Logs (*.csv);;All Files (*)",
        )
        if files:
            self.last_dir = Path(files[0]).parent
            self.load_paths([Path(p) for p in files])

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "CSV 로그 폴더 선택", str(self.last_dir))
        if folder:
            self.last_dir = Path(folder)
            self.load_paths(sorted(Path(folder).glob("*.csv")))

    def load_paths(self, paths: list[Path]):
        existing = {log.path.resolve() for log in self.logs}
        new_logs = []
        for path in paths:
            if path.resolve() in existing:
                continue
            new_logs.append(read_log(path))
        self.logs.extend(new_logs)
        if not self.time_filter_enabled():
            self.sync_time_range_to_logs()
        self.refresh_table_and_plot()

    def remove_selected(self):
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            if 0 <= row < len(self.logs):
                self.logs.pop(row)
        if not self.time_filter_enabled():
            self.sync_time_range_to_logs()
        self.refresh_table_and_plot()

    def clear_logs(self):
        self.logs.clear()
        self.sync_time_range_to_logs()
        self.refresh_table_and_plot()

    def refresh_table_and_plot(self):
        self.refresh_table()
        self.plot()

    def refresh_table(self):
        spec = self.active_spec()
        ref_suffix = " min" if self.relative_reference_mode() == "min" else "0"
        self.table.setHorizontalHeaderLabels([
            "색",
            "파일",
            "샘플",
            "시간[s]",
            "컬럼",
            f"Tin{ref_suffix}[N]",
            f"Tout{ref_suffix}[N]",
            "Raw 면적",
            "Relative 면적",
            "상태",
        ])
        self.table.setRowCount(len(self.logs))

        valid_for_spec = 0
        for row, log in enumerate(self.logs):
            available = spec.available(log.column_set)
            if available and not log.error:
                valid_for_spec += 1
            stats = self.compute_stats(log, spec) if available and not log.error else {}
            status = log.error or ("OK" if available else f"필수 컬럼 없음: {spec.x_col}, {spec.y_col}")
            columns = ", ".join(log.columns[:10]) + ("..." if len(log.columns) > 10 else "")
            visible_rows, visible_duration = self.filtered_row_summary(log)
            values = [
                "",
                log.path.name,
                str(visible_rows),
                f"{visible_duration:.2f}",
                columns,
                self.format_stat(stats.get("x0")),
                self.format_stat(stats.get("y0")),
                self.format_stat(stats.get("raw_area")),
                self.format_stat(stats.get("rel_area")),
                status,
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setText("■")
                if col in (2, 3, 5, 6, 7, 8):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if not available or log.error:
                    item.setForeground(Qt.darkRed)
                elif col == 0:
                    item.setForeground(self.qt_color(color_for_index(row)))
                self.table.setItem(row, col, item)

        self.info_label.setText(
            f"총 {len(self.logs)}개 로그, 현재 그래프 사용 가능 {valid_for_spec}개. "
            f"선택한 행이 없으면 전체 로그를 그립니다. "
            f"표시 시간: {self.time_range_label()}, cycle: {self.cycle_label()}."
        )

    @staticmethod
    def format_stat(value) -> str:
        return "--" if value is None else f"{float(value):.4f}"

    @staticmethod
    def qt_color(hex_color: str):
        from PyQt5.QtGui import QColor

        return QColor(hex_color)

    def compute_stats(self, log: LogFile, spec: PlotSpec) -> dict[str, float]:
        x, y = self.finite_spec_pairs(log, spec)
        if not x:
            return {}
        xr, x0 = self.relative_values(x)
        yr, y0 = self.relative_values(y)
        return {
            "x0": x0,
            "y0": y0,
            "raw_area": loop_area(x, y),
            "rel_area": loop_area(xr, yr),
        }

    def plot(self):
        self.draw_current_plot(self.figure, self.canvas)
        self.refresh_large_plot_windows()

    def draw_current_plot(self, figure: Figure, canvas: FigureCanvas):
        figure.clear()
        spec = self.active_spec()
        logs = [log for log in self.selected_logs() if not log.error and spec.available(log.column_set)]
        modes = self.combo_mode.currentData()
        overlay = self.chk_overlay.isChecked()

        if not logs:
            ax = figure.add_subplot(111)
            ax.text(0.5, 0.5, "표시할 수 있는 로그가 없습니다.", ha="center", va="center")
            ax.set_axis_off()
            canvas.draw_idle()
            return

        if self.combo_layout.currentText() == "Paper Overview":
            self.plot_paper_overview(logs, spec, figure)
            canvas.draw_idle()
            return

        if self.combo_layout.currentText() == "Noise Diagnostics":
            self.plot_noise_diagnostics(logs, spec, figure)
            canvas.draw_idle()
            return

        if overlay:
            axes = figure.subplots(1, len(modes), squeeze=False)[0]
            for ax, mode in zip(axes, modes):
                self.plot_overlay(ax, logs, spec, mode)
        else:
            axes = figure.subplots(len(logs), len(modes), squeeze=False)
            for row, log in enumerate(logs):
                log_index = self.logs.index(log)
                for col, mode in enumerate(modes):
                    self.plot_single(axes[row][col], log, spec, mode, color_for_index(log_index))

        canvas.draw_idle()

    def open_large_plot(self):
        if not self.logs:
            QMessageBox.information(self, "큰 창", "먼저 로그를 추가하세요.")
            return
        win = LargePlotWindow(self)
        self.large_plot_windows.append(win)
        win.redraw()
        win.show()
        win.raise_()
        win.activateWindow()

    def refresh_large_plot_windows(self):
        alive: list[LargePlotWindow] = []
        for win in self.large_plot_windows:
            if win.isVisible():
                win.redraw()
                alive.append(win)
        self.large_plot_windows = alive

    def unregister_large_plot_window(self, win: LargePlotWindow):
        if win in self.large_plot_windows:
            self.large_plot_windows.remove(win)

    def force_abs_enabled(self, spec: PlotSpec) -> bool:
        return spec.key == "tension" and self.chk_abs_tension.isChecked()

    def finite_spec_pairs(self, log: LogFile, spec: PlotSpec) -> tuple[list[float], list[float]]:
        if self.cycle_summary_enabled():
            return self.cycle_summary_xy(log, spec)

        times = log.data.get("time_s", [])
        cycle_window = self.selected_cycle_window(log)
        use_abs = self.force_abs_enabled(spec)
        x_col = spec.x_col
        y_col = spec.y_col
        using_abs_cols = False
        if use_abs:
            ax_col = spec.x_col.replace("_N", "_abs_N")
            ay_col = spec.y_col.replace("_N", "_abs_N")
            if ax_col in log.data and ay_col in log.data:
                x_col, y_col = ax_col, ay_col
                using_abs_cols = True
        x_raw = log.data.get(x_col, [])
        y_raw = log.data.get(y_col, [])
        x: list[float] = []
        y: list[float] = []
        for i, (xv, yv) in enumerate(zip(x_raw, y_raw)):
            if math.isnan(xv) or math.isnan(yv):
                continue
            if not self.row_passes_time_filter(times, i):
                continue
            if not self.row_passes_cycle_filter(log, times, i, cycle_window):
                continue
            x.append(xv)
            y.append(yv)
        if use_abs and not using_abs_cols:
            x = [abs(v) for v in x]
            y = [abs(v) for v in y]
        return x, y

    def axis_labels(self, spec: PlotSpec) -> tuple[str, str]:
        if self.force_abs_enabled(spec):
            return "|T_in| / CH0 [N]", "|T_out| / CH1 [N]"
        return spec.x_label, spec.y_label

    def prepare_xy(self, log: LogFile, spec: PlotSpec, mode: str) -> tuple[list[float], list[float], str, str]:
        x, y = self.finite_spec_pairs(log, spec)
        base_xlabel, base_ylabel = self.axis_labels(spec)
        if mode == "relative":
            x, x0 = self.relative_values(x)
            y, y0 = self.relative_values(y)
            xlabel = f"Delta {base_xlabel}"
            ylabel = f"Delta {base_ylabel}"
        else:
            xlabel = base_xlabel
            ylabel = base_ylabel
        return x, y, xlabel, ylabel

    def mode_title_label(self, mode: str) -> str:
        label = "Raw" if mode == "raw" else f"Relative ({self.relative_reference_label()})"
        summary = self.cycle_summary_mode()
        if summary == "mean":
            label += ", mean cycle"
        elif summary == "median":
            label += ", median cycle"
        return label

    def plot_single(self, ax, log: LogFile, spec: PlotSpec, mode: str, color: str):
        x, y, xlabel, ylabel = self.prepare_xy(log, spec, mode)
        ax.plot(x, y, linewidth=1.1, color=color, label=log.label)
        if x and y:
            ax.scatter([x[0]], [y[0]], s=18, color=color, edgecolors="black", linewidths=0.5, zorder=3)
        self.add_cycle_markers(ax, log, spec, mode, color)
        mode_label = self.mode_title_label(mode)
        ax.set_title(f"{log.label} ({mode_label})", fontsize=10)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.grid(True, alpha=0.3)
        ax.axis("equal")
        ax.legend(fontsize=8)
        if mode == "raw" and x and y:
            mn = min(min(x), min(y))
            mx = max(max(x), max(y))
            ax.plot([mn, mx], [mn, mx], "k--", linewidth=0.8, alpha=0.35)

    def plot_overlay(self, ax, logs: list[LogFile], spec: PlotSpec, mode: str):
        xlabel = spec.x_label
        ylabel = spec.y_label
        all_x: list[float] = []
        all_y: list[float] = []
        for log in logs:
            log_index = self.logs.index(log)
            x, y, xlabel, ylabel = self.prepare_xy(log, spec, mode)
            all_x.extend(x)
            all_y.extend(y)
            color = color_for_index(log_index)
            ax.plot(x, y, linewidth=1.1, color=color, label=log.label)
            if x and y:
                ax.scatter([x[0]], [y[0]], s=18, color=color, edgecolors="black", linewidths=0.5, zorder=3)
            self.add_cycle_markers(ax, log, spec, mode, color)
        mode_label = self.mode_title_label(mode)
        ax.set_title(f"{spec.title} ({mode_label}, overlay)", fontsize=10)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.grid(True, alpha=0.3)
        ax.axis("equal")
        if mode == "raw" and all_x and all_y:
            mn = min(min(all_x), min(all_y))
            mx = max(max(all_x), max(all_y))
            ax.plot([mn, mx], [mn, mx], "k--", linewidth=0.8, alpha=0.35)
        ax.legend(fontsize=8)

    def add_cycle_markers(self, ax, log: LogFile, spec: PlotSpec, mode: str, color: str):
        if not self.chk_cycle_markers.isChecked() or self.cycle_summary_enabled():
            return
        t, x, y, idx = self.finite_tension_indexed_rows(log, spec)
        if not idx:
            return
        if mode == "relative":
            x, _ = self.relative_values(x)
            y, _ = self.relative_values(y)
        pos_by_idx = {source_idx: pos for pos, source_idx in enumerate(idx)}
        shown = 0
        for cycle_no, source_idx in self.cycle_start_indices(log):
            pos = pos_by_idx.get(source_idx)
            if pos is None:
                continue
            ax.scatter([x[pos]], [y[pos]], s=34, color=color, edgecolors="black",
                       linewidths=0.7, zorder=4)
            ax.text(x[pos], y[pos], str(cycle_no), fontsize=7, color="black",
                    ha="center", va="center", zorder=5,
                    bbox=dict(boxstyle="circle,pad=0.18", facecolor="white",
                              edgecolor=color, alpha=0.85, linewidth=0.7))
            shown += 1
            if shown >= 50:
                break

    def finite_tension_rows(
        self,
        log: LogFile,
        spec: PlotSpec,
        apply_cycle_filter: bool = True,
        normalize_time: bool = True,
    ):
        times = log.data.get("time_s", [])
        cycle_window = self.selected_cycle_window(log) if apply_cycle_filter else None
        use_abs = self.force_abs_enabled(spec)
        x_col = spec.x_col
        y_col = spec.y_col
        using_abs_cols = False
        if use_abs:
            ax_col = spec.x_col.replace("_N", "_abs_N")
            ay_col = spec.y_col.replace("_N", "_abs_N")
            if ax_col in log.data and ay_col in log.data:
                x_col, y_col = ax_col, ay_col
                using_abs_cols = True
        x_raw = log.data.get(x_col, [])
        y_raw = log.data.get(y_col, [])
        t: list[float] = []
        x: list[float] = []
        y: list[float] = []
        for i, (xv, yv) in enumerate(zip(x_raw, y_raw)):
            if math.isnan(xv) or math.isnan(yv):
                continue
            if not self.row_passes_time_filter(times, i):
                continue
            if apply_cycle_filter and not self.row_passes_cycle_filter(log, times, i, cycle_window):
                continue
            tv = times[i] if i < len(times) and not math.isnan(times[i]) else float(i)
            t.append(tv)
            x.append(abs(xv) if use_abs and not using_abs_cols else xv)
            y.append(abs(yv) if use_abs and not using_abs_cols else yv)
        if normalize_time and t:
            t0 = t[0]
            t = [v - t0 for v in t]
        return t, x, y

    def finite_tension_indexed_rows(
        self,
        log: LogFile,
        spec: PlotSpec,
        apply_cycle_filter: bool = True,
        normalize_time: bool = True,
    ):
        times = log.data.get("time_s", [])
        cycle_window = self.selected_cycle_window(log) if apply_cycle_filter else None
        use_abs = self.force_abs_enabled(spec)
        x_col = spec.x_col
        y_col = spec.y_col
        using_abs_cols = False
        if use_abs:
            ax_col = spec.x_col.replace("_N", "_abs_N")
            ay_col = spec.y_col.replace("_N", "_abs_N")
            if ax_col in log.data and ay_col in log.data:
                x_col, y_col = ax_col, ay_col
                using_abs_cols = True
        x_raw = log.data.get(x_col, [])
        y_raw = log.data.get(y_col, [])
        t: list[float] = []
        x: list[float] = []
        y: list[float] = []
        idx: list[int] = []
        for i, (xv, yv) in enumerate(zip(x_raw, y_raw)):
            if math.isnan(xv) or math.isnan(yv):
                continue
            if not self.row_passes_time_filter(times, i):
                continue
            if apply_cycle_filter and not self.row_passes_cycle_filter(log, times, i, cycle_window):
                continue
            tv = times[i] if i < len(times) and not math.isnan(times[i]) else float(i)
            t.append(tv)
            x.append(abs(xv) if use_abs and not using_abs_cols else xv)
            y.append(abs(yv) if use_abs and not using_abs_cols else yv)
            idx.append(i)
        if normalize_time and t:
            t0 = t[0]
            t = [v - t0 for v in t]
        return t, x, y, idx

    def aux_for_indices(self, log: LogFile, col: str, idx: list[int]) -> list[float]:
        data = log.data.get(col, [])
        out: list[float] = []
        for i in idx:
            value = data[i] if i < len(data) else float("nan")
            out.append(value)
        return out

    def cycle_boundaries(self, log: LogFile, t: list[float], idx: list[int]) -> list[float]:
        signal = self.aux_for_indices(log, "target_vel", idx)
        if not signal or all(math.isnan(v) for v in signal):
            signal = self.aux_for_indices(log, "actual_vel", idx)

        boundaries: list[float] = []
        for i in range(1, min(len(t), len(signal))):
            a = signal[i - 1]
            b = signal[i]
            if math.isnan(a) or math.isnan(b):
                continue
            if a < 0.0 <= b:
                denom = b - a
                frac = 0.0 if abs(denom) < 1e-12 else (0.0 - a) / denom
                boundaries.append(t[i - 1] + (t[i] - t[i - 1]) * frac)

        if len(boundaries) >= 2:
            return boundaries

        match = re.search(r"(\d+)\s*cycles?", log.path.name, flags=re.IGNORECASE)
        if match and t:
            cycles = max(1, int(match.group(1)))
            duration = max(t[-1] - t[0], 1e-9)
            period = duration / cycles
            return [t[0] + period * i for i in range(cycles + 1)]

        return [t[0], t[-1]] if len(t) >= 2 else []

    def phases_from_boundaries(self, t: list[float], boundaries: list[float]) -> list[float]:
        if len(boundaries) < 2:
            return [0.0 for _ in t]
        phases: list[float] = []
        j = 0
        for tv in t:
            while j + 2 < len(boundaries) and tv >= boundaries[j + 1]:
                j += 1
            start = boundaries[j]
            end = boundaries[j + 1]
            period = max(end - start, 1e-9)
            phases.append(((tv - start) / period % 1.0) * 100.0)
        return phases

    def compute_noise_profile(self, log: LogFile, spec: PlotSpec) -> dict | None:
        t, tin, tout, idx = self.finite_tension_indexed_rows(log, spec)
        if len(t) < 10:
            return None
        window = self.spin_noise_window.value()
        tin_smooth = moving_average(tin, window)
        tout_smooth = moving_average(tout, window)
        rough = [
            math.hypot(a - sa, b - sb)
            for a, sa, b, sb in zip(tin, tin_smooth, tout, tout_smooth)
        ]
        boundaries = self.cycle_boundaries(log, t, idx)
        phase = self.phases_from_boundaries(t, boundaries)
        vertical_score: list[float] = []
        vertical_ratio: list[float] = []
        for i in range(1, len(tin)):
            dx = tin[i] - tin[i - 1]
            dy = tout[i] - tout[i - 1]
            denom = abs(dx) + abs(dy) + 1e-12
            ratio = abs(dy) / denom
            step = math.hypot(dx, dy)
            vertical_ratio.append(ratio)
            vertical_score.append(step * ratio)
        return {
            "log": log,
            "t": t,
            "tin": tin,
            "tout": tout,
            "rough": rough,
            "phase": phase,
            "boundaries": boundaries,
            "vertical_t": t[1:],
            "vertical_tin": tin[1:],
            "vertical_tout": tout[1:],
            "vertical_phase": phase[1:],
            "vertical_score": vertical_score,
            "vertical_ratio": vertical_ratio,
        }

    def plot_noise_diagnostics(self, logs: list[LogFile], spec: PlotSpec, figure: Figure):
        axes = figure.subplots(2, 2, squeeze=False)
        ax_time, ax_loop = axes[0]
        ax_phase, ax_bins = axes[1]
        base_xlabel, base_ylabel = self.axis_labels(spec)

        profiles = [p for p in (self.compute_noise_profile(log, spec) for log in logs) if p]
        if not profiles:
            ax_time.text(0.5, 0.5, "노이즈 분석 가능한 로그가 없습니다.", ha="center", va="center")
            ax_time.set_axis_off()
            ax_loop.set_axis_off()
            ax_phase.set_axis_off()
            ax_bins.set_axis_off()
            return

        all_rough = [r for profile in profiles for r in profile["rough"]]
        all_vertical = [r for profile in profiles for r in profile["vertical_score"]]
        rough_threshold = percentile(all_rough, 95.0)
        vertical_threshold = percentile(all_vertical, 95.0)
        bin_count = 20
        phase_bins: list[list[float]] = [[] for _ in range(bin_count)]
        summary_lines = [
            f"roughness = sqrt((Tin-smooth)^2 + (Tout-smooth)^2)",
            f"vertical score = step * |dTout|/(|dTin|+|dTout|)",
            f"smooth window = {self.spin_noise_window.value()} samples",
            f"rough p95 = {rough_threshold:.4f} N, vertical p95 = {vertical_threshold:.4f} N/step",
            "",
            "peak vertical jitter:",
        ]

        scatter = None
        for profile in profiles:
            log = profile["log"]
            log_index = self.logs.index(log)
            color = color_for_index(log_index)
            t = profile["t"]
            tin = profile["tin"]
            tout = profile["tout"]
            rough = profile["rough"]
            vertical_t = profile["vertical_t"]
            vertical_tin = profile["vertical_tin"]
            vertical_tout = profile["vertical_tout"]
            vertical_phase = profile["vertical_phase"]
            vertical_score = profile["vertical_score"]

            ax_time.plot(t, rough, color=color, linewidth=0.8, alpha=0.85, label=log.label)
            for boundary in profile["boundaries"][:20]:
                ax_time.axvline(boundary, color=color, linewidth=0.3, alpha=0.12)

            ax_loop.plot(tin, tout, color=color, linewidth=0.6, alpha=0.22)
            high_x = [xv for xv, rv in zip(vertical_tin, vertical_score) if rv >= vertical_threshold]
            high_y = [yv for yv, rv in zip(vertical_tout, vertical_score) if rv >= vertical_threshold]
            high_r = [rv for rv in vertical_score if rv >= vertical_threshold]
            if high_x:
                scatter = ax_loop.scatter(high_x, high_y, c=high_r, cmap="plasma",
                                          s=10, alpha=0.88, edgecolors="none")

            ax_phase.scatter(vertical_phase, vertical_score, s=3, color=color, alpha=0.22, label=log.label)
            for ph, rv in zip(vertical_phase, vertical_score):
                b = max(0, min(bin_count - 1, int(ph / 100.0 * bin_count)))
                phase_bins[b].append(rv)

            if vertical_score:
                peak_i = max(range(len(vertical_score)), key=lambda i: vertical_score[i])
                summary_lines.append(
                    f"{log.label}: t={vertical_t[peak_i]:.3f}s, phase={vertical_phase[peak_i]:.1f}%, "
                    f"score={vertical_score[peak_i]:.4f}"
                )

        ax_time.axhline(rough_threshold, color="black", linewidth=0.8, linestyle="--", alpha=0.45, label="rough p95")
        ax_time.set_title("1. Roughness Over Time")
        ax_time.set_xlabel("Time [s]")
        ax_time.set_ylabel("roughness [N]")
        ax_time.grid(True, alpha=0.3)
        ax_time.legend(fontsize=7, ncols=2)

        ax_loop.set_title("2. Vertical Jitter Points on Loop")
        ax_loop.set_xlabel(base_xlabel)
        ax_loop.set_ylabel(base_ylabel)
        ax_loop.grid(True, alpha=0.3)
        ax_loop.axis("equal")
        self.add_identity_line(ax_loop)
        if scatter is not None:
            figure.colorbar(scatter, ax=ax_loop, label="vertical score")

        ax_phase.axhline(vertical_threshold, color="black", linewidth=0.8, linestyle="--", alpha=0.45)
        ax_phase.set_title("3. Vertical Jitter vs Cycle Phase")
        ax_phase.set_xlabel("Cycle phase [%]")
        ax_phase.set_ylabel("vertical score")
        ax_phase.set_xlim(0, 100)
        ax_phase.grid(True, alpha=0.3)

        centers = [(i + 0.5) * 100.0 / bin_count for i in range(bin_count)]
        means = [mean(xs) if xs else 0.0 for xs in phase_bins]
        ax_bins.bar(centers, means, width=100.0 / bin_count * 0.85, color="#607d8b")
        ax_bins.set_title("4. Mean Vertical Jitter by Cycle Phase")
        ax_bins.set_xlabel("Cycle phase [%]")
        ax_bins.set_ylabel("mean vertical score")
        ax_bins.set_xlim(0, 100)
        ax_bins.grid(True, axis="y", alpha=0.3)

        top_bins = sorted(range(bin_count), key=lambda i: means[i], reverse=True)[:3]
        if top_bins and any(means):
            summary_lines += ["", "most vertical phase bins:"]
            for i in top_bins:
                lo = i * 100.0 / bin_count
                hi = (i + 1) * 100.0 / bin_count
                summary_lines.append(f"{lo:.0f}-{hi:.0f}%: mean={means[i]:.4f}, n={len(phase_bins[i])}")
            text = "\n".join(summary_lines[:12])
            ax_bins.text(0.02, 0.98, text, transform=ax_bins.transAxes,
                         va="top", ha="left", fontsize=8,
                         bbox=dict(boxstyle="round", facecolor="white", alpha=0.82, edgecolor="#cccccc"))

    def plot_paper_overview(self, logs: list[LogFile], spec: PlotSpec, figure: Figure):
        axes = figure.subplots(2, 3, squeeze=False)
        ax_time, ax_raw, ax_rel = axes[0]
        ax_loss, ax_area, ax_initial = axes[1]
        base_xlabel, base_ylabel = self.axis_labels(spec)

        labels: list[str] = []
        raw_areas: list[float] = []
        rel_areas: list[float] = []
        tin0_values: list[float] = []
        tout0_values: list[float] = []
        loss_values: list[float] = []

        for log in logs:
            log_index = self.logs.index(log)
            color = color_for_index(log_index)
            t, tin, tout = self.finite_tension_rows(log, spec)
            if not tin:
                continue

            tin_rel, tin0 = self.relative_values(tin)
            tout_rel, tout0 = self.relative_values(tout)
            loss = [a - b for a, b in zip(tin, tout)]
            label = log.label

            ax_time.plot(t, tin, color=color, linewidth=1.0, label=f"{label} Tin")
            ax_time.plot(t, tout, color=color, linewidth=1.0, linestyle="--", alpha=0.75, label=f"{label} Tout")

            ax_raw.plot(tin, tout, color=color, linewidth=1.1, label=label)
            ax_raw.scatter([tin[0]], [tout[0]], s=18, color=color, edgecolors="black", linewidths=0.5, zorder=3)

            ax_rel.plot(tin_rel, tout_rel, color=color, linewidth=1.1, label=label)
            ax_rel.scatter([tin_rel[0]], [tout_rel[0]], s=18, color=color, edgecolors="black", linewidths=0.5, zorder=3)

            ax_loss.plot(t, loss, color=color, linewidth=1.0, label=label)

            labels.append(label)
            raw_areas.append(loop_area(tin, tout))
            rel_areas.append(loop_area(tin_rel, tout_rel))
            tin0_values.append(tin0)
            tout0_values.append(tout0)
            loss_values.append(mean(loss))

        ax_time.set_title("1-a Time Domain Tension")
        ax_time.set_xlabel("Time [s]")
        ax_time.set_ylabel("|F| Tension [N]" if self.force_abs_enabled(spec) else "Tension [N]")
        ax_time.grid(True, alpha=0.3)
        ax_time.legend(fontsize=7, ncols=2)

        ax_raw.set_title("1-b Raw Tension Loop")
        ax_raw.set_xlabel(base_xlabel)
        ax_raw.set_ylabel(base_ylabel)
        ax_raw.grid(True, alpha=0.3)
        ax_raw.axis("equal")
        self.add_identity_line(ax_raw)
        ax_raw.legend(fontsize=8)

        ax_rel.set_title(f"1-c Relative Tension Loop ({self.relative_reference_label()})")
        ax_rel.set_xlabel(f"Delta {base_xlabel}")
        ax_rel.set_ylabel(f"Delta {base_ylabel}")
        ax_rel.grid(True, alpha=0.3)
        ax_rel.axis("equal")
        ax_rel.legend(fontsize=8)

        ax_loss.set_title("2-a Tension Loss")
        ax_loss.set_xlabel("Time [s]")
        ax_loss.set_ylabel("Tin - Tout [N]")
        ax_loss.axhline(0.0, color="black", linewidth=0.8, alpha=0.35)
        ax_loss.grid(True, alpha=0.3)
        ax_loss.legend(fontsize=8)

        x_pos = list(range(len(labels)))
        width = 0.36
        raw_pos = [x - width / 2 for x in x_pos]
        rel_pos = [x + width / 2 for x in x_pos]
        ax_area.bar(raw_pos, raw_areas, width=width, label="Raw area", color="#607d8b")
        ax_area.bar(rel_pos, rel_areas, width=width, label="Relative area", color="#9c27b0")
        ax_area.set_title("2-b Loop Area")
        ax_area.set_ylabel("Area [N^2]")
        ax_area.set_xticks(x_pos)
        ax_area.set_xticklabels(labels, rotation=25, ha="right", fontsize=8)
        ax_area.grid(True, axis="y", alpha=0.3)
        ax_area.legend(fontsize=8)

        tin_pos = [x - width / 2 for x in x_pos]
        tout_pos = [x + width / 2 for x in x_pos]
        ref_label = " min" if self.relative_reference_mode() == "min" else "0"
        ax_initial.bar(tin_pos, tin0_values, width=width, label=f"Tin{ref_label}", color="#1f77b4")
        ax_initial.bar(tout_pos, tout0_values, width=width, label=f"Tout{ref_label}", color="#d62728")
        ax_initial.plot(x_pos, loss_values, color="black", marker="o", linewidth=1.0, label="Mean loss")
        ax_initial.set_title("2-c Reference Tension / Mean Loss")
        ax_initial.set_ylabel("Tension [N]")
        ax_initial.set_xticks(x_pos)
        ax_initial.set_xticklabels(labels, rotation=25, ha="right", fontsize=8)
        ax_initial.grid(True, axis="y", alpha=0.3)
        ax_initial.legend(fontsize=8)

    @staticmethod
    def add_identity_line(ax):
        x0, x1 = ax.get_xlim()
        y0, y1 = ax.get_ylim()
        mn = min(x0, y0)
        mx = max(x1, y1)
        ax.plot([mn, mx], [mn, mx], "k--", linewidth=0.8, alpha=0.35)
        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)

    def save_figure(self):
        if not self.logs:
            QMessageBox.information(self, "저장", "먼저 로그를 추가하세요.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "그림 저장",
            str(self.last_dir / "hysteresis_analysis.png"),
            "PNG Image (*.png);;PDF (*.pdf);;SVG (*.svg);;All Files (*)",
        )
        if not path:
            return
        self.figure.savefig(path, dpi=180)
        QMessageBox.information(self, "저장 완료", f"저장됨:\n{path}")


def main() -> int:
    app = QApplication(sys.argv)
    win = LogAnalysisWindow()
    win.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
