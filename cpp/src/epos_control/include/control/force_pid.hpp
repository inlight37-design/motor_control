// force_pid.hpp — RT-safe PID controller for force feedback control
// ================================================================
//
// [역할]
//   로드셀(힘 센서) 피드백을 기반으로 모터 속도(RPM)를 출력하는 PID 제어기.
//   1000Hz RT 루프 안에서 매 사이클 호출되므로, 동적 메모리 할당이나
//   시스템 콜 없이 순수 산술 연산만 수행한다.
//
// [설계 원칙]
//   1. D-on-Measurement: 미분항을 오차(error)가 아닌 측정값(measurement)에 적용.
//      → setpoint(목표힘)를 갑자기 바꿔도 D항이 순간적으로 튀지 않음 (derivative kick 방지)
//   2. Anti-Windup: 적분항에 상한/하한 클램프를 걸어,
//      모터가 포화 상태일 때 적분값이 무한히 쌓이는 것을 방지.
//   3. D항 저역통과필터(LPF): 로드셀 노이즈가 미분 시 증폭되는 것을 억제.
//      alpha가 작을수록 부드럽지만 반응이 느려짐.
//
// [호출 구조]
//   epos_motor_node.cpp 의 control_loop_rt() 에서만 호출.
//   → force_pid_.compute(target_mN, actual_mN, dt_s)
//   → 반환값(rpm)을 모터 속도 명령으로 사용.
//
// [단위]
//   - 입력: target, measurement → mN (밀리뉴턴), dt_s → 초
//   - 출력: rpm (모터 속도 명령)
//   - 내부 적분/출력 제한: rpm 단위
//
#pragma once
#include <algorithm>
#include <cmath>

struct ForcePID {
  // ── PID 게인 ─────────────────────────────────────────────────────
  // GUI에서 atomic 변수를 통해 실시간 변경 가능.
  // kp: 오차에 비례하는 즉각적 반응 (클수록 빠르지만 진동 위험)
  // ki: 정상상태 오차(steady-state error)를 제거 (클수록 빠르지만 오버슈트 증가)
  // kd: 오차 변화율을 감쇠 (클수록 진동 억제, 너무 크면 노이즈 증폭)
  double kp = 0.0;
  double ki = 0.0;
  double kd = 0.0;

  // ── 내부 상태 (RT 스레드에서만 접근) ──────────────────────────────
  double integral = 0.0;           // I항 누적값 [rpm·s → rpm으로 환산됨]
  double prev_measurement = 0.0;   // D항 계산용: 이전 측정값 [mN]
  double d_filtered = 0.0;         // D항 LPF 출력 [mN/s]

  // ── 튜닝 파라미터 ────────────────────────────────────────────────
  double integral_limit = 3000.0;  // anti-windup 클램프 [rpm 단위]
                                   // 적분값이 이 범위를 넘지 못하게 제한
  double output_limit = 3000.0;    // 최종 출력 클램프 [rpm]
                                   // GUI의 force_max_rpm 값으로 덮어씌워짐
  double d_filter_alpha = 0.1;     // D항 LPF 계수 (0.05~0.2)
                                   // 작을수록 부드러움, 클수록 빠른 반응
  bool first = true;               // 첫 사이클 플래그 (D항 초기화용)

  // ── 상태 초기화 ──────────────────────────────────────────────────
  // 힘 제어 시작/재시작 시 호출. 이전 제어의 잔여 상태가 남아있으면
  // 제어 시작 순간에 예측 불가능한 출력이 나올 수 있으므로 반드시 리셋.
  void reset() {
    integral = 0.0;
    prev_measurement = 0.0;
    d_filtered = 0.0;
    first = true;
  }

  // ── PID 연산 ─────────────────────────────────────────────────────
  // @param target      목표 힘 [mN]
  // @param measurement 실제 측정 힘 [mN]
  // @param dt_s        이번 제어 주기 [초] (보통 0.001s = 1ms)
  // @return            모터 속도 명령 [rpm] (양수=정방향, 음수=역방향)
  double compute(double target, double measurement, double dt_s) {
    // dt 유효성 검사: 0 이하면 0 나누기 위험, 1초 이상이면 비정상 상황
    if (dt_s <= 0.0 || dt_s > 1.0) return 0.0;

    double error = target - measurement;

    // ── P항 (비례) ─────────────────────────────────────────────────
    // 현재 오차에 즉시 반응. 제어의 주된 구동력.
    double p_out = kp * error;

    // ── I항 (적분) + Anti-Windup ───────────────────────────────────
    // 오차를 시간에 대해 누적 → 정상상태 오차 제거.
    // 예: 목표 50N인데 48N에서 안 올라가면, 적분이 쌓여서 추가 출력 발생.
    // Anti-windup: 모터가 max_rpm에 도달해도 적분이 계속 쌓이면,
    //   모터가 풀릴 때 과도한 역방향 출력이 나옴 → 클램프로 방지.
    integral += error * dt_s;
    integral = std::max(-integral_limit, std::min(integral_limit, integral));
    double i_out = ki * integral;

    // ── D항 (미분, 측정값 기반) ────────────────────────────────────
    // 핵심: error가 아닌 measurement의 변화율을 사용.
    // error = target - measurement 이고,
    // d(error)/dt = d(target)/dt - d(measurement)/dt 인데,
    // target이 갑자기 바뀌면 d(target)/dt가 무한대 → 출력 스파이크 발생.
    // measurement만 미분하면 이 문제가 없음. (부호 반전 필요: 측정값 증가 = 오차 감소)
    double d_raw = 0.0;
    if (!first) {
      d_raw = -(measurement - prev_measurement) / dt_s;
    }
    first = false;
    prev_measurement = measurement;

    // D항 LPF: 로드셀 노이즈가 미분 시 크게 증폭되므로,
    // 1차 IIR 저역통과필터로 고주파 성분 제거.
    // d_filtered = alpha * 새값 + (1-alpha) * 이전값
    // alpha=0.1이면 새 값의 10%만 반영 → 매우 부드러움
    d_filtered = d_filter_alpha * d_raw + (1.0 - d_filter_alpha) * d_filtered;
    double d_out = kd * d_filtered;

    // ── 최종 출력 = P + I + D, 클램프 적용 ─────────────────────────
    double output = p_out + i_out + d_out;
    return std::max(-output_limit, std::min(output_limit, output));
  }
};

// ── 비선형 Tanh 힘 제어기 ─────────────────────────────────────────────
//
// [원리]
//   rpm = max_rpm × tanh(error / sensitivity)
//
//   오차가 클 때(1N 이상) → max_rpm에 가까운 빠른 속도
//   오차가 중간(0.1~1N)  → 점점 낮은 속도로 접근
//   오차가 작을 때(0.01N 근처) → 아주 천천히 섬세하게 수렴
//
//   PID처럼 게인을 여러 개 튜닝할 필요 없이 sensitivity 하나로 조정.
//   데드밴드 내부(|오차| < deadband_mN)에서는 목표 도달로 보고 출력 0 → 정지.
//
// [단위]
//   - sensitivity_mN: 이 값(mN)의 오차일 때 max_rpm의 약 76% 출력
//     예) sensitivity=1000 → 1.0N 오차에서 max_rpm × 0.76
//   - deadband_mN: 이 범위 안에서는 모터 정지 (예: 10 = 0.01N)
struct ForceTanh {
  double max_rpm     = 3000.0;   // 최대 출력 속도 [rpm]
  double sensitivity_mN = 1000.0; // 반응 민감도 [mN] (작을수록 민감)
  double deadband_mN    = 10.0;  // 정지 데드밴드 [mN] (0=사용 안 함)

  double compute(double target, double measurement) const {
    double error = target - measurement;
    double abs_err = std::abs(error);
    double deadband = std::max(0.0, deadband_mN);
    double sensitivity = std::max(1.0, std::abs(sensitivity_mN));

    if (abs_err <= deadband) return 0.0;

    // 데드밴드 경계에서 불연속 없이 부드럽게 시작하도록 데드밴드 제거 후 계산
    double sign = (error > 0.0) ? 1.0 : -1.0;
    double adj  = abs_err - deadband;
    return max_rpm * std::tanh(adj / sensitivity) * sign;
  }
};
