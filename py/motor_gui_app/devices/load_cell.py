# -*- coding: utf-8 -*-
"""Phidget 로드셀 리더와 캘리브레이션 헬퍼."""
import os
import threading

from ..core.config import DEFAULT_LOAD_CELL_CHANGE_TRIGGER, DEFAULT_LOAD_CELL_DATA_RATE_HZ
from ..core.load_cell_calibration import (
    calibration_to_grams,
    load_calibration_channels,
    select_channel_calibration,
)
from ..core.phidget_support import GRAVITY, PHIDGET_AVAILABLE, VoltageRatioInput

class _IIRFilter:
    """1차 IIR 저역통과 필터 — 로드셀 노이즈 제거용.

    y[n] = alpha * x[n] + (1 - alpha) * y[n-1]
    alpha가 작을수록 부드럽지만 반응이 느려진다. (0.1 = 새 값의 10%만 반영)
    """
    def __init__(self, alpha: float = 0.1):
        self.alpha = alpha
        self._prev = None  # 이전 필터 출력값

    def process(self, value: float) -> float:
        """새 샘플을 필터링하여 반환. 첫 번째 호출 시에는 입력값을 그대로 반환."""
        if self._prev is None:
            self._prev = value
            return value
        out = self.alpha * value + (1.0 - self.alpha) * self._prev
        self._prev = out
        return out

    def reset(self):
        """필터 상태 초기화 — 캘리브레이션 변경 시 호출하여 과도 응답을 제거."""
        self._prev = None


# ══════════════════════════════════════════════════════════════════════
# LoadCellReader 클래스 — Phidget 로드셀 GUI 내장형 리더
# ── load_cell_node.py 없이도 GUI에서 직접 Phidget USB 장치를 읽는다
# ── CommandThread가 get_force_N()으로 힘 값을 가져가서 소프트 리미트에 사용
# ══════════════════════════════════════════════════════════════════════
class LoadCellReader:
    """Phidget 로드셀 리더 — GUI 내장형.

    Phidget 콜백 스레드에서 데이터 수신 → IIR 필터 + 캘리브레이션 적용.
    CommandThread 가 get_force_N() 으로 소프트 리미트 계산에 사용.
    연결 없이도 인스턴스 생성/사용 가능 (connected == [False, ...]).
    """

    def __init__(self, n_channels: int = 1, alpha: float = 0.1):
        self.n_channels = n_channels
        self._lock      = threading.Lock()  # 콜백 스레드 ↔ GUI 스레드 경합 방지
        self._scale_g   = [1.0] * n_channels   # 캘리브레이션 스케일 (전압비 → 그램)
        self._offset_g  = [0.0] * n_channels   # 캘리브레이션 오프셋 (그램)
        self._tare_g    = [0.0] * n_channels   # 영점(Tare) 보정값 (그램)
        self._iir       = [_IIRFilter(alpha) for _ in range(n_channels)]  # 채널별 IIR 필터
        self._force_N   = [0.0] * n_channels   # 최종 힘 값 (뉴턴)
        self._last_raw  = [0.0] * n_channels   # 최근 원시 전압비 (디버그용)
        self._last_filtered = [0.0] * n_channels # 최근 필터링된 전압비
        self._has_sample = [False] * n_channels  # 채널별 첫 샘플 수신 여부
        self.connected  = [False] * n_channels # 채널별 연결 상태
        self._devices   = [None] * n_channels  # Phidget 디바이스 객체
        self.cal_file   = ""                   # 현재 적용 중인 캘리브레이션 파일 경로
        self.cal_files  = [""] * n_channels    # 채널별 캘리브레이션 파일 경로
        self.cal_note   = ""                   # 캘리브레이션 적용 요약
        self.last_errors = [""] * n_channels   # 최근 채널별 연결 실패 사유

    def _apply_channel_calibration(self, ch: int, scale_g: float, offset_g: float, path: str):
        """한 채널에만 캘리브레이션을 적용하고 해당 채널 상태를 초기화."""
        self._scale_g[ch] = scale_g
        self._offset_g[ch] = offset_g
        self._iir[ch].reset()
        self._tare_g[ch] = 0.0
        self._force_N[ch] = 0.0
        self._has_sample[ch] = False
        self.cal_files[ch] = path

    def _refresh_cal_note(self):
        parts = []
        for i, path in enumerate(self.cal_files):
            if path:
                parts.append(f"CH{i}:{os.path.basename(path)}")
        self.cal_note = ", ".join(parts) if parts else "적용 채널 없음"

    def load_calibration_channel(self, path: str, target_ch: int) -> str:
        """JSON 파일 하나를 지정한 GUI 채널에만 적용."""
        if target_ch < 0 or target_ch >= self.n_channels:
            return f"CH{target_ch} 없음"
        try:
            channels = load_calibration_channels(path)
            selected = select_channel_calibration(target_ch, channels)
            if selected is None:
                return f"파일에 CH{target_ch} 캘리브레이션이 없습니다."
            _src_key, calibration, _copied = selected
            scale_g, offset_g = calibration_to_grams(calibration)
            with self._lock:
                self._apply_channel_calibration(target_ch, scale_g, offset_g, path)
            self._refresh_cal_note()
            self.cal_file = path
            return ""
        except Exception as e:
            return str(e)

    def load_calibration(self, path: str) -> str:
        """JSON 캘리브레이션 파일 로드. 성공 시 "" 반환, 실패 시 에러 메시지 반환.

        JSON 형식 예시:
        {"channels": {"0": {"scale_g": 12345.6, "offset_g": -0.5}}}
        load_cell_gui.py 에서 2점 캘리브레이션으로 생성한 파일을 사용한다.
        """
        try:
            channels = load_calibration_channels(path)

            applied = []
            with self._lock:
                for i in range(self.n_channels):
                    selected = select_channel_calibration(i, channels)
                    if selected is not None:
                        src_key, calibration, copied = selected
                        scale_g, offset_g = calibration_to_grams(calibration)
                        self._apply_channel_calibration(i, scale_g, offset_g, path)
                        applied.append(f"CH{i}=CH{src_key}" if copied else f"CH{i}")
            self.cal_file = path
            self._refresh_cal_note()
            if applied:
                self.cal_note = f"{', '.join(applied)} / {self.cal_note}"
            return ""
        except Exception as e:
            return str(e)

    # ── Phidget 콜백 (Phidget 라이브러리의 내부 스레드에서 호출됨) ────
    def _on_voltage_change(self, ch_idx: int, ratio: float):
        """전압비 변화 콜백 — Phidget 내부 스레드에서 호출.

        변환 경로: 전압비(V/V) → IIR 필터 → 캘리브레이션(그램) → Tare 보정 → 뉴턴
        """
        with self._lock:
            filtered = self._iir[ch_idx].process(ratio)
            # 캘리브레이션 적용: 전압비 → 절대 그램
            abs_g    = self._scale_g[ch_idx] * filtered + self._offset_g[ch_idx]
            # Tare(영점) 보정: 절대 그램 → 순수 그램
            net_g    = abs_g - self._tare_g[ch_idx]
            # 그램 → 뉴턴 변환 (g / 1000 = kg, kg × 9.80665 = N)
            self._force_N[ch_idx]  = (net_g / 1000.0) * GRAVITY
            self._last_raw[ch_idx] = ratio
            self._last_filtered[ch_idx] = filtered
            self._has_sample[ch_idx] = True

    def connect(self) -> list:
        """Phidget 장치 연결 시도 (최대 3초 블로킹). 성공한 채널 인덱스 목록 반환.

        각 채널마다 VoltageRatioInput 디바이스를 열고, 최소 데이터 간격으로 설정.
        콜백 핸들러를 등록하면 Phidget이 자체 스레드에서 데이터를 전달해 준다.
        """
        if not PHIDGET_AVAILABLE:
            return []
        ok = []
        self.last_errors = [""] * self.n_channels
        for i in range(self.n_channels):
            try:
                dev = VoltageRatioInput()
                dev.setChannel(i)
                dev.openWaitForAttachment(3000)  # 3초 타임아웃으로 USB 연결 대기
                # 1046_1은 2채널 사용 시 채널당 최대 약 250 samples/s.
                # DataRate를 명시하고 change trigger를 최소화해 고속 실험에서 계단형 갱신을 줄인다.
                try:
                    min_rate = float(dev.getMinDataRate())
                    max_rate = float(dev.getMaxDataRate())
                    rate = max(min_rate, min(max_rate, DEFAULT_LOAD_CELL_DATA_RATE_HZ))
                    dev.setDataRate(rate)
                except Exception:
                    dev.setDataInterval(dev.getMinDataInterval())  # fallback: 최소 주기(최대 속도)
                try:
                    min_trigger = float(dev.getMinVoltageRatioChangeTrigger())
                    max_trigger = float(dev.getMaxVoltageRatioChangeTrigger())
                    trigger = max(min_trigger, min(max_trigger, DEFAULT_LOAD_CELL_CHANGE_TRIGGER))
                    dev.setVoltageRatioChangeTrigger(trigger)
                except Exception:
                    pass
                # 람다의 ci=i: 루프 변수 캡처 문제를 방지하기 위해 기본값으로 바인딩
                dev.setOnVoltageRatioChangeHandler(
                    lambda _dev, ratio, ci=i: self._on_voltage_change(ci, ratio)
                )
                self._devices[i] = dev
                self.connected[i] = True
                ok.append(i)
            except Exception as e:
                self.connected[i] = False
                self.last_errors[i] = str(e)
        return ok

    def disconnect(self):
        """모든 Phidget 채널 연결 해제. GUI 종료 시 호출."""
        for i, dev in enumerate(self._devices):
            if dev:
                try:
                    dev.close()
                except Exception:
                    pass
                self._devices[i] = None
                self.connected[i] = False

    def tare(self, ch: int = 0) -> tuple[bool, str]:
        """현재 filtered 측정값을 즉시 영점으로 설정.

        현재 필터링된 전압비를 캘리브레이션 절대값으로 환산해 tare_g에 저장한다.
        로드셀에 기구물이 올라간 상태에서 눌러 순수 하중만 측정할 때 사용.
        """
        if ch >= self.n_channels:
            return False, f"CH{ch} 없음"
        with self._lock:
            if not self.connected[ch]:
                return False, f"CH{ch} 미연결"
            if not self._has_sample[ch]:
                return False, f"CH{ch} 샘플 대기 중"
            # 원래 Load_cell/load_cell_gui.py와 같은 방식:
            # tare_g = scale_g * filtered_ratio + offset_g
            self._tare_g[ch] = self._scale_g[ch] * self._last_filtered[ch] + self._offset_g[ch]
            # 화면에 즉시 0으로 표시되도록 force_N도 리셋
            self._force_N[ch] = 0.0
            return True, f"CH{ch} Tare 완료"

    def tare_all(self) -> list[tuple[bool, str]]:
        """연결된 모든 채널을 현재 힘 기준으로 영점 보정."""
        results = []
        for ch in range(self.n_channels):
            if ch < len(self.connected) and self.connected[ch]:
                results.append(self.tare(ch))
        return results

    def reset_tare(self):
        """모든 채널의 tare를 초기화해 캘리브레이션 절대값 기준으로 되돌린다."""
        with self._lock:
            self._tare_g = [0.0] * self.n_channels

    def get_force_N(self, ch: int = 0) -> float:
        """특정 채널의 현재 힘 값(N)을 스레드-안전하게 반환."""
        with self._lock:
            return self._force_N[ch] if ch < self.n_channels else 0.0

    def get_all_forces_N(self) -> list:
        """모든 채널의 힘 값(N) 리스트를 스레드-안전하게 반환."""
        with self._lock:
            return list(self._force_N)

    def get_soft_limit_force_N(self) -> float:
        """연결된 채널 중 절댓값이 가장 큰 힘을 반환."""
        with self._lock:
            values = [
                abs(self._force_N[i])
                for i in range(self.n_channels)
                if i < len(self.connected) and self.connected[i]
            ]
        return max(values) if values else 0.0
