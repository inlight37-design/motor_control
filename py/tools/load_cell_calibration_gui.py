"""
Load Cell GUI — Calibration & Measurement
==========================================
탭 1: Calibration
  - 원하는 무게 포인트 직접 추가/삭제
  - 로딩(↑) / 언로딩(↓) 방향 구분
  - 0 g 포인트 필수 (무부하 또는 접시/지그 포함 기준점)
  - 포인트별 수집 (안정화 감지 + IQR 이상값 제거)
  - Huber 회귀 → scale/offset/R² 계산
  - 히스테리시스 측정 (로딩+언로딩 쌍이 있는 무게에서 자동 계산)
  - 분석 플롯 (캘리브레이션 곡선, 잔차, 히스테리시스)
  - JSON 저장

탭 2: Measurement
  - 듀얼 채널 실시간 표시 (N / kg / g 선택)
  - IIR 저역통과 필터 (α 슬라이더)
  - Tare (영점), Peak Hold, Peak 초기화
  - Over-Tension 임계값 경고
  - 실시간 롤링 그래프
  - CSV 데이터 로깅

의존성: pip install numpy matplotlib scikit-learn Phidget22
"""

import sys
import os
import time
import json
import csv
import threading
import numpy as np
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from collections import deque, defaultdict
from datetime import datetime
import matplotlib
import matplotlib.font_manager as fm
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.lines import Line2D
from sklearn.linear_model import HuberRegressor
from sklearn.metrics import r2_score
from Phidget22.Phidget import *
from Phidget22.Devices.VoltageRatioInput import *

# ── matplotlib 한글 폰트 설정 ─────────────────────────────────
def _setup_kr_font():
    _candidates = ["NanumGothic", "NanumBarunGothic", "NanumGothicCoding",
                   "UnDotum", "Malgun Gothic", "AppleGothic",
                   "Noto Sans CJK KR", "Noto Sans CJK JP", "Noto Serif CJK JP"]
    _available = {f.name for f in fm.fontManager.ttflist}
    for _font in _candidates:
        if _font in _available:
            matplotlib.rcParams["font.family"] = _font
            matplotlib.rcParams["axes.unicode_minus"] = False
            return
    # 캐시에 없으면 시스템 폰트 파일 직접 등록
    import glob
    for pattern in ["/usr/share/fonts/**/NotoSansCJK*Regular*",
                    "/usr/share/fonts/**/Nanum*.ttf"]:
        for path in sorted(glob.glob(pattern, recursive=True)):
            try:
                fm.fontManager.addfont(path)
                matplotlib.rcParams["font.family"] = fm.FontProperties(fname=path).get_name()
                matplotlib.rcParams["axes.unicode_minus"] = False
                return
            except Exception:
                continue
    matplotlib.rcParams["axes.unicode_minus"] = False

_setup_kr_font()
# ──────────────────────────────────────────────────────────────
GRAVITY         = 9.80665
N_CHANNELS      = 2
SAMPLE_INTERVAL = 0.01    # 100 Hz — 장치 최소 간격(~8 ms)보다 여유 있게 설정
GUI_INTERVAL_MS = 50      # 20 Hz GUI refresh
PLOT_SKIP       = 5       # plot 은 5 tick 마다 갱신 (100ms)
# ──────────────────────────────────────────────────────────────


class IIRFilter:
    def __init__(self, alpha: float = 0.1):
        self.alpha = alpha
        self._prev = None

    def process(self, value: float) -> float:
        if self._prev is None:
            self._prev = value
            return value
        out = self.alpha * value + (1.0 - self.alpha) * self._prev
        self._prev = out
        return out

    def reset(self):
        self._prev = None


class ChannelState:
    """Phidget 채널 하나의 상태 (스레드 안전)."""

    def __init__(self, ch_num: int):
        self.ch_num    = ch_num
        self.scale_g   = 1.0    # gram 기반 scale  (Vratio → g)
        self.offset_g  = 0.0    # gram 기반 offset
        self.tare_g    = 0.0
        self.iir       = IIRFilter(alpha=0.1)
        self.connected = False

        # 최신 값 (GUI 폴링용)
        self.raw_ratio  = 0.0
        self.filt_ratio = 0.0
        self.grams      = 0.0
        self.newtons    = 0.0
        self.peak_n     = 0.0

        self._lock = threading.Lock()

    # Phidget 콜백 (백그라운드 스레드에서 호출됨)
    def on_voltage_change(self, _, ratio: float):
        with self._lock:
            filtered = self.iir.process(ratio)
            abs_g    = self.scale_g * filtered + self.offset_g
            net_g    = abs_g - self.tare_g
            net_n    = (net_g / 1000.0) * GRAVITY
            self.raw_ratio  = ratio
            self.filt_ratio = filtered
            self.grams      = net_g
            self.newtons    = net_n
            if abs(net_n) > self.peak_n:
                self.peak_n = abs(net_n)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "raw":       self.raw_ratio,
                "filtered":  self.filt_ratio,
                "grams":     self.grams,
                "newtons":   self.newtons,
                "peak_n":    self.peak_n,
                "connected": self.connected,
            }

    def set_calibration(self, scale_g: float, offset_g: float):
        with self._lock:
            self.scale_g  = scale_g
            self.offset_g = offset_g
            self.tare_g = 0.0
            self.grams = 0.0
            self.newtons = 0.0
            self.peak_n = 0.0
            self.iir.reset()

    def set_tare(self, tare_g: float):
        with self._lock:
            self.tare_g = tare_g

    def reset_peak(self):
        with self._lock:
            self.peak_n = 0.0

    def set_alpha(self, alpha: float):
        with self._lock:
            self.iir.alpha = alpha


# ══════════════════════════════════════════════════════════════
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Load Cell — Calibration & Measurement")
        self.geometry("1280x780")
        self.minsize(1000, 650)

        self.channels: list[ChannelState] = [ChannelState(i) for i in range(N_CHANNELS)]
        self.devices:  list               = [None] * N_CHANNELS

        # 측정 히스토리 (실시간 그래프용)
        maxlen = int(120 / (GUI_INTERVAL_MS / 1000))  # 최대 120초분
        self.hist_t = deque(maxlen=maxlen)
        self.hist_n = [deque(maxlen=maxlen) for _ in range(N_CHANNELS)]
        self.t0 = time.time()

        # CSV 로깅
        self._csv_file   = None
        self._csv_writer = None
        self._logging    = False

        # 임계값
        self.threshold_n       = tk.DoubleVar(value=50.0)
        self.threshold_enabled = tk.BooleanVar(value=False)

        # 채널 활성화 (센서 꽂힌 채널만 체크)
        self.ch_enabled = [tk.BooleanVar(value=(i == 0)) for i in range(N_CHANNELS)]

        self._build_ui()
        self._connect_phidgets()
        self._plot_tick = 0
        self._loop()

    # ──────────────────────────────────────────────────────────
    # Phidget 연결
    # ──────────────────────────────────────────────────────────
    def _connect_phidgets(self):
        for i, ch in enumerate(self.channels):
            try:
                dev = VoltageRatioInput()
                dev.setChannel(i)
                dev.openWaitForAttachment(3000)
                dev.setDataInterval(dev.getMinDataInterval())
                dev.setOnVoltageRatioChangeHandler(ch.on_voltage_change)
                self.devices[i] = dev
                ch.connected    = True
            except PhidgetException:
                ch.connected = False

    def _disconnect_phidgets(self):
        for dev in self.devices:
            if dev:
                try:
                    dev.close()
                except Exception:
                    pass

    # ──────────────────────────────────────────────────────────
    # UI 구성
    # ──────────────────────────────────────────────────────────
    def _build_ui(self):
        # 상태 바 (상단)
        top = tk.Frame(self, bg="#263238", height=36)
        top.pack(fill=tk.X)
        top.pack_propagate(False)
        self._ch_status_lbls = []
        for i in range(N_CHANNELS):
            # 채널 활성화 체크박스
            cb = tk.Checkbutton(top, text=f"CH{i}", variable=self.ch_enabled[i],
                                fg="white", bg="#263238", selectcolor="#37474f",
                                activebackground="#263238", activeforeground="white",
                                font=("Consolas", 10, "bold"))
            cb.pack(side=tk.LEFT, padx=(16, 0))
            lbl = tk.Label(top, text="미연결", fg="#ef9a9a",
                           bg="#263238", font=("Consolas", 10))
            lbl.pack(side=tk.LEFT, padx=(2, 10))
            self._ch_status_lbls.append(lbl)

        # Notebook
        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        cal_tab  = ttk.Frame(nb)
        meas_tab = ttk.Frame(nb)
        nb.add(cal_tab,  text="  ⚙  Calibration  ")
        nb.add(meas_tab, text="  📊  Measurement  ")

        self._build_calibration_tab(cal_tab)
        self._build_measurement_tab(meas_tab)

        # 하단 상태 바
        self._statusbar = tk.Label(self, text="Ready", anchor="w",
                                   relief=tk.SUNKEN, font=("Consolas", 9),
                                   bg="#eceff1")
        self._statusbar.pack(fill=tk.X, side=tk.BOTTOM)

    # ══════════════════════════════════════════════════════════
    # 탭 1: Calibration
    # ══════════════════════════════════════════════════════════
    def _build_calibration_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=2)
        parent.rowconfigure(0, weight=1)

        # ── 왼쪽: 포인트 관리 ─────────────────────────────────
        left = ttk.LabelFrame(parent, text="Calibration Points")
        left.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        # 채널 선택
        row_ch = ttk.Frame(left)
        row_ch.pack(fill=tk.X, padx=8, pady=(8, 2))
        ttk.Label(row_ch, text="채널:").pack(side=tk.LEFT)
        self.cal_ch = tk.IntVar(value=0)
        for i in range(N_CHANNELS):
            ttk.Radiobutton(row_ch, text=f"CH {i}",
                            variable=self.cal_ch, value=i).pack(side=tk.LEFT, padx=6)

        # 접시 무게 입력
        row_dish = ttk.Frame(left)
        row_dish.pack(fill=tk.X, padx=8, pady=(4, 0))
        ttk.Label(row_dish, text="접시 무게 (g):").pack(side=tk.LEFT)
        self._dish_w = tk.DoubleVar(value=0.0)
        self._dish_entry = ttk.Entry(row_dish, textvariable=self._dish_w, width=8)
        self._dish_entry.pack(side=tk.LEFT, padx=6)
        self._dish_note = ttk.Label(row_dish, text="", foreground="gray",
                                    font=("Arial", 8))
        self._dish_note.pack(side=tk.LEFT)

        row_ref = ttk.Frame(left)
        row_ref.pack(fill=tk.X, padx=8, pady=(0, 4))
        self._dish_zero_mode = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            row_ref,
            text="접시/지그 포함 상태를 0 g 기준으로 사용",
            variable=self._dish_zero_mode,
            command=self._on_dish_zero_mode,
        ).pack(side=tk.LEFT)

        # 무게 입력 (추가할 순수 무게)
        row_w = ttk.Frame(left)
        row_w.pack(fill=tk.X, padx=8, pady=4)
        ttk.Label(row_w, text="추가 무게 (g):").pack(side=tk.LEFT)
        self._w_entry = ttk.Entry(row_w, width=10)
        self._w_entry.pack(side=tk.LEFT, padx=6)
        self._w_entry.bind("<KeyRelease>", self._update_total_preview)
        self._w_entry.bind("<Return>", lambda _: self._add_cal_point())
        self._total_preview = ttk.Label(row_w, text="합계: 0 g",
                                        foreground="#1565c0", font=("Consolas", 10, "bold"))
        self._total_preview.pack(side=tk.LEFT, padx=4)
        self._dish_w.trace_add("write", lambda *_: self._update_total_preview())
        ttk.Button(row_w, text="Add", command=self._add_cal_point).pack(side=tk.LEFT, padx=6)
        self._on_dish_zero_mode()

        # ── 방향 선택 (로딩 / 언로딩) ─────────────────────────
        row_dir = ttk.Frame(left)
        row_dir.pack(fill=tk.X, padx=8, pady=(0, 4))
        ttk.Label(row_dir, text="측정 방향:").pack(side=tk.LEFT)
        self._cal_dir = tk.StringVar(value="loading")
        ttk.Radiobutton(row_dir, text="↑ 로딩",
                        variable=self._cal_dir, value="loading").pack(side=tk.LEFT, padx=6)
        ttk.Radiobutton(row_dir, text="↓ 언로딩",
                        variable=self._cal_dir, value="unloading").pack(side=tk.LEFT, padx=4)

        # ── 사이클 선택 ─────────────────────────────────────
        ttk.Label(row_dir, text="  사이클:").pack(side=tk.LEFT, padx=(8, 0))
        self._cal_cycle = tk.IntVar(value=1)
        for c in (1, 2, 3):
            ttk.Radiobutton(row_dir, text=str(c),
                            variable=self._cal_cycle, value=c).pack(side=tk.LEFT, padx=2)

        # 포인트 목록 (Treeview) — 채널+방향+사이클 컬럼
        cols = ("ch", "cycle", "dir", "w", "ratio", "std", "status")
        tree = ttk.Treeview(left, columns=cols, show="headings", height=12)
        tree.heading("ch",     text="CH")
        tree.heading("cycle",  text="Cycle")
        tree.heading("dir",    text="방향")
        tree.heading("w",      text="Load (g)")
        tree.heading("ratio",  text="Mean Ratio")
        tree.heading("std",    text="Std (µV/V)")
        tree.heading("status", text="Status")
        tree.column("ch",     width=38,  anchor="center")
        tree.column("cycle",  width=45,  anchor="center")
        tree.column("dir",    width=65,  anchor="center")
        tree.column("w",      width=75,  anchor="center")
        tree.column("ratio",  width=105, anchor="center")
        tree.column("std",    width=85,  anchor="center")
        tree.column("status", width=80,  anchor="center")
        tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        self._cal_tree = tree

        row_btn = ttk.Frame(left)
        row_btn.pack(fill=tk.X, padx=8, pady=4)
        self._remove_btn = ttk.Button(row_btn, text="Remove",
                                      command=self._remove_cal_point)
        self._remove_btn.pack(side=tk.LEFT)
        self._reset_sample_btn = ttk.Button(row_btn, text="샘플 초기화",
                                            command=self._reset_cal_sample)
        self._reset_sample_btn.pack(side=tk.LEFT, padx=4)
        self._reverse_unload_btn = ttk.Button(row_btn, text="언로딩 역순 생성",
                                              command=self._add_reverse_unloading_points)
        self._reverse_unload_btn.pack(side=tk.LEFT, padx=4)
        self._copy_cycle_btn = ttk.Button(row_btn, text="Cycle 복사",
                                          command=self._copy_cycle_points)
        self._copy_cycle_btn.pack(side=tk.LEFT, padx=4)
        self._save_points_btn = ttk.Button(row_btn, text="포인트 저장",
                                           command=self._save_cal_session)
        self._save_points_btn.pack(side=tk.LEFT, padx=4)
        self._load_points_btn = ttk.Button(row_btn, text="포인트 불러오기",
                                           command=self._load_cal_session)
        self._load_points_btn.pack(side=tk.LEFT, padx=4)
        self._clear_btn = ttk.Button(row_btn, text="Clear All",
                                     command=self._clear_cal_points)
        self._clear_btn.pack(side=tk.LEFT, padx=4)

        self._cal_points: dict = {}   # iid → {weight_g, mean_ratio, std_ratio, direction, cycle, n_rejected}
        self._collecting = threading.Event()

        # ── 오른쪽: 수집 & 결과 ───────────────────────────────
        right = ttk.LabelFrame(parent, text="Data Collection & Results")
        right.grid(row=0, column=1, sticky="nsew", padx=8, pady=8)

        # 라이브 Ratio 표시
        row_live = ttk.Frame(right)
        row_live.pack(fill=tk.X, padx=10, pady=8)
        ttk.Label(row_live, text="Live VoltageRatio:", font=("Consolas", 11)).pack(side=tk.LEFT)
        self._live_ratio = ttk.Label(row_live, text="---",
                                     font=("Consolas", 13, "bold"), foreground="#1565c0")
        self._live_ratio.pack(side=tk.LEFT, padx=10)

        # 안정화 표시
        row_stab = ttk.Frame(right)
        row_stab.pack(fill=tk.X, padx=10)
        ttk.Label(row_stab, text="Stability:").pack(side=tk.LEFT)
        self._stab_bar = tk.Canvas(row_stab, width=220, height=18,
                                   bg="#b0bec5", highlightthickness=1,
                                   highlightbackground="#90a4ae")
        self._stab_bar.pack(side=tk.LEFT, padx=8)
        self._stab_lbl = ttk.Label(row_stab, text="--", font=("Consolas", 9))
        self._stab_lbl.pack(side=tk.LEFT)

        # 수집 설정
        row_cfg = ttk.Frame(right)
        row_cfg.pack(fill=tk.X, padx=10, pady=6)
        ttk.Label(row_cfg, text="수집 시간 (s):").pack(side=tk.LEFT)
        self._collect_sec = tk.DoubleVar(value=15.0)
        ttk.Spinbox(row_cfg, from_=5, to=120, width=6,
                    textvariable=self._collect_sec).pack(side=tk.LEFT, padx=4)
        ttk.Label(row_cfg, text="  안정화 임계값 (µV/V):").pack(side=tk.LEFT)
        self._stab_thresh_uv = tk.DoubleVar(value=3.0)
        ttk.Spinbox(row_cfg, from_=0.5, to=30.0, increment=0.5, width=6,
                    textvariable=self._stab_thresh_uv).pack(side=tk.LEFT, padx=4)

        # 수집 버튼 + 프로그레스
        self._collect_btn = ttk.Button(right, text="▶  Collect for Selected Point",
                                       command=self._start_collection)
        self._collect_btn.pack(padx=10, pady=4)
        self._progress = ttk.Progressbar(right, length=360, mode="determinate")
        self._progress.pack(padx=10)
        self._collect_msg = ttk.Label(right, text="", foreground="#555")
        self._collect_msg.pack(pady=2)

        ttk.Separator(right, orient="horizontal").pack(fill=tk.X, padx=10, pady=8)

        # 회귀 실행 + 플롯 버튼 (나란히)
        row_fit = ttk.Frame(right)
        row_fit.pack(fill=tk.X, padx=10, pady=(2, 0))
        self._fit_unloading = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            row_fit,
            text="회귀에 언로딩 포인트도 포함",
            variable=self._fit_unloading,
        ).pack(side=tk.LEFT)

        btn_row = ttk.Frame(right)
        btn_row.pack(pady=4)
        ttk.Button(btn_row, text="  Run Huber Regression  ",
                   command=self._run_calibration).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_row, text="  Analysis Plot  ",
                   command=self._show_analysis_plot).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_row, text="  JSON → Plot  ",
                   command=self._load_and_plot_json).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_row, text="  JSON → Points  ",
                   command=self._import_points_from_json).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_row, text="  Merge JSONs  ",
                   command=self._merge_calibration_jsons).pack(side=tk.LEFT, padx=6)

        # 결과 텍스트
        self._cal_result = tk.Text(right, height=12, font=("Consolas", 10),
                                   state=tk.DISABLED, bg="#fafafa",
                                   relief=tk.FLAT, bd=1)
        self._cal_result.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        ttk.Button(right, text="Save Calibration (JSON)",
                   command=self._save_calibration).pack(pady=(4, 8))

        self._latest_cal: dict  = {}   # ch_idx → cal dict
        self._last_cal_data     = None # 플롯용 최근 회귀 결과
        self._stab_buf: deque   = deque(maxlen=800)  # (time, ratio) — GUI 루프에서 채움

    # ── Calibration 포인트 관리 ────────────────────────────────
    def _parse_weight(self, text: str) -> float | None:
        """숫자 또는 수식(1205+1000 등)을 float으로 변환. 실패 시 None."""
        text = text.strip()
        if not text:
            return None
        try:
            # +, -, *, / 만 허용하는 안전한 eval
            result = eval(text, {"__builtins__": {}}, {})
            return float(result)
        except Exception:
            return None

    def _update_total_preview(self, *_):
        text = self._w_entry.get()
        parsed = self._parse_weight(text)
        added = parsed if parsed is not None else 0.0
        try:
            dish = self._dish_w.get()
        except Exception:
            dish = 0.0
        zero_mode = self._dish_zero_mode.get()
        total = added if zero_mode else dish + added
        color = "#1565c0" if parsed is not None or not text.strip() else "red"
        label = "기준하중" if zero_mode else "합계"
        suffix = " (접시=0)" if zero_mode else ""
        self._total_preview.config(text=f"{label}: {total:.1f} g{suffix}", foreground=color)

    def _on_dish_zero_mode(self):
        """접시/지그를 기준 0 g로 볼지, 총 무게에 합산할지 전환."""
        zero_mode = self._dish_zero_mode.get()
        state = tk.DISABLED if zero_mode else tk.NORMAL
        self._dish_entry.config(state=state)
        if zero_mode:
            self._dish_note.config(text="(보정식에서 제외됨)")
        else:
            self._dish_note.config(text="(추가 무게에 자동 합산됨)")
        self._update_total_preview()

    def _insert_cal_point(
        self,
        weight_g: float,
        direction: str,
        cycle: int,
        channel: int | None = None,
        mean_ratio: float | None = None,
        std_ratio: float | None = None,
        n_rejected: int | None = None,
        added_weight_g: float | None = None,
        dish_weight_g: float = 0.0,
        reference_mode: str = "total_weight",
        source: str = "",
        status: str | None = None,
    ) -> str:
        """캘리브레이션 포인트를 테이블과 내부 dict에 동시에 추가."""
        direction = direction or "loading"
        if direction not in ("loading", "unloading"):
            direction = "loading"
        cycle = int(cycle or 1)
        if channel is not None:
            try:
                channel = int(channel)
            except Exception:
                channel = None
        dir_lbl = "↑ 로딩" if direction == "loading" else "↓ 언로딩"
        ch_lbl = f"CH{channel}" if channel is not None else "?"
        ratio_txt = f"{mean_ratio:.8f}" if mean_ratio is not None else "---"
        std_txt = f"{std_ratio * 1e6:.2f}" if std_ratio is not None else "---"
        if status is None:
            status = f"JSON {source}" if mean_ratio is not None and source else ("완료" if mean_ratio is not None else "대기")
        iid = self._cal_tree.insert(
            "",
            tk.END,
            values=(ch_lbl, cycle, dir_lbl, f"{weight_g:.1f}", ratio_txt, std_txt, status),
        )
        self._cal_points[iid] = {
            "channel": channel,
            "weight_g": float(weight_g),
            "added_weight_g": float(weight_g if added_weight_g is None else added_weight_g),
            "dish_weight_g": float(dish_weight_g),
            "reference_mode": reference_mode,
            "mean_ratio": None if mean_ratio is None else float(mean_ratio),
            "std_ratio": None if std_ratio is None else float(std_ratio),
            "direction": direction,
            "cycle": cycle,
            "n_rejected": n_rejected,
            "source": source,
            "status": status,
        }
        return iid

    def _add_cal_point(self):
        added = self._parse_weight(self._w_entry.get())
        if added is None:
            messagebox.showerror("오류", "숫자 또는 수식을 입력하세요 (예: 500, 1205+1000)")
            return
        try:
            dish = self._dish_w.get()
        except Exception:
            dish = 0.0
        zero_mode = self._dish_zero_mode.get()
        total    = added if zero_mode else dish + added
        dir_val  = self._cal_dir.get()
        cycle    = self._cal_cycle.get()
        self._insert_cal_point(
            total,
            dir_val,
            cycle,
            added_weight_g=added,
            dish_weight_g=dish,
            reference_mode="dish_zero" if zero_mode else "total_weight",
        )
        self._w_entry.delete(0, tk.END)
        self._update_total_preview()

    def _add_reverse_unloading_points(self):
        """로딩 포인트를 읽어 같은 cycle의 언로딩 포인트를 역순으로 생성."""
        cycle = int(self._cal_cycle.get())
        target_ch = int(self.cal_ch.get())

        selected = [
            self._cal_points[iid]
            for iid in self._cal_tree.selection()
            if iid in self._cal_points
            and self._cal_points[iid].get("direction") == "loading"
        ]

        if selected:
            candidates = selected
        else:
            candidates = [
                d for d in self._cal_points.values()
                if d.get("direction") == "loading"
                and int(d.get("cycle", 1)) == cycle
                and d.get("channel") in (None, target_ch)
            ]
            if not candidates:
                candidates = [
                    d for d in self._cal_points.values()
                    if d.get("direction") == "loading"
                    and int(d.get("cycle", 1)) == cycle
                ]

        loading_points = []
        seen_loading = set()
        for d in candidates:
            key = (
                round(float(d.get("weight_g", 0.0)), 6),
                d.get("reference_mode", "total_weight"),
                round(float(d.get("dish_weight_g", 0.0)), 6),
            )
            if key in seen_loading:
                continue
            seen_loading.add(key)
            loading_points.append(d)

        if not loading_points:
            messagebox.showwarning("경고", f"Cycle {cycle}의 로딩 포인트가 없습니다.")
            return

        existing_unload = set()
        for d in self._cal_points.values():
            if d.get("direction") != "unloading" or int(d.get("cycle", 1)) != cycle:
                continue
            if d.get("channel") not in (None, target_ch):
                continue
            existing_unload.add((
                round(float(d.get("weight_g", 0.0)), 6),
                d.get("reference_mode", "total_weight"),
                round(float(d.get("dish_weight_g", 0.0)), 6),
            ))

        added = 0
        skipped = 0
        for d in reversed(loading_points):
            key = (
                round(float(d.get("weight_g", 0.0)), 6),
                d.get("reference_mode", "total_weight"),
                round(float(d.get("dish_weight_g", 0.0)), 6),
            )
            if key in existing_unload:
                skipped += 1
                continue
            self._insert_cal_point(
                weight_g=float(d["weight_g"]),
                direction="unloading",
                cycle=cycle,
                added_weight_g=float(d.get("added_weight_g", d["weight_g"])),
                dish_weight_g=float(d.get("dish_weight_g", 0.0)),
                reference_mode=d.get("reference_mode", "total_weight"),
                status="역순 대기",
            )
            existing_unload.add(key)
            added += 1

        self._cal_dir.set("unloading")
        messagebox.showinfo(
            "언로딩 생성",
            f"Cycle {cycle} 언로딩 포인트 {added}개 생성\n중복 스킵 {skipped}개",
        )

    def _copy_cycle_points(self):
        """현재 cycle의 포인트 구조를 다른 cycle들로 복사한다."""
        src_cycle = int(self._cal_cycle.get())
        target_ch = int(self.cal_ch.get())
        target_cycles = [c for c in (1, 2, 3) if c != src_cycle]

        selected = [
            self._cal_points[iid]
            for iid in self._cal_tree.selection()
            if iid in self._cal_points
        ]
        if selected:
            source_points = selected
        else:
            source_points = [
                d for d in self._cal_points.values()
                if int(d.get("cycle", 1)) == src_cycle
                and d.get("channel") in (None, target_ch)
            ]
            if not source_points:
                source_points = [
                    d for d in self._cal_points.values()
                    if int(d.get("cycle", 1)) == src_cycle
                ]

        if not source_points:
            messagebox.showwarning("경고", f"Cycle {src_cycle}에 복사할 포인트가 없습니다.")
            return

        existing = set()
        for d in self._cal_points.values():
            existing.add((
                int(d.get("cycle", 1)),
                d.get("direction", "loading"),
                round(float(d.get("weight_g", 0.0)), 6),
                d.get("reference_mode", "total_weight"),
                round(float(d.get("dish_weight_g", 0.0)), 6),
                d.get("channel"),
            ))

        added = 0
        skipped = 0
        for dst_cycle in target_cycles:
            for d in source_points:
                key = (
                    dst_cycle,
                    d.get("direction", "loading"),
                    round(float(d.get("weight_g", 0.0)), 6),
                    d.get("reference_mode", "total_weight"),
                    round(float(d.get("dish_weight_g", 0.0)), 6),
                    d.get("channel"),
                )
                if key in existing:
                    skipped += 1
                    continue
                self._insert_cal_point(
                    weight_g=float(d["weight_g"]),
                    direction=d.get("direction", "loading"),
                    cycle=dst_cycle,
                    channel=None,
                    added_weight_g=float(d.get("added_weight_g", d["weight_g"])),
                    dish_weight_g=float(d.get("dish_weight_g", 0.0)),
                    reference_mode=d.get("reference_mode", "total_weight"),
                    status=f"C{src_cycle} 복사 대기",
                )
                existing.add(key)
                added += 1

        messagebox.showinfo(
            "Cycle 복사",
            f"Cycle {src_cycle} → {', '.join(f'Cycle {c}' for c in target_cycles)}\n"
            f"포인트 {added}개 생성\n중복 스킵 {skipped}개",
        )

    def _ordered_cal_points(self) -> list:
        """테이블 순서대로 캘리브레이션 포인트를 JSON 직렬화 가능한 dict로 반환."""
        points = []
        for iid in self._cal_tree.get_children():
            d = self._cal_points.get(iid)
            if not d:
                continue
            values = self._cal_tree.item(iid).get("values", [])
            status = values[6] if len(values) > 6 else d.get("status", "")
            points.append({
                "channel": d.get("channel"),
                "weight_g": float(d.get("weight_g", 0.0)),
                "added_weight_g": float(d.get("added_weight_g", d.get("weight_g", 0.0))),
                "dish_weight_g": float(d.get("dish_weight_g", 0.0)),
                "reference_mode": d.get("reference_mode", "total_weight"),
                "mean_ratio": d.get("mean_ratio"),
                "std_ratio": d.get("std_ratio"),
                "direction": d.get("direction", "loading"),
                "cycle": int(d.get("cycle", 1)),
                "n_rejected": d.get("n_rejected"),
                "source": d.get("source", ""),
                "status": status,
            })
        return points

    def _save_cal_session(self):
        """캘리브레이션 중간 포인트 테이블을 세션 JSON으로 저장."""
        points = self._ordered_cal_points()
        if not points:
            messagebox.showwarning("경고", "저장할 포인트가 없습니다.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialfile=f"cal_points_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        )
        if not path:
            return
        data = {
            "type": "load_cell_calibration_session",
            "version": 1,
            "timestamp": datetime.now().isoformat(),
            "settings": {
                "current_channel": int(self.cal_ch.get()),
                "current_cycle": int(self._cal_cycle.get()),
                "dish_zero_mode": bool(self._dish_zero_mode.get()),
                "dish_weight_g": float(self._dish_w.get()),
                "fit_includes_unloading": bool(self._fit_unloading.get()),
            },
            "points": points,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        messagebox.showinfo("포인트 저장", f"저장 완료\n{path}")

    def _points_from_calibration_json(self, data: dict, source: str) -> list:
        """완성된 캘리브레이션 JSON의 channels.points를 세션 포인트 형식으로 변환."""
        points = []
        channels = self._channels_from_cal_json(data)
        for ch_key, cal in channels.items():
            try:
                ch_idx = int(ch_key)
            except Exception:
                ch_idx = None
            reference_mode = cal.get("reference_mode", "total_weight")
            dish_weight_g = float(cal.get("dish_weight_g", 0.0) or 0.0)
            for p in cal.get("points", []):
                if "weight_g" not in p or "mean_ratio" not in p:
                    continue
                std_ratio = p.get("std_ratio")
                if std_ratio is None:
                    std_ratio = float(p.get("std_uv_v", 0.0) or 0.0) * 1e-6
                weight_g = float(p["weight_g"])
                added_weight_g = p.get("added_weight_g")
                if added_weight_g is None:
                    added_weight_g = weight_g if reference_mode == "dish_zero" else weight_g - dish_weight_g
                points.append({
                    "channel": ch_idx,
                    "weight_g": weight_g,
                    "added_weight_g": float(added_weight_g),
                    "dish_weight_g": dish_weight_g,
                    "reference_mode": reference_mode,
                    "mean_ratio": float(p["mean_ratio"]),
                    "std_ratio": float(std_ratio),
                    "direction": p.get("direction") or "loading",
                    "cycle": int(p.get("cycle") or 1),
                    "n_rejected": p.get("n_rejected"),
                    "source": source,
                    "status": f"JSON {source}",
                })
        return points

    def _load_cal_session(self):
        """저장된 포인트 세션 JSON을 불러와 캘리브레이션을 이어서 진행."""
        path = filedialog.askopenfilename(
            title="캘리브레이션 포인트/세션 불러오기",
            filetypes=[("JSON", "*.json"), ("All", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror("오류", f"불러오기 실패: {e}")
            return

        source = os.path.basename(path)
        if data.get("type") == "load_cell_calibration_session" and "points" in data:
            points = data.get("points", [])
            settings = data.get("settings", {})
        elif "channels" in data or ("scale" in data and "offset" in data):
            points = self._points_from_calibration_json(data, source)
            settings = {}
        else:
            messagebox.showerror("오류", "포인트 세션 또는 캘리브레이션 JSON이 아닙니다.")
            return

        if not points:
            messagebox.showwarning("경고", "불러올 포인트가 없습니다.")
            return

        replace = True
        if self._cal_points:
            replace = messagebox.askyesno(
                "불러오기",
                "현재 포인트를 지우고 불러올까요?\n\n"
                "예: 현재 테이블 대체\n"
                "아니오: 현재 테이블 뒤에 추가",
            )
        if replace:
            self._clear_cal_points()
            self._latest_cal.clear()
            self._last_cal_data = None

        if settings:
            try:
                self.cal_ch.set(int(settings.get("current_channel", self.cal_ch.get())))
                self._cal_cycle.set(int(settings.get("current_cycle", self._cal_cycle.get())))
                self._dish_zero_mode.set(bool(settings.get("dish_zero_mode", self._dish_zero_mode.get())))
                self._dish_w.set(float(settings.get("dish_weight_g", self._dish_w.get())))
                self._fit_unloading.set(bool(settings.get("fit_includes_unloading", self._fit_unloading.get())))
                self._on_dish_zero_mode()
            except Exception:
                pass

        imported = 0
        skipped = 0
        for p in points:
            try:
                self._insert_cal_point(
                    weight_g=float(p["weight_g"]),
                    direction=p.get("direction") or "loading",
                    cycle=int(p.get("cycle") or 1),
                    channel=p.get("channel"),
                    mean_ratio=p.get("mean_ratio"),
                    std_ratio=p.get("std_ratio"),
                    n_rejected=p.get("n_rejected"),
                    added_weight_g=p.get("added_weight_g"),
                    dish_weight_g=float(p.get("dish_weight_g", 0.0) or 0.0),
                    reference_mode=p.get("reference_mode", "total_weight"),
                    source=p.get("source", source),
                    status=p.get("status"),
                )
                imported += 1
            except Exception:
                skipped += 1
        messagebox.showinfo("포인트 불러오기", f"포인트 {imported}개 불러옴\n스킵 {skipped}개")

    def _remove_cal_point(self):
        for iid in self._cal_tree.selection():
            self._cal_tree.delete(iid)
            self._cal_points.pop(iid, None)

    def _reset_cal_sample(self):
        """선택된 포인트의 수집 데이터만 초기화 (무게·방향·사이클은 유지)."""
        sel = self._cal_tree.selection()
        if not sel:
            messagebox.showwarning("경고", "초기화할 포인트를 선택하세요")
            return
        for iid in sel:
            pt = self._cal_points[iid]
            pt["mean_ratio"] = None
            pt["std_ratio"]  = None
            pt["n_rejected"] = None
            pt["channel"] = None
            pt["status"] = "대기"
            dir_lbl = "↑ 로딩" if pt["direction"] == "loading" else "↓ 언로딩"
            w = f"{pt['weight_g']:.1f}"
            self._cal_tree.item(iid, values=("?", pt.get("cycle", 1), dir_lbl, w, "---", "---", "대기"))

    def _clear_cal_points(self):
        for iid in list(self._cal_points):
            self._cal_tree.delete(iid)
        self._cal_points.clear()

    # ── 데이터 수집 ───────────────────────────────────────────
    def _start_collection(self):
        sel = self._cal_tree.selection()
        if not sel:
            messagebox.showwarning("경고", "포인트를 먼저 선택하세요")
            return
        if self._collecting.is_set():
            return
        ch_idx = self.cal_ch.get()
        if not self.channels[ch_idx].connected:
            messagebox.showerror("오류", f"CH{ch_idx} 연결되지 않음")
            return
        try:
            thresh = float(self._stab_thresh_uv.get()) * 1e-6
            ctime = float(self._collect_sec.get())
        except Exception:
            messagebox.showerror("오류", "수집 시간/안정화 임계값을 확인하세요")
            return
        self._collecting.set()
        self._collect_btn.state(["disabled"])
        self._remove_btn.state(["disabled"])
        self._reset_sample_btn.state(["disabled"])
        self._clear_btn.state(["disabled"])
        self._stab_buf.clear()
        iid = sel[0]
        threading.Thread(target=self._collect_worker,
                         args=(iid, ch_idx, thresh, ctime), daemon=True).start()

    def _collect_worker(self, iid: str, ch_idx: int, thresh: float, ctime: float):
        dev    = self.devices[ch_idx]

        # ── 1. 안정화 대기 ────────────────────────────────────
        self._set_msg("안정화 대기 중...", "#1565c0")
        buf = []
        deadline = time.time() + 60.0
        stable = False
        while time.time() < deadline:
            try:
                v = dev.getVoltageRatio()
                now = time.time()
                buf.append((now, v))
                buf = [(t, x) for t, x in buf if now - t <= 3.0]
                if len(buf) > 50:
                    vals  = [x for _, x in buf]
                    times = [t - buf[0][0] for t, _ in buf]
                    std_v = np.std(vals)
                    slope = np.polyfit(times, vals, 1)[0]
                    if std_v < thresh and abs(slope) < thresh / 2.0:
                        stable = True
                        break
                time.sleep(SAMPLE_INTERVAL)
            except Exception:
                pass

        if not stable:
            self._set_msg("안정화 타임아웃 — 강제 수집", "#e65100")
        else:
            self._set_msg("수집 중...", "#2e7d32")

        # ── 2. 데이터 수집 ────────────────────────────────────
        samples = []
        start = time.time()
        while time.time() - start < ctime:
            try:
                samples.append(dev.getVoltageRatio())
                time.sleep(SAMPLE_INTERVAL)
            except Exception:
                pass
            self.after(0, self._set_progress,
                       (time.time() - start) / ctime * 100)

        # ── 3. IQR 이상값 제거 ────────────────────────────────
        pt      = self._cal_points[iid]
        dir_lbl = "↑ 로딩" if pt["direction"] == "loading" else "↓ 언로딩"
        try:
            arr = np.array(samples)
            if len(arr) < 10:
                raise ValueError("샘플 부족 (수집된 샘플이 10개 미만)")

            q1, q3 = np.percentile(arr, [25, 75])
            iqr    = q3 - q1
            filt   = arr[(arr >= q1 - 1.5 * iqr) & (arr <= q3 + 1.5 * iqr)]
            n_rej  = len(arr) - len(filt)

            if len(filt) == 0:
                raise ValueError("이상값 제거 후 샘플 없음")

            mean_v = float(np.mean(filt))
            std_v  = float(np.std(filt))

            pt["mean_ratio"] = mean_v
            pt["std_ratio"]  = std_v
            pt["n_rejected"] = n_rej
            pt["channel"]    = ch_idx
            pt["status"]     = "완료"

            cyc = pt.get("cycle", 1)
            w0 = f"{pt['weight_g']:.1f}"
            new_vals = (f"CH{ch_idx}", cyc, dir_lbl, w0, f"{mean_v:.8f}", f"{std_v * 1e6:.2f}", "완료")
            self.after(0, lambda v=new_vals: self._cal_tree.item(iid, values=v))
            self._set_msg(f"완료 — {len(filt)}개 샘플, 이상값 {n_rej}개 제거", "#2e7d32")

        except (ValueError, KeyError) as e:
            cyc = pt.get("cycle", 1)
            w0 = f"{pt['weight_g']:.1f}"
            pt["status"] = "수집 실패"
            fail_vals = (f"CH{ch_idx}", cyc, dir_lbl, w0, "---", "---", "수집 실패")
            self.after(0, lambda v=fail_vals: self._cal_tree.item(iid, values=v))
            self._set_msg(f"수집 실패 — {e}", "#c62828")

        finally:
            self.after(0, self._set_progress, 0)
            self._collecting.clear()
            self.after(0, lambda: self._collect_btn.state(["!disabled"]))
            self.after(0, lambda: self._remove_btn.state(["!disabled"]))
            self.after(0, lambda: self._reset_sample_btn.state(["!disabled"]))
            self.after(0, lambda: self._clear_btn.state(["!disabled"]))

    def _set_progress(self, val: float):
        self._progress["value"] = val

    def _set_msg(self, msg: str, color: str = "#555"):
        self.after(0, lambda: self._collect_msg.config(text=msg, foreground=color))

    # ── 회귀 실행 ─────────────────────────────────────────────
    def _run_calibration(self):
        ch_idx = self.cal_ch.get()
        ready = []
        skipped_other_ch = 0
        reference_modes = set()
        dish_weights = []
        for d in self._cal_points.values():
            if d["mean_ratio"] is None:
                continue
            if d.get("channel") != ch_idx:
                skipped_other_ch += 1
                continue
            reference_modes.add(d.get("reference_mode", "total_weight"))
            dish_weights.append(float(d.get("dish_weight_g", 0.0)))
            ready.append(
                (d["weight_g"], d["mean_ratio"], d["std_ratio"] or 0.0,
                 d.get("direction", "loading") or "loading", d.get("n_rejected") or 0,
                 d.get("cycle", 1))
            )
        if len(ready) < 3:
            extra = f"\n다른 채널 포인트 {skipped_other_ch}개는 제외했습니다." if skipped_other_ch else ""
            messagebox.showerror("오류", f"CH{ch_idx}에서 수집된 포인트가 3개 이상 필요합니다.{extra}")
            return
        if len(reference_modes) > 1:
            messagebox.showerror(
                "오류",
                "접시 기준 0 g 포인트와 총무게 기준 포인트가 섞여 있습니다.\n"
                "샘플 초기화 후 한 방식으로 다시 수집하세요.")
            return

        reference_mode = next(iter(reference_modes)) if reference_modes else "total_weight"
        reference_label = (
            "접시/지그 포함 상태 = 0 g"
            if reference_mode == "dish_zero"
            else "접시 무게를 포함한 총 무게"
        )
        dish_weight_g = dish_weights[0] if dish_weights else 0.0

        # 0 g 포인트 필수 확인 (±1 g 허용)
        has_zero = any(abs(p[0]) < 1.0 for p in ready)
        if not has_zero:
            messagebox.showerror(
                "오류",
                "0 g 기준 포인트가 필요합니다.\n"
                "접시/지그 기준 모드에서는 접시만 걸린 상태에서 0 g 포인트를 수집하세요.")
            return

        wg      = np.array([p[0] for p in ready])
        rat     = np.array([p[1] for p in ready])
        std_arr = np.array([p[2] for p in ready])
        dirs    = [p[3] for p in ready]
        nrej    = [p[4] for p in ready]
        cycles  = [p[5] for p in ready]
        fn      = (wg / 1000.0) * GRAVITY    # Newton

        dirs_arr    = np.array(dirs)
        load_mask   = dirs_arr == "loading"
        unload_mask = dirs_arr == "unloading"

        # 회귀 기준 선택: 실험용은 로딩+언로딩 평균 보정선, 센서 평가용은 로딩 기준선.
        if load_mask.sum() < 3:
            messagebox.showerror("오류", "로딩(↑) 포인트가 3개 이상 필요합니다")
            return

        # 0 g는 반드시 로딩 방향으로 수집돼야 함
        if not any(abs(wg[i]) < 1.0 for i in range(len(wg)) if load_mask[i]):
            messagebox.showerror("오류", "0 g 기준 포인트는 로딩(↑) 방향으로 수집해야 합니다")
            return

        fit_unloading = self._fit_unloading.get()
        fit_mask = (load_mask | unload_mask) if fit_unloading else load_mask
        if fit_mask.sum() < 3:
            messagebox.showerror("오류", "회귀에 사용할 포인트가 3개 이상 필요합니다")
            return
        basis_label = "로딩+언로딩" if fit_unloading else "로딩만"
        basis_key = "loading_unloading" if fit_unloading else "loading_only"

        model = HuberRegressor(epsilon=1.35, alpha=0.0)
        model.fit(rat[fit_mask].reshape(-1, 1), fn[fit_mask])

        # 전체 포인트에 대해 캘리브레이션 선 예측값 계산
        y_pred_all  = model.predict(rat.reshape(-1, 1))
        r2          = r2_score(fn[fit_mask], y_pred_all[fit_mask])

        scale_n  = float(model.coef_[0])
        offset_n = float(model.intercept_)
        # Newton 기반 → gram 기반으로 변환 (load_cell.py 방식과 호환)
        scale_g  = scale_n  / GRAVITY * 1000.0
        offset_g = offset_n / GRAVITY * 1000.0

        # 잔차: 로딩=캘리브레이션 피팅 품질, 언로딩=히스테리시스 크기
        residuals_g = (fn - y_pred_all) / GRAVITY * 1000.0

        # ── 히스테리시스 계산 ──────────────────────────────────
        # 언로딩 포인트를 로딩 기반 캘리브레이션 선에 대입 → 편차 = 히스테리시스
        hyst_data: dict[float, float] = {}
        if unload_mask.any():
            for w_actual, res_g in zip(wg[unload_mask], residuals_g[unload_mask]):
                key = round(w_actual, 1)
                hyst_data[key] = max(hyst_data.get(key, 0.0), abs(res_g))

        max_hyst_g = max(hyst_data.values()) if hyst_data else None

        # ── 반복성 (Repeatability) 계산 ──────────────────────
        # 같은 무게+방향에 대해 사이클 간 ratio 편차 → 반복성
        repeat_groups = defaultdict(list)  # (weight, direction) → [mean_ratio, ...]
        for w, r, d, cyc in zip(wg, rat, dirs, cycles):
            repeat_groups[(round(w, 1), d)].append(r)
        repeatability = {}  # (weight, direction) → std of ratios across cycles
        for key, ratios in repeat_groups.items():
            if len(ratios) >= 2:
                repeatability[key] = float(np.std(ratios))
        max_repeat_uv = max(v * 1e6 for v in repeatability.values()) if repeatability else None

        # ── 결과 저장 ──────────────────────────────────────────
        self._latest_cal[ch_idx] = {
            "reference_mode": reference_mode,
            "reference_label": reference_label,
            "dish_weight_g": dish_weight_g,
            "weight_unit": "g",
            "regression_basis": basis_key,
            "fit_includes_unloading": bool(fit_unloading),
            "weight_definition": (
                "additional load after dish/fixture baseline"
                if reference_mode == "dish_zero"
                else "total applied load including dish/fixture"
            ),
            "scale_n":  scale_n,  "offset_n": offset_n,
            "scale_g":  scale_g,  "offset_g": offset_g,
            "r2":       r2,
            "max_residual_g":   float(max(abs(residuals_g[fit_mask]))),
            "n_points_loading": int(load_mask.sum()),
            "n_points_unloading": int(unload_mask.sum()),
            "n_points_fit": int(fit_mask.sum()),
            "max_hysteresis_g": float(max_hyst_g) if max_hyst_g is not None else None,
            "hysteresis_by_weight_g": {str(w): float(h) for w, h in hyst_data.items()},
            "max_repeatability_uv": float(max_repeat_uv) if max_repeat_uv is not None else None,
            "repeatability_by_weight_uv": {
                f"{w}_{d}": float(s * 1e6)
                for (w, d), s in repeatability.items()
            },
            "points": [
                {
                    "weight_g":   float(w),
                    "mean_ratio": float(r),
                    "std_uv_v":   float(s * 1e6),
                    "residual_g": float(res),
                    "direction":  d,
                    "cycle":      int(cyc),
                    "n_rejected": int(nj),
                }
                for w, r, s, res, d, cyc, nj in zip(wg, rat, std_arr, residuals_g, dirs, cycles, nrej)
            ],
        }
        self.channels[ch_idx].set_calibration(scale_g, offset_g)

        # ── 플롯용 데이터 보관 ─────────────────────────────────
        self._last_cal_data = {
            "wg": wg, "rat": rat, "fn": fn, "y_pred": y_pred_all,
            "residuals_g": residuals_g, "dirs": dirs, "cycles": cycles,
            "load_mask": load_mask, "fit_mask": fit_mask,
            "hyst_data": hyst_data,
            "repeatability": repeatability,
            "scale_g": scale_g, "offset_g": offset_g, "r2": r2,
            "regression_basis": basis_key,
        }

        # ── 결과 텍스트 ────────────────────────────────────────
        lines = [
            f"=== CH{ch_idx} 캘리브레이션 결과 ===",
            f"기준           : {reference_label}",
            f"회귀 기준      : {basis_label}",
            f"R² ({basis_label}) : {r2:.6f}",
            f"Scale  (N기반) : {scale_n:.6e}",
            f"Offset (N기반) : {offset_n:.6e}",
            f"Scale  (g기반) : {scale_g:.4f}",
            f"Offset (g기반) : {offset_g:.4f}",
            f"공식           : F(N) = {scale_n:.4e} × Vratio + {offset_n:.4e}",
            f"로딩 포인트    : {load_mask.sum()}개  /  언로딩 포인트: {unload_mask.sum()}개  /  회귀 사용: {fit_mask.sum()}개",
            "",
            f"{'Cyc':^3}  {'방향':^6}  {'하중':>7}  {'잔차(=히스)':>11}  {'이상값 제거':>8}",
        ] + [
            f"{cyc:^3}  {'↑로딩' if d=='loading' else '↓언로딩':^6}  {w:>6.0f}g  {res:>+9.2f}g  {nj:>5}개"
            for w, res, d, nj, cyc in zip(wg, residuals_g, dirs, nrej, cycles)
        ] + [
            f"\n회귀 사용 포인트 최대 잔차: {max(abs(residuals_g[fit_mask])):.2f} g",
        ]

        if hyst_data:
            lines += ["", "=== 히스테리시스 ==="]
            for w_key, h in sorted(hyst_data.items()):
                lines.append(f"  {w_key:.1f} g → {h:.2f} g")
            lines.append(f"최대 히스테리시스: {max_hyst_g:.2f} g")
        else:
            lines += ["", "(히스테리시스: 로딩+언로딩 쌍 없음 — Analysis Plot 참고)"]

        if repeatability:
            lines += ["", "=== 반복성 (Repeatability) ==="]
            for (w_key, d_key), std_r in sorted(repeatability.items()):
                d_lbl = "↑로딩" if d_key == "loading" else "↓언로딩"
                lines.append(f"  {w_key:.1f} g ({d_lbl}) → σ = {std_r * 1e6:.2f} µV/V")
            lines.append(f"최대 반복성 편차: {max_repeat_uv:.2f} µV/V")
        else:
            lines += ["", "(반복성: 같은 무게에 대해 2사이클 이상 데이터 필요)"]

        self._cal_result.config(state=tk.NORMAL)
        self._cal_result.delete("1.0", tk.END)
        self._cal_result.insert(tk.END, "\n".join(lines))
        self._cal_result.config(state=tk.DISABLED)
        hyst_str = f", 최대 히스테리시스 {max_hyst_g:.2f}g" if max_hyst_g else ""
        self._set_status(f"CH{ch_idx} 캘리브레이션 완료 — R² = {r2:.5f}{hyst_str}")

    # ── 분석 플롯 창 ──────────────────────────────────────────
    def _show_analysis_plot(self):
        if self._last_cal_data is None:
            messagebox.showwarning("경고", "먼저 캘리브레이션을 실행하세요")
            return

        d         = self._last_cal_data
        wg        = d["wg"]
        rat       = d["rat"]
        residuals_g = d["residuals_g"]
        dirs      = d["dirs"]
        cycles    = d["cycles"]
        hyst_data = d["hyst_data"]
        repeat_data = d["repeatability"]
        scale_g   = d["scale_g"]
        offset_g  = d["offset_g"]
        basis = d.get("regression_basis", "")
        basis_lbl = "로딩+언로딩" if basis == "loading_unloading" else ("로딩만" if basis == "loading_only" else "")

        has_hyst   = bool(hyst_data)
        has_repeat = bool(repeat_data)
        n_cols     = 2 + int(has_hyst) + int(has_repeat)

        win = tk.Toplevel(self)
        win.title("캘리브레이션 분석 플롯")
        win.geometry(f"{min(n_cols * 370, 1500)}x520")

        fig = Figure(figsize=(n_cols * 3.7, 5), tight_layout=True)

        # 사이클별 색상·마커
        _cycle_colors  = {1: "#1565c0", 2: "#2e7d32", 3: "#e65100"}
        _cycle_markers_l = {1: "o", 2: "s", 3: "D"}    # 로딩: 원, 사각, 다이아
        _cycle_markers_u = {1: "^", 2: "v", 3: "P"}    # 언로딩: 삼각, 역삼각, 플러스

        def style(direction, cycle):
            c = _cycle_colors.get(cycle, "#555")
            if direction == "loading":
                m = _cycle_markers_l.get(cycle, "o")
            else:
                m = _cycle_markers_u.get(cycle, "^")
            return c, m

        # ── Subplot 1: 캘리브레이션 곡선 ──────────────────────
        ax1 = fig.add_subplot(1, n_cols, 1)
        rat_line = np.linspace(rat.min() * 0.9995, rat.max() * 1.0005, 200)
        wg_line  = (scale_g * rat_line + offset_g)
        ax1.plot(rat_line, wg_line, "k-", lw=1.5, label="Fit", zorder=1)
        for w, r, direc, cyc in zip(wg, rat, dirs, cycles):
            c, m = style(direc, cyc)
            ax1.scatter(r, w, color=c, marker=m, s=30, edgecolors="k",
                        linewidths=0.3, zorder=5)
        # 범례: 사이클별
        legend_elems = [Line2D([0], [0], color="k", lw=1.5, label="Fit")]
        unique_cycles = sorted(set(cycles))
        for cyc in unique_cycles:
            cc = _cycle_colors.get(cyc, "#555")
            legend_elems.append(
                Line2D([0], [0], marker=_cycle_markers_l.get(cyc, "o"), color="w",
                       markerfacecolor=cc, label=f"Cyc{cyc} ↑로딩", markersize=7))
            legend_elems.append(
                Line2D([0], [0], marker=_cycle_markers_u.get(cyc, "^"), color="w",
                       markerfacecolor=cc, label=f"Cyc{cyc} ↓언로딩", markersize=7))
        ax1.legend(handles=legend_elems, fontsize=6, loc="best")
        ax1.set_xlabel("Voltage Ratio")
        ax1.set_ylabel("Weight (g)")
        r2_val = d.get("r2")
        r2_str = f"\nR² = {r2_val:.7f}" if r2_val is not None else ""
        basis_str = f" ({basis_lbl})" if basis_lbl else ""
        ax1.set_title(f"캘리브레이션 곡선{basis_str}{r2_str}")
        ax1.grid(True, alpha=0.3)

        # ── Subplot 2: 잔차 ───────────────────────────────────
        ax2 = fig.add_subplot(1, n_cols, 2)
        for w, res, direc, cyc in zip(wg, residuals_g, dirs, cycles):
            c, m = style(direc, cyc)
            ax2.scatter(w, res, color=c, marker=m, s=30, edgecolors="k",
                        linewidths=0.3, zorder=5)
        ax2.axhline(y=0, color="k", lw=1, ls="--")
        ax2.set_xlabel("Weight (g)")
        ax2.set_ylabel("Residual (g)")
        ax2.set_title("잔차 (Residuals)")
        ax2.grid(True, alpha=0.3)

        # ── Subplot 3: 히스테리시스 (있을 때만) ──────────────
        subplot_idx = 3
        if has_hyst:
            ax3 = fig.add_subplot(1, n_cols, subplot_idx)
            sorted_w = sorted(hyst_data)
            w_labels = [f"{w/1000:.1f}kg" if w >= 1000 else f"{w:.0f}g"
                        for w in sorted_w]
            h_vals   = [hyst_data[w] for w in sorted_w]
            x_pos    = np.arange(len(w_labels))
            bars = ax3.bar(x_pos, h_vals, color="#7b1fa2", alpha=0.75, width=0.6)
            ax3.set_xticks(x_pos)
            ax3.set_xticklabels(w_labels, rotation=45, ha="right", fontsize=7)
            for bar, val in zip(bars, h_vals):
                ax3.text(bar.get_x() + bar.get_width() / 2,
                         bar.get_height(),
                         f"{val:.1f}", ha="center", va="bottom",
                         fontsize=7, color="black")
            ax3.set_xlabel("Weight")
            ax3.set_ylabel("Hysteresis (g)")
            ax3.set_title(f"히스테리시스\n최대: {max(h_vals):.1f} g")
            ax3.grid(True, alpha=0.3, axis="y")
            subplot_idx += 1

        # ── Subplot 4: 반복성 (있을 때만) ────────────────────
        if has_repeat:
            ax_r = fig.add_subplot(1, n_cols, subplot_idx)
            sorted_keys = sorted(repeat_data.keys())
            rpt_labels = []
            rpt_vals   = []
            ratio_to_g = abs(scale_g)  # ratio → g 변환 계수
            for (w_key, d_key) in sorted_keys:
                d_lbl = "↑" if d_key == "loading" else "↓"
                w_short = f"{w_key/1000:.1f}k" if w_key >= 1000 else f"{w_key:.0f}"
                rpt_labels.append(f"{w_short}{d_lbl}")
                rpt_vals.append(repeat_data[(w_key, d_key)] * ratio_to_g)  # g 단위
            x_pos = np.arange(len(rpt_labels))
            bars = ax_r.bar(x_pos, rpt_vals, color="#00695c", alpha=0.75, width=0.6)
            ax_r.set_xticks(x_pos)
            ax_r.set_xticklabels(rpt_labels, rotation=45, ha="right", fontsize=6)
            for bar, val in zip(bars, rpt_vals):
                ax_r.text(bar.get_x() + bar.get_width() / 2,
                         bar.get_height(),
                         f"{val:.1f}", ha="center", va="bottom",
                         fontsize=6, color="black")
            ax_r.set_xlabel("Weight")
            ax_r.set_ylabel("Repeatability σ (g)")
            ax_r.set_title(f"반복성\n최대 σ: {max(rpt_vals):.1f} g")
            ax_r.grid(True, alpha=0.3, axis="y")

        canvas = FigureCanvasTkAgg(fig, win)
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        canvas.draw()

    def _load_and_plot_json(self):
        """저장된 캘리브레이션 JSON을 불러와서 분석 플롯을 띄움."""
        path = filedialog.askopenfilename(
            filetypes=[("JSON", "*.json"), ("All", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror("오류", f"JSON 로드 실패: {e}")
            return

        # 첫 번째 채널 데이터 사용
        channels = data.get("channels", {})
        if not channels:
            messagebox.showerror("오류", "채널 데이터가 없습니다")
            return
        ch_key = list(channels.keys())[0]
        cal = channels[ch_key]
        pts = cal.get("points", [])
        if len(pts) < 2:
            messagebox.showerror("오류", "포인트가 부족합니다")
            return

        wg  = np.array([p["weight_g"] for p in pts])
        rat = np.array([p["mean_ratio"] for p in pts])
        dirs   = [p.get("direction") or "loading" for p in pts]
        cycles = [p.get("cycle") or 1 for p in pts]

        scale_g  = cal.get("scale_g", 0.0)
        offset_g = cal.get("offset_g", 0.0)

        # 잔차 재계산
        fn = (wg / 1000.0) * GRAVITY
        scale_n  = cal.get("scale_n", scale_g * GRAVITY / 1000.0)
        offset_n = cal.get("offset_n", offset_g * GRAVITY / 1000.0)
        y_pred   = scale_n * rat + offset_n
        residuals_g = (fn - y_pred) / GRAVITY * 1000.0

        dirs_arr    = np.array(dirs)
        load_mask   = dirs_arr == "loading"

        # 히스테리시스 복원
        hyst_data = {}
        for k, v in cal.get("hysteresis_by_weight_g", {}).items():
            hyst_data[float(k)] = float(v)

        # 반복성 복원
        repeatability = {}
        for k, v in cal.get("repeatability_by_weight_uv", {}).items():
            parts = k.rsplit("_", 1)
            if len(parts) == 2:
                repeatability[(float(parts[0]), parts[1])] = float(v) * 1e-6  # µV/V → ratio

        self._last_cal_data = {
            "wg": wg, "rat": rat, "fn": fn, "y_pred": y_pred,
            "residuals_g": residuals_g, "dirs": dirs, "cycles": cycles,
            "load_mask": load_mask, "fit_mask": load_mask,
            "hyst_data": hyst_data,
            "repeatability": repeatability,
            "scale_g": scale_g, "offset_g": offset_g,
            "r2": cal.get("r2", None),
            "regression_basis": cal.get("regression_basis", "unknown"),
        }
        self._show_analysis_plot()

    def _channels_from_cal_json(self, data: dict) -> dict:
        """신/구 캘리브레이션 JSON을 channels dict 형태로 정규화."""
        if "channels" in data:
            return data["channels"]
        if "scale_g" in data and "offset_g" in data:
            return {"0": {"scale_g": data["scale_g"], "offset_g": data["offset_g"], "points": []}}
        if "scale_n" in data and "offset_n" in data:
            return {"0": {"scale_n": data["scale_n"], "offset_n": data["offset_n"], "points": []}}
        if "scale" in data and "offset" in data:
            return {"0": {"scale_n": data["scale"], "offset_n": data["offset"], "points": []}}
        return {}

    def _import_points_from_json(self):
        """저장된 캘리브레이션 JSON의 points를 현재 테이블로 가져와 재회귀에 사용."""
        paths = filedialog.askopenfilenames(
            title="캘리브레이션 JSON 포인트 가져오기",
            filetypes=[("JSON", "*.json"), ("All", "*.*")],
        )
        if not paths:
            return
        preserve_channel = messagebox.askyesno(
            "채널 선택",
            "JSON 안의 CH 번호를 그대로 가져올까요?\n\n"
            "예: JSON의 CH0/CH1 유지\n"
            "아니오: 현재 선택된 CH로 모두 가져오기",
        )
        target_ch = self.cal_ch.get()
        imported = 0
        skipped = 0
        for path in paths:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                channels = self._channels_from_cal_json(data)
            except Exception:
                skipped += 1
                continue
            for ch_key, cal in channels.items():
                try:
                    src_ch = int(ch_key)
                except Exception:
                    src_ch = target_ch
                ch_idx = src_ch if preserve_channel else target_ch
                if not (0 <= ch_idx < N_CHANNELS):
                    skipped += 1
                    continue
                reference_mode = cal.get("reference_mode", "total_weight")
                dish_weight_g = float(cal.get("dish_weight_g", 0.0) or 0.0)
                source = os.path.basename(path)
                for p in cal.get("points", []):
                    if "weight_g" not in p or "mean_ratio" not in p:
                        skipped += 1
                        continue
                    std_ratio = p.get("std_ratio")
                    if std_ratio is None:
                        std_ratio = float(p.get("std_uv_v", 0.0) or 0.0) * 1e-6
                    weight_g = float(p["weight_g"])
                    added_weight_g = p.get("added_weight_g")
                    if added_weight_g is None:
                        added_weight_g = weight_g if reference_mode == "dish_zero" else weight_g - dish_weight_g
                    self._insert_cal_point(
                        weight_g=weight_g,
                        direction=p.get("direction") or "loading",
                        cycle=p.get("cycle") or 1,
                        channel=ch_idx,
                        mean_ratio=float(p["mean_ratio"]),
                        std_ratio=float(std_ratio),
                        n_rejected=p.get("n_rejected"),
                        added_weight_g=float(added_weight_g),
                        dish_weight_g=dish_weight_g,
                        reference_mode=reference_mode,
                        source=source,
                        status=f"JSON {source}",
                    )
                    imported += 1
        messagebox.showinfo("가져오기 완료", f"포인트 {imported}개 가져옴\n스킵 {skipped}개")

    def _merge_calibration_jsons(self):
        """여러 캘리브레이션 JSON의 channels 항목을 한 JSON으로 합친다."""
        paths = filedialog.askopenfilenames(
            title="합칠 캘리브레이션 JSON 선택",
            filetypes=[("JSON", "*.json"), ("All", "*.*")],
        )
        if not paths:
            return
        merged = {
            "timestamp": datetime.now().isoformat(),
            "merged_from": [os.path.basename(p) for p in paths],
            "channels": {},
        }
        skipped = []
        for path in paths:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                channels = self._channels_from_cal_json(data)
            except Exception as e:
                skipped.append(f"{os.path.basename(path)}: {e}")
                continue
            for ch_key, cal in channels.items():
                if ch_key in merged["channels"]:
                    skipped.append(f"{os.path.basename(path)}: CH{ch_key} 중복")
                    continue
                merged["channels"][str(ch_key)] = cal

        if not merged["channels"]:
            messagebox.showerror("오류", "합칠 수 있는 채널 데이터가 없습니다.")
            return

        save_path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialfile=f"cal_merged_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        )
        if not save_path:
            return
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
        detail = "\n".join(skipped[:8])
        if len(skipped) > 8:
            detail += f"\n... 외 {len(skipped) - 8}개"
        msg = f"저장 완료: {save_path}\n채널: {', '.join('CH' + k for k in merged['channels'])}"
        if detail:
            msg += f"\n\n스킵:\n{detail}"
        messagebox.showinfo("Merge 완료", msg)

    def _save_calibration(self):
        if not self._latest_cal:
            messagebox.showwarning("경고", "먼저 캘리브레이션을 실행하세요")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialfile=f"cal_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        )
        if not path:
            return
        data = {"timestamp": datetime.now().isoformat(), "channels": {}}
        for ch_idx, cal in self._latest_cal.items():
            data["channels"][str(ch_idx)] = cal
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        messagebox.showinfo("저장 완료", path)

    # ══════════════════════════════════════════════════════════
    # 탭 2: Measurement
    # ══════════════════════════════════════════════════════════
    def _build_measurement_tab(self, parent):
        parent.columnconfigure(0, weight=0)
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(0, weight=1)

        # ── 왼쪽 컨트롤 패널 ──────────────────────────────────
        ctrl = tk.Frame(parent, width=210, bg="#eceff1")
        ctrl.grid(row=0, column=0, sticky="nsew")
        ctrl.grid_propagate(False)

        def section(text):
            tk.Label(ctrl, text=text, font=("Arial", 10, "bold"),
                     bg="#eceff1", fg="#37474f").pack(anchor="w", padx=10, pady=(12, 2))
            ttk.Separator(ctrl, orient="horizontal").pack(fill=tk.X, padx=8, pady=2)

        # 캘리브레이션 JSON 로드
        section("Calibration")
        ttk.Button(ctrl, text="Load combined JSON",
                   command=self._load_cal_json).pack(fill=tk.X, padx=10, pady=2)
        self._cal_file_lbls = []
        for i in range(N_CHANNELS):
            ttk.Button(ctrl, text=f"Load CH {i} JSON",
                       command=lambda idx=i: self._load_cal_json_for_channel(idx)).pack(
                           fill=tk.X, padx=10, pady=2)
            lbl = tk.Label(ctrl, text=f"CH{i}: default calibration",
                           bg="#eceff1", fg="#546e7a", anchor="w",
                           font=("Arial", 8), wraplength=185, justify=tk.LEFT)
            lbl.pack(fill=tk.X, padx=12, pady=(0, 2))
            self._cal_file_lbls.append(lbl)

        # Tare / Peak
        section("Tare & Peak")
        for i in range(N_CHANNELS):
            ttk.Button(ctrl, text=f"Tare CH {i}",
                       command=lambda idx=i: self._do_tare(idx)).pack(
                           fill=tk.X, padx=10, pady=2)
        ttk.Button(ctrl, text="Tare 초기화 (전체)",
                   command=self._reset_tare).pack(fill=tk.X, padx=10, pady=2)
        ttk.Button(ctrl, text="Reset All Peak",
                   command=self._reset_peak).pack(fill=tk.X, padx=10, pady=2)

        # IIR 필터
        section("IIR Filter  α")
        tk.Label(ctrl, text="작을수록 부드러움 (노이즈↓, 응답↓지연↑)",
                 bg="#eceff1", fg="gray", font=("Arial", 8),
                 wraplength=190).pack(anchor="w", padx=10)
        self._alpha_var = tk.DoubleVar(value=0.1)
        ttk.Scale(ctrl, from_=0.01, to=1.0, variable=self._alpha_var,
                  orient="horizontal",
                  command=self._on_alpha).pack(fill=tk.X, padx=10, pady=2)
        self._alpha_lbl = tk.Label(ctrl, text="α = 0.10", bg="#eceff1",
                                   font=("Consolas", 10))
        self._alpha_lbl.pack(anchor="w", padx=10)

        # 단위
        section("Display Unit")
        self._unit = tk.StringVar(value="N")
        for u in ["N", "kg", "g"]:
            ttk.Radiobutton(ctrl, text=u, variable=self._unit,
                            value=u).pack(anchor="w", padx=20)

        # 임계값 경고
        section("Over-Tension Alert (N)")
        ttk.Checkbutton(ctrl, text="Enable",
                        variable=self.threshold_enabled).pack(anchor="w", padx=20)
        row_th = tk.Frame(ctrl, bg="#eceff1")
        row_th.pack(fill=tk.X, padx=10, pady=2)
        ttk.Entry(row_th, textvariable=self.threshold_n, width=8).pack(side=tk.LEFT)
        tk.Label(row_th, text=" N", bg="#eceff1").pack(side=tk.LEFT)

        # CSV 로깅
        section("Data Logging")
        self._log_btn = ttk.Button(ctrl, text="▶ Start Logging",
                                   command=self._toggle_logging)
        self._log_btn.pack(fill=tk.X, padx=10, pady=2)

        # Plot 윈도우
        section("Plot Window")
        self._plot_win = tk.IntVar(value=30)
        row_pw = tk.Frame(ctrl, bg="#eceff1")
        row_pw.pack(fill=tk.X, padx=10)
        ttk.Spinbox(row_pw, from_=5, to=120, textvariable=self._plot_win,
                    width=6).pack(side=tk.LEFT)
        tk.Label(row_pw, text=" sec", bg="#eceff1").pack(side=tk.LEFT)

        # ── 오른쪽: 디스플레이 + 그래프 ───────────────────────
        right = ttk.Frame(parent)
        right.grid(row=0, column=1, sticky="nsew", padx=6, pady=6)
        right.rowconfigure(0, weight=0)
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        # 채널 디스플레이 (상단)
        disp_row = ttk.Frame(right)
        disp_row.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        disp_row.columnconfigure(0, weight=1)
        disp_row.columnconfigure(1, weight=1)

        self._displays = []
        for i in range(N_CHANNELS):
            frame = tk.LabelFrame(disp_row, text=f"  CH {i}  ",
                                  font=("Arial", 11, "bold"),
                                  padx=6, pady=6)
            frame.grid(row=0, column=i, sticky="ew", padx=6)

            val_lbl = tk.Label(frame, text="---",
                               font=("Consolas", 42, "bold"),
                               fg="#1565c0", width=9, anchor="e")
            val_lbl.pack()

            unit_lbl = tk.Label(frame, text="N",
                                font=("Consolas", 15), fg="#546e7a")
            unit_lbl.pack()

            info_row = tk.Frame(frame)
            info_row.pack(fill=tk.X, pady=4)
            peak_lbl = tk.Label(info_row, text="Peak: ---",
                                font=("Consolas", 10), fg="#bf360c")
            peak_lbl.pack(side=tk.LEFT, padx=6)
            raw_lbl  = tk.Label(info_row, text="Raw: ---",
                                font=("Consolas", 10), fg="#78909c")
            raw_lbl.pack(side=tk.LEFT, padx=6)

            alert_lbl = tk.Label(frame, text="",
                                 font=("Arial", 12, "bold"), fg="#c62828")
            alert_lbl.pack()

            self._displays.append({
                "frame": frame, "val": val_lbl, "unit": unit_lbl,
                "peak": peak_lbl, "raw": raw_lbl, "alert": alert_lbl,
            })

        # 실시간 그래프
        self._fig = Figure(figsize=(9, 4), dpi=100, tight_layout=True)
        self._ax  = self._fig.add_subplot(111)
        self._ax.set_xlabel("Time (s)")
        self._ax.set_ylabel("Force (N)")
        self._ax.grid(True, alpha=0.35)
        colors = ["#1565c0", "#e65100"]
        self._lines = [
            self._ax.plot([], [], color=colors[i],
                          label=f"CH {i}", linewidth=1.8)[0]
            for i in range(N_CHANNELS)
        ]
        self._thresh_line     = self._ax.axhline(
            y=0, color="#c62828", linestyle="--", linewidth=1.5, alpha=0)
        self._thresh_line_neg = self._ax.axhline(
            y=0, color="#c62828", linestyle="--", linewidth=1.5, alpha=0)
        self._ax.legend(loc="upper left")

        canvas = FigureCanvasTkAgg(self._fig, right)
        canvas.get_tk_widget().grid(row=1, column=0, sticky="nsew")
        self._plot_canvas = canvas

    # ── Measurement 컨트롤 ────────────────────────────────────
    def _on_alpha(self, _=None):
        a = round(self._alpha_var.get(), 2)
        self._alpha_lbl.config(text=f"α = {a:.2f}")
        for ch in self.channels:
            ch.set_alpha(a)

    def _do_tare(self, ch_idx: int):
        dev = self.devices[ch_idx]
        if not dev:
            messagebox.showerror("오류", f"CH{ch_idx} 연결되지 않음")
            return
        self._set_status(f"CH{ch_idx} Taring...")

        def worker():
            ch = self.channels[ch_idx]
            time.sleep(0.3)   # IIR 필터 정착 대기
            samples, t0 = [], time.time()
            while time.time() - t0 < 2.0:
                samples.append(ch.snapshot()["filtered"])
                time.sleep(0.05)
            if samples:
                mean_f = float(np.mean(samples))
                tare_g = ch.scale_g * mean_f + ch.offset_g
                ch.set_tare(tare_g)
            self.after(0, self._set_status, f"CH{ch_idx} Tare 완료")

        threading.Thread(target=worker, daemon=True).start()

    def _reset_tare(self):
        """모든 채널 Tare를 0으로 초기화 (원래 절대값으로 복귀)."""
        for ch in self.channels:
            ch.set_tare(0.0)
        self._set_status("Tare 초기화 완료 — 절대값 기준으로 복귀")

    def _reset_peak(self):
        for ch in self.channels:
            ch.reset_peak()

    def _cal_to_g(self, cal: dict) -> tuple[float, float]:
        """캘리브레이션 dict를 ChannelState가 쓰는 gram 기반 scale/offset으로 변환."""
        if "scale_g" in cal and "offset_g" in cal:
            return float(cal["scale_g"]), float(cal["offset_g"])
        if "scale_n" in cal and "offset_n" in cal:
            return (
                float(cal["scale_n"]) / GRAVITY * 1000.0,
                float(cal["offset_n"]) / GRAVITY * 1000.0,
            )
        raise KeyError("scale_g/offset_g 또는 scale_n/offset_n 없음")

    def _read_calibration_json(self, path: str) -> tuple[dict, dict]:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        channels = self._channels_from_cal_json(data)
        if not channels:
            raise ValueError("올바른 캘리브레이션 파일이 아닙니다")
        return data, channels

    def _set_cal_file_label(self, ch_idx: int, path: str, source_ch: str | int | None = None):
        if not hasattr(self, "_cal_file_lbls") or not (0 <= ch_idx < len(self._cal_file_lbls)):
            return
        name = os.path.basename(path)
        suffix = ""
        if source_ch is not None and str(source_ch) != str(ch_idx):
            suffix = f" (file CH{source_ch} -> CH{ch_idx})"
        self._cal_file_lbls[ch_idx].config(text=f"CH{ch_idx}: {name}{suffix}", foreground="#1565c0")

    def _apply_calibration_to_channel(self, ch_idx: int, cal: dict, path: str, source_ch=None) -> str:
        if not (0 <= ch_idx < N_CHANNELS):
            raise ValueError(f"CH{ch_idx}는 사용할 수 없습니다")
        scale_g, offset_g = self._cal_to_g(cal)
        self.channels[ch_idx].set_calibration(scale_g, offset_g)
        self._set_cal_file_label(ch_idx, path, source_ch)
        if source_ch is not None and str(source_ch) != str(ch_idx):
            return f"CH{ch_idx}<=file CH{source_ch}"
        return f"CH{ch_idx}"

    def _load_cal_json_for_channel(self, ch_idx: int):
        """단일 캘리브레이션 JSON을 선택한 물리 채널에만 적용."""
        path = filedialog.askopenfilename(
            title=f"CH{ch_idx} 캘리브레이션 JSON 선택",
            filetypes=[("JSON", "*.json"), ("All", "*.*")],
        )
        if not path:
            return
        try:
            _, channels = self._read_calibration_json(path)
            ch_key = str(ch_idx)
            if ch_key in channels:
                source_ch, cal = ch_key, channels[ch_key]
            elif len(channels) == 1:
                source_ch, cal = next(iter(channels.items()))
            else:
                available = ", ".join("CH" + str(k) for k in channels.keys())
                raise ValueError(f"파일에 CH{ch_idx} 보정이 없습니다. 포함 채널: {available}")
            applied = self._apply_calibration_to_channel(ch_idx, cal, path, source_ch)
            messagebox.showinfo("로드 완료", f"{path}\n적용: {applied}")
        except Exception as e:
            messagebox.showerror("오류", str(e))

    def _load_cal_json(self):
        path = filedialog.askopenfilename(
            title="통합 캘리브레이션 JSON 선택",
            filetypes=[("JSON", "*.json"), ("All", "*.*")]
        )
        if not path:
            return
        try:
            _, channels = self._read_calibration_json(path)
            applied = []
            skipped = []
            for ch_str, cal in channels.items():
                try:
                    ch_idx = int(ch_str)
                except Exception:
                    skipped.append(f"CH{ch_str}")
                    continue
                if not (0 <= ch_idx < N_CHANNELS):
                    skipped.append(f"CH{ch_str}")
                    continue
                applied.append(self._apply_calibration_to_channel(ch_idx, cal, path, ch_str))
            if not applied:
                raise ValueError("적용 가능한 채널이 없습니다")
            detail = f"{path}\n적용: {', '.join(applied)}"
            if skipped:
                detail += f"\n스킵: {', '.join(skipped)}"
            messagebox.showinfo("로드 완료",
                detail + "\n\n통합 로드는 JSON에 포함된 채널에만 적용됩니다.")
        except Exception as e:
            messagebox.showerror("오류", str(e))

    def _toggle_logging(self):
        if self._logging:
            self._stop_logging()
        else:
            self._start_logging()

    def _start_logging(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile=f"loadcell_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        )
        if not path:
            return
        self._csv_file   = open(path, "w", newline="", encoding="utf-8")
        self._csv_writer = csv.writer(self._csv_file)
        self._csv_writer.writerow([
            "timestamp", "time_s",
            "ch0_filt_ratio", "ch0_g", "ch0_N",
            "ch1_filt_ratio", "ch1_g", "ch1_N",
        ])
        self._logging  = True
        self._log_t0   = time.time()
        self._log_btn.config(text="■ Stop Logging")
        self._set_status(f"Logging → {path}")

    def _stop_logging(self):
        self._logging = False
        if self._csv_file:
            self._csv_file.close()
            self._csv_file = self._csv_writer = None
        self._log_btn.config(text="▶ Start Logging")
        self._set_status("Logging 중지됨")

    # ──────────────────────────────────────────────────────────
    # 메인 GUI 업데이트 루프 (50ms)
    # ──────────────────────────────────────────────────────────
    def _loop(self):
        now     = time.time()
        elapsed = now - self.t0
        unit    = self._unit.get()
        thresh  = self.threshold_n.get()
        th_on   = self.threshold_enabled.get()

        # ── 채널 상태 읽기 ──
        snaps = [ch.snapshot() for ch in self.channels]

        # ── 상단 연결 상태 ──
        for i, s in enumerate(snaps):
            enabled = self.ch_enabled[i].get()
            if not enabled:
                self._ch_status_lbls[i].config(text="비활성", fg="#78909c")
            elif s["connected"]:
                self._ch_status_lbls[i].config(text="연결됨", fg="#a5d6a7")
            else:
                self._ch_status_lbls[i].config(text="미연결", fg="#ef9a9a")

        # ── 디스플레이 업데이트 ──
        unit_scale = {"N": 1.0, "kg": 1.0 / GRAVITY, "g": 1000.0 / GRAVITY}[unit]
        for i, s in enumerate(snaps):
            d = self._displays[i]
            enabled = self.ch_enabled[i].get()
            if not enabled:
                d["val"].config(text="---", fg="#90a4ae")
                d["unit"].config(text=unit)
                d["peak"].config(text="Peak: ---")
                d["raw"].config(text="비활성")
                d["alert"].config(text="")
                continue

            net_n   = s["newtons"]
            display = net_n * unit_scale
            over    = th_on and abs(net_n) >= thresh
            color   = "#c62828" if over else "#1565c0"

            d["val"].config(text=f"{display:+.3f}", fg=color)
            d["unit"].config(text=unit)
            d["peak"].config(text=f"Peak: {s['peak_n']:.3f} N")
            d["raw"].config(text=f"Filt: {s['filtered']:.8f}")
            d["alert"].config(text="⚠  OVER THRESHOLD" if over else "")

        # ── 히스토리 추가 ──
        self.hist_t.append(elapsed)
        for i, s in enumerate(snaps):
            val = s["newtons"] if self.ch_enabled[i].get() else float("nan")
            self.hist_n[i].append(val)

        # ── CSV 로깅 ──
        if self._logging and self._csv_writer:
            self._csv_writer.writerow([
                datetime.now().isoformat(), f"{elapsed:.3f}",
                f"{snaps[0]['filtered']:.9f}",
                f"{snaps[0]['grams']:.3f}", f"{snaps[0]['newtons']:.4f}",
                f"{snaps[1]['filtered']:.9f}",
                f"{snaps[1]['grams']:.3f}", f"{snaps[1]['newtons']:.4f}",
            ])

        # ── Calibration 탭 안정화 / 라이브 표시 ──
        cal_ch = self.cal_ch.get()
        raw    = snaps[cal_ch]["raw"]
        self._stab_buf.append((now, raw))
        recent = [v for t, v in self._stab_buf if now - t <= 3.0]
        if recent:
            std    = float(np.std(recent))
            thresh_uv = self._stab_thresh_uv.get() * 1e-6
            ratio  = min(1.0, std / max(thresh_uv * 5, 1e-9))
            bar_w  = int((1.0 - ratio) * 220)
            color  = ("green" if std < thresh_uv
                      else "orange" if std < thresh_uv * 3 else "red")
            self._stab_bar.delete("all")
            self._stab_bar.create_rectangle(
                0, 0, bar_w, 18, fill=color, outline="")
            self._stab_lbl.config(text=f"std = {std * 1e6:.2f} µV/V")
        self._live_ratio.config(text=f"{raw:.9f}")

        # ── 그래프 업데이트 (매 PLOT_SKIP 번째) ──
        self._plot_tick += 1
        if self._plot_tick % PLOT_SKIP == 0:
            self._update_plot(unit, unit_scale, th_on, thresh)

        self.after(GUI_INTERVAL_MS, self._loop)

    def _update_plot(self, unit: str, scale: float,
                     th_on: bool, thresh: float):
        t_arr = np.array(self.hist_t)
        if len(t_arr) < 2:
            return
        win  = self._plot_win.get()
        mask = t_arr >= t_arr[-1] - win

        all_y = []
        for i in range(N_CHANNELS):
            h = np.array(self.hist_n[i])
            if len(h) == len(t_arr) and self.ch_enabled[i].get():
                y = h[mask] * scale
                valid = ~np.isnan(y)
                self._lines[i].set_data(t_arr[mask][valid], y[valid])
                all_y.extend(y[valid])
            else:
                self._lines[i].set_data([], [])

        if t_arr[mask].size:
            self._ax.set_xlim(t_arr[mask][0], t_arr[-1] + 0.5)

        if all_y:
            mn, mx = min(all_y), max(all_y)
            if th_on:
                mx = max(mx,  thresh * scale)
                mn = min(mn, -thresh * scale)
            pad = max((mx - mn) * 0.15, 0.5)
            self._ax.set_ylim(mn - pad, mx + pad)

        if th_on:
            self._thresh_line.set_ydata([thresh * scale, thresh * scale])
            self._thresh_line.set_alpha(0.8)
            self._thresh_line_neg.set_ydata([-thresh * scale, -thresh * scale])
            self._thresh_line_neg.set_alpha(0.8)
        else:
            self._thresh_line.set_alpha(0)
            self._thresh_line_neg.set_alpha(0)

        self._ax.set_ylabel(f"Force ({unit})")
        self._plot_canvas.draw_idle()

    # ──────────────────────────────────────────────────────────
    def _set_status(self, msg: str):
        self._statusbar.config(text=msg)

    def on_close(self):
        self._stop_logging()
        self._disconnect_phidgets()
        self.destroy()


# ──────────────────────────────────────────────────────────────
def main():
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()


if __name__ == "__main__":
    main()
