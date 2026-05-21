// epos_motor_node.cpp — Maxon EPOS4 EtherCAT 실시간 제어 노드
// ================================================================
//
// [전체 구조]
//   이 파일은 ROS2 노드 하나(EposNode)로 구성됨.
//   내부에 3개의 스레드가 동작:
//
//   ┌─────────────────────────────────────────────────────────────┐
//   │ 스레드 1: ROS2 스핀 (main)                                    │
//   │   - rclcpp::spin()이 구독 콜백들을 처리                         │
//   │   - GUI에서 온 명령(속도, 위치, 토크, 파형 등)을 atomic에 저장      │
//   │   - publish_feedback(): 50Hz로 GUI에 피드백 발행               │
//   │   - publish_diag_summary(): 10Hz로 진단 요약 발행              │
//   └─────────────────────────────────────────────────────────────┘
//   ┌─────────────────────────────────────────────────────────────┐
//   │ 스레드 2: RT 제어 루프 (control_loop_rt)                       │
//   │   - 1000Hz (1ms 주기) 실시간 제어                              │
//   │   - SCHED_FIFO + CPU 핀닝 + mlockall로 RT 성능 확보            │
//   │   - EtherCAT PDO 교환 → 모터 상태 읽기 → 제어 계산 → 명령 쓰기     │
//   │   - lock-free: mutex 없이 atomic과 더블버퍼만 사용              │
//   └─────────────────────────────────────────────────────────────┘
//   ┌─────────────────────────────────────────────────────────────┐
//   │ 스레드 3: AsyncLogger (process_loop)                         │
//   │   - 10ms 간격으로 링버퍼에서 데이터를 꺼내 CSV 파일에 기록            │
//   └─────────────────────────────────────────────────────────────┘
//
// [데이터 흐름]
//   GUI(Python) --[ROS2 토픽]--> 콜백 --[atomic]--> RT루프 --[PDO]--> 모터
//   모터 --[PDO]--> RT루프 --[atomic]--> publish_feedback --[토픽]--> GUI
//   RT루프 --[링버퍼]--> AsyncLogger --[fwrite]--> CSV 파일
//
// [제어 모드]
//   - CSV (mode 9): 속도 제어. 대부분의 실험에서 사용.
//   - CSP (mode 8): 위치 제어. 내부적으로 P제어 → CSV로 변환하여 구현.
//     (EPOS4의 CSP 모드를 직접 쓰지 않는 이유: 마스터/슬레이브 클럭 차이로
//      위치가 꿀렁거리는 현상 발생 → 마스터에서 P제어 후 CSV로 보내면 해결)
//   - CST (mode 10): 토크 제어. 직접 토크 명령 전달.
//   - 힘 제어: 로드셀 피드백 → PID → RPM 출력 (CSV 모드 위에서 동작)
//
// [안전 장치]
//   1. Fault 감지: RT 루프에서 감지, non-RT 피드백 콜백에서 SDO 에러코드 읽기
//   2. 최종 출력 안전장치: Fault/disable/명령 타임아웃/Heartbeat 타임아웃 시 속도·토크 0
//   3. 로드셀 힘 한계: RT 루프 1kHz에서 판단, 로그 출력은 non-RT에서 처리
//   4. WKC 연속 오류 복구 (wkc_recover_threshold)
//
#include <atomic>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <numeric>
#include <string>
#include <thread>
#include <vector>

// POSIX RT 관련 헤더들 — Linux 전용
#include <time.h>        // clock_gettime, clock_nanosleep
#include <errno.h>       // EINTR
#include <unistd.h>

// ROS2 헤더
#include "rclcpp/rclcpp.hpp"
#include "std_msgs/msg/float32.hpp"
#include "std_msgs/msg/int32.hpp"
#include "std_msgs/msg/string.hpp"
#include "std_srvs/srv/set_bool.hpp"
#include "std_srvs/srv/trigger.hpp"
#include "epos_interfaces/msg/force_ctrl_cmd.hpp"
#include "epos_interfaces/msg/waveform_cmd.hpp"

// SOEM (Simple Open EtherCAT Master) — C 라이브러리이므로 extern "C"로 감쌈
extern "C" {
#include "ethercat.h"
}

// 프로젝트 헤더
#include "waveform/waveform_generator.hpp"  // 파형 생성 + 파싱
#include "ethercat/axis_config.hpp"         // PDO 구조체, AxisState, 에러맵
#include "logging/async_logger.hpp"         // 비동기 CSV 로거
#include "ethercat/cia402_state.hpp"        // CiA402 상태 워드 판단
#include "commands/command_parsing.hpp"     // GUI/스크립트 명령 문자열 파싱
#include "ethercat/epos_setup.hpp"          // EPOS4 PDO/SDO 초기 설정
#include "logging/file_utils.hpp"           // 로그 파일 디렉토리 생성
#include "control/force_control.hpp"        // 힘 피드백 선택 + PID/Tanh 제어 계산
#include "safety/force_limit_guard.hpp"     // 로드셀 힘 한계 판단
#include "control/force_pid.hpp"            // 힘 제어 PID
#include "waveform/hysteresis_plan.hpp"     // 히스테리시스 파형/로깅 시간창 계산
#include "logging/log_command.hpp"          // CSV 로깅 명령 파싱
#include "util/motor_units.hpp"             // N↔mN, mm↔um 단위 변환
#include "util/net_utils.hpp"               // EtherCAT 인터페이스 자동 감지
#include "safety/output_safety_guard.hpp"   // 최종 PDO 출력 안전장치
#include "control/position_control.hpp"     // 위치 목표 → CSV 속도 명령 변환
#include "util/realtime_config.hpp"         // RT 스케줄러/CPU/메모리 설정
#include "util/simple_ring_buffer.hpp"      // 진단 데이터 수집용 SPSC 버퍼
#include "control/velocity_control.hpp"     // CSV 속도 제어 명령 계산

using namespace std::chrono_literals;  // 100ms, 2ms 등 리터럴 사용

using epos_control::MN_TO_N;
using epos_control::N_TO_MN;
using epos_control::SimpleRingBuffer;
using epos_control::check_force_limit;
using epos_control::compute_force_control_command;
using epos_control::configure_realtime_thread;
using epos_control::compute_velocity_csv_command;
using epos_control::detect_default_iface;
using epos_control::ensure_parent_dir;
using epos_control::ForceControlParams;
using epos_control::make_hyst_position_plan;
using epos_control::make_hyst_velocity_plan;
using epos_control::mN_to_N_float;
using epos_control::mm_to_um;
using epos_control::n_to_mN;
using epos_control::apply_output_safety;
using epos_control::OutputSafetyInput;
using epos_control::parse_log_command;
using epos_control::select_force_feedback;
using epos_control::compute_position_csv_command;


// ══════════════════════════════════════════════════════════════════
//  EposNode — ROS2 노드 클래스
// ══════════════════════════════════════════════════════════════════
class EposNode : public rclcpp::Node
{
public:
  EposNode() : Node("epos_motor_node")
  {
    // ── ROS2 파라미터 선언 ──────────────────────────────────────────
    // --ros-args -p iface:=enx... 형태로 실행 시 변경 가능.
    // 런타임 변경은 지원하지 않음 (생성자에서 1회 읽기).
    iface_           = this->declare_parameter<std::string>("iface", detect_default_iface());
    cycle_hz_        = this->declare_parameter<int>("cycle_hz", 1000);       // RT 루프 주파수
    publish_hz_      = this->declare_parameter<int>("publish_hz", 50);       // GUI 피드백 주기
    max_abs_target_  = this->declare_parameter<int>("max_abs_target", 3000); // RPM 안전 한계
    cmd_timeout_ms_  = this->declare_parameter<int>("cmd_timeout_ms", 0);    // 0=비활성
    auto_enable_     = this->declare_parameter<bool>("auto_enable", true);   // 자동 모터 활성화
    overrun_thresh_us_ = this->declare_parameter<int>("overrun_thresh_us", 200); // 주기 초과 임계값
    rt_enable_       = this->declare_parameter<bool>("rt_enable", true);
    rt_priority_     = this->declare_parameter<int>("rt_priority", 50);      // SCHED_FIFO 우선순위 (1~99)
    rt_cpu_          = this->declare_parameter<int>("rt_cpu", -1);           // -1=고정안함, 0~7=특정코어
    wkc_recover_threshold_ = this->declare_parameter<int>("wkc_recover_threshold", 50);
    heartbeat_timeout_ms_ = this->declare_parameter<int>("heartbeat_timeout_ms", 0); // 0=비활성
    diag_hz_         = this->declare_parameter<int>("diag_hz", 10);          // 진단 발행 주기
    pos_p_gain_      = this->declare_parameter<double>("pos_p_gain", 5.0);   // 위치 P제어 게인
    motor_ticks_per_rev_ = std::max(1, static_cast<int>(this->declare_parameter<int>("motor_ticks_per_rev", 2000)));
    int accel_limit_param = this->declare_parameter<int>("accel_limit_rpm_s", 5000);
    accel_limit_rpm_s_.store(std::max(0, accel_limit_param), std::memory_order_relaxed);
    double force_limit_N_param = this->declare_parameter<double>("force_limit_N", 0.0);
    force_limit_mN_.store(n_to_mN(std::max(0.0, force_limit_N_param)), std::memory_order_relaxed);

    // 힘 제어 PID 게인 — atomic이므로 GUI에서 실시간 변경 가능
    force_kp_.store(this->declare_parameter<double>("force_kp", 0.5), std::memory_order_relaxed);
    force_ki_.store(this->declare_parameter<double>("force_ki", 0.05), std::memory_order_relaxed);
    force_kd_.store(this->declare_parameter<double>("force_kd", 0.01), std::memory_order_relaxed);
    int force_max_rpm_param = this->declare_parameter<int>("force_max_rpm", 50);
    force_max_rpm_.store(std::max(1, std::min(max_abs_target_, force_max_rpm_param)), std::memory_order_relaxed);
    double force_alpha_param = this->declare_parameter<double>("force_out_alpha", 0.3);
    force_out_alpha_.store(std::max(0.01, std::min(1.0, force_alpha_param)), std::memory_order_relaxed);
    double tanh_sens_N_param = this->declare_parameter<double>("force_tanh_sensitivity_N", 1.0);
    double tanh_dead_N_param = this->declare_parameter<double>("force_tanh_deadband_N", 0.01);
    force_tanh_sensitivity_.store(std::max(0.001, tanh_sens_N_param) * N_TO_MN, std::memory_order_relaxed);
    force_tanh_deadband_.store(std::max(0.0, tanh_dead_N_param) * N_TO_MN, std::memory_order_relaxed);

    if (iface_.empty()) {
      RCLCPP_ERROR(get_logger(), "EtherCAT 인터페이스를 찾지 못했습니다. EPOS_IFACE 또는 iface 파라미터를 지정하세요.");
      return;
    }

    // 슬레이브 설정
    int slave_idx = this->declare_parameter<int>("slave_index", 1);
    int op_mode   = this->declare_parameter<int>("op_mode", 9);  // 기본: CSV (속도 제어)
    int8_t initial_mode = (op_mode == 8 || op_mode == 9 || op_mode == 10)
                        ? static_cast<int8_t>(op_mode)
                        : static_cast<int8_t>(9);
    axis_.slave_index = slave_idx;
    axis_.op_mode.store(initial_mode, std::memory_order_relaxed);
    requested_op_mode_.store(initial_mode, std::memory_order_relaxed);
    axis_.name = "axis0";

    // ── ROS2 구독자 (GUI → C++) ────────────────────────────────────
    // 모든 명령은 콜백에서 atomic 변수에 저장만 하고, RT 루프에서 읽어감.
    // 이렇게 해야 콜백 처리 시간이 0에 가까워 ROS2 스핀이 밀리지 않음.

    // 속도 명령 [RPM]
    sub_target_ = this->create_subscription<std_msgs::msg::Int32>(
      "/target_speed", rclcpp::QoS(10).reliable(),
      [this](const std_msgs::msg::Int32::SharedPtr msg) {
        target_.store(msg->data, std::memory_order_relaxed);
        last_cmd_ns_.store(now_monotonic_ns(), std::memory_order_relaxed);
      });

    // 위치 명령 [encoder tick]
    sub_target_pos_ = this->create_subscription<std_msgs::msg::Int32>(
      "/target_position", rclcpp::QoS(10).reliable(),
      [this](const std_msgs::msg::Int32::SharedPtr msg) {
        target_pos_.store(msg->data, std::memory_order_relaxed);
        last_cmd_ns_.store(now_monotonic_ns(), std::memory_order_relaxed);
      });

    // 토크 명령 [‰ rated torque]
    sub_target_trq_ = this->create_subscription<std_msgs::msg::Int32>(
      "/target_torque", rclcpp::QoS(10).reliable(),
      [this](const std_msgs::msg::Int32::SharedPtr msg) {
        target_trq_.store(static_cast<int16_t>(msg->data), std::memory_order_relaxed);
        last_cmd_ns_.store(now_monotonic_ns(), std::memory_order_relaxed);
      });

    // 동작 모드 변경 (8: 위치, 9: 속도, 10: 토크)
    sub_op_mode_ = this->create_subscription<std_msgs::msg::Int32>(
      "/op_mode_cmd", rclcpp::QoS(10).reliable(),
      [this](const std_msgs::msg::Int32::SharedPtr msg) {
        int8_t mode = static_cast<int8_t>(msg->data);
        if (mode == 8 || mode == 9 || mode == 10) {
          requested_op_mode_.store(mode, std::memory_order_relaxed);
        }
      });

    // 가속도 한계 [RPM/s] — C++ RT 루프의 slew rate limiter에서 사용
    sub_accel_ = this->create_subscription<std_msgs::msg::Int32>(
      "/accel_limit_rpm_s", rclcpp::QoS(10).reliable(),
      [this](const std_msgs::msg::Int32::SharedPtr msg) {
        accel_limit_rpm_s_.store(msg->data, std::memory_order_relaxed);
      });

    // 위치 제어 시 이동 속도 한계 [Tick/s]
    sub_pos_speed_limit_ = this->create_subscription<std_msgs::msg::Int32>(
      "/pos_speed_limit", rclcpp::QoS(10).reliable(),
      [this](const std_msgs::msg::Int32::SharedPtr msg) {
        pos_speed_limit_.store(msg->data, std::memory_order_relaxed);
      });

    // 파형 생성기 명령 v1 (문자열): 기존 GUI/스크립트 호환용.
    sub_waveform_ = this->create_subscription<std_msgs::msg::String>(
      "/epos/waveform_cmd", rclcpp::QoS(10).reliable(),
      [this](const std_msgs::msg::String::SharedPtr msg) { handle_waveform_cmd(msg->data); });

    // 파형 생성기 명령 v2 (구조화 메시지): 새 GUI가 우선 사용.
    sub_waveform_v2_ = this->create_subscription<epos_interfaces::msg::WaveformCmd>(
      "/epos/waveform_cmd_v2", rclcpp::QoS(10).reliable(),
      [this](const epos_interfaces::msg::WaveformCmd::SharedPtr msg) { handle_waveform_msg(msg); });

    // CSV 로깅 명령 ("start /path" 또는 "stop")
    sub_log_cmd_ = this->create_subscription<std_msgs::msg::String>(
      "/epos/log_cmd", rclcpp::QoS(10).reliable(),
      [this](const std_msgs::msg::String::SharedPtr msg) { handle_log_cmd(msg->data); });

    // GUI heartbeat — GUI가 살아있는지 확인용 (best_effort: 손실 허용)
    sub_heartbeat_ = this->create_subscription<std_msgs::msg::Int32>(
      "/epos/heartbeat", rclcpp::QoS(10).best_effort(),
      [this](const std_msgs::msg::Int32::SharedPtr) {
        last_heartbeat_ns_.store(now_monotonic_ns(), std::memory_order_relaxed);
      });

    // 로드셀 힘 [N] — load_cell_node 또는 GUI에서 발행
    // best_effort + depth=1: 최신 값 하나만 유지 (센서 데이터는 최신만 의미 있음)
    sub_force_ch0_ = this->create_subscription<std_msgs::msg::Float32>(
      "/load_cell/ch0_N", rclcpp::QoS(1).best_effort(),
      [this](const std_msgs::msg::Float32::SharedPtr msg) {
        // N → mN 변환 후 정수로 저장 (atomic<float>를 피하기 위해)
        // atomic<double/float>는 일부 플랫폼에서 lock-free가 아닐 수 있음
        last_force_ch0_mN_.store(n_to_mN(msg->data), std::memory_order_relaxed);
        last_force_ch0_ns_.store(now_monotonic_ns(), std::memory_order_relaxed);
      });

    sub_force_ch1_ = this->create_subscription<std_msgs::msg::Float32>(
      "/load_cell/ch1_N", rclcpp::QoS(1).best_effort(),
      [this](const std_msgs::msg::Float32::SharedPtr msg) {
        last_force_ch1_mN_.store(n_to_mN(msg->data), std::memory_order_relaxed);
        last_force_ch1_ns_.store(now_monotonic_ns(), std::memory_order_relaxed);
      });

    // 리니어 엔코더 위치 — GUI가 PhidgetEncoder에서 읽어 발행
    sub_linear_count_ = this->create_subscription<std_msgs::msg::Int32>(
      "/linear_encoder/position_count", rclcpp::QoS(1).best_effort(),
      [this](const std_msgs::msg::Int32::SharedPtr msg) {
        last_linear_count_.store(msg->data, std::memory_order_relaxed);
        last_linear_ns_.store(now_monotonic_ns(), std::memory_order_relaxed);
      });

    sub_linear_mm_ = this->create_subscription<std_msgs::msg::Float32>(
      "/linear_encoder/position_mm", rclcpp::QoS(1).best_effort(),
      [this](const std_msgs::msg::Float32::SharedPtr msg) {
        last_linear_um_.store(mm_to_um(msg->data), std::memory_order_relaxed);
        last_linear_ns_.store(now_monotonic_ns(), std::memory_order_relaxed);
      });

    // 힘 제어 명령 v1 (문자열): 기존 GUI/스크립트 호환용.
    sub_force_ctrl_ = this->create_subscription<std_msgs::msg::String>(
      "/epos/force_ctrl_cmd", rclcpp::QoS(10).reliable(),
      [this](const std_msgs::msg::String::SharedPtr msg) { handle_force_ctrl_cmd(msg->data); });

    // 힘 제어 명령 v2 (구조화 메시지): 새 GUI가 우선 사용.
    sub_force_ctrl_v2_ = this->create_subscription<epos_interfaces::msg::ForceCtrlCmd>(
      "/epos/force_ctrl_cmd_v2", rclcpp::QoS(10).reliable(),
      [this](const epos_interfaces::msg::ForceCtrlCmd::SharedPtr msg) { handle_force_ctrl_msg(msg); });

    // 힘 제어 목표값 [N]
    sub_target_force_ = this->create_subscription<std_msgs::msg::Float32>(
      "/target_force_N", rclcpp::QoS(10).reliable(),
      [this](const std_msgs::msg::Float32::SharedPtr msg) {
        target_force_mN_.store(n_to_mN(msg->data), std::memory_order_relaxed);
      });

    // ── ROS2 발행자 (C++ → GUI) ────────────────────────────────────
    pub_speed_        = this->create_publisher<std_msgs::msg::Int32>("/measured_speed", 10);
    pub_stat_         = this->create_publisher<std_msgs::msg::Int32>("/epos/status_word", 10);
    pub_pos_          = this->create_publisher<std_msgs::msg::Int32>("/epos/actual_position", 10);
    pub_trq_          = this->create_publisher<std_msgs::msg::Int32>("/epos/actual_torque", 10);
    pub_wkc_          = this->create_publisher<std_msgs::msg::Int32>("/epos/wkc", 10);
    pub_cycle_dt_     = this->create_publisher<std_msgs::msg::Int32>("/epos/cycle_dt_us", 10);
    pub_cycle_jitter_ = this->create_publisher<std_msgs::msg::Int32>("/epos/cycle_jitter_us", 10);
    pub_overrun_cnt_  = this->create_publisher<std_msgs::msg::Int32>("/epos/cycle_overrun_count", 10);
    pub_wkc_err_cnt_  = this->create_publisher<std_msgs::msg::Int32>("/epos/wkc_error_count", 10);
    pub_error_code_   = this->create_publisher<std_msgs::msg::Int32>("/epos/error_code", 10);
    pub_diag_summary_ = this->create_publisher<std_msgs::msg::String>("/epos/diag_summary", 10);

    // ── ROS2 서비스 ────────────────────────────────────────────────
    // ~/enable: 모터 활성화/비활성화 (SetBool)
    srv_enable_ = this->create_service<std_srvs::srv::SetBool>(
      "~/enable",
      [this](const std_srvs::srv::SetBool::Request::SharedPtr req, std_srvs::srv::SetBool::Response::SharedPtr res) {
        enable_req_.store(req->data, std::memory_order_relaxed);
        res->success = true;
      });

    // ~/fault_reset: 모터 에러 해제 (Trigger)
    srv_fault_reset_ = this->create_service<std_srvs::srv::Trigger>(
      "~/fault_reset",
      [this](const std_srvs::srv::Trigger::Request::SharedPtr, std_srvs::srv::Trigger::Response::SharedPtr res) {
        fault_reset_req_.store(true, std::memory_order_relaxed);
        res->success = true;
      });

    // ── 타이머 (non-RT 주기 콜백) ──────────────────────────────────
    // publish_feedback: 50Hz — 모터 상태를 GUI로 발행
    pub_timer_ = this->create_wall_timer(
      std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::duration<double>(1.0 / std::max(1, publish_hz_))),
      std::bind(&EposNode::publish_feedback, this));

    // publish_diag_summary: 10Hz — RT 루프 주기 통계를 JSON으로 발행
    diag_timer_ = this->create_wall_timer(
      std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::duration<double>(1.0 / std::max(1, diag_hz_))),
      std::bind(&EposNode::publish_diag_summary, this));

    // ── EtherCAT 초기화 ────────────────────────────────────────────
    if (!init_ethercat()) {
      RCLCPP_ERROR(get_logger(), "EtherCAT 초기화 실패. iface=%s", iface_.c_str());
      return;
    }

    // 타임아웃 기준 시각 초기화
    last_heartbeat_ns_.store(now_monotonic_ns(), std::memory_order_relaxed);
    last_cmd_ns_.store(now_monotonic_ns(), std::memory_order_relaxed);

    // ── RT 제어 스레드 시작 ────────────────────────────────────────
    running_.store(true);
    logger_.init();  // 로거 백그라운드 스레드 시작
    control_thread_ = std::thread([this]() { control_loop_rt(); });

    RCLCPP_INFO(get_logger(), "epos_motor_node started. iface=%s", iface_.c_str());
  }

  ~EposNode() override
  {
    // RT 스레드 종료 대기
    running_.store(false);
    if (control_thread_.joinable()) control_thread_.join();
    logger_.stop();  // 로거 스레드 종료 + 파일 닫기

    // EtherCAT 종료: 모터가 마지막 명령 상태를 유지하므로,
    // 100ms 대기하여 속도 0 명령이 적용된 후 close
    if (operational_.load()) std::this_thread::sleep_for(100ms);
    ec_close();
    RCLCPP_INFO(get_logger(), "EtherCAT Closed.");
  }

private:

  // ══════════════════════════════════════════════════════════════════
  //  명령 핸들러 (ROS2 콜백에서 호출 — non-RT 스레드)
  // ══════════════════════════════════════════════════════════════════

  // ── CSV 로깅 명령 처리 ────────────────────────────────────────────
  // "start /path/to/file.csv" → 로깅 시작
  // "stop" → 로깅 중지
  void handle_log_cmd(const std::string& cmd)
  {
    auto parsed = parse_log_command(cmd);
    switch (parsed.kind) {
      case epos_control::LogCommandKind::STOP:
        logger_.stop_logging();
        RCLCPP_INFO(get_logger(), "CSV 로깅 중지.");
        break;

      case epos_control::LogCommandKind::START: {
        auto parent = ensure_parent_dir(parsed.path);
        if (!parent.ok) {
          RCLCPP_ERROR(get_logger(), "CSV 디렉토리 생성 실패: %s (%s)", parent.parent.c_str(), parent.error.c_str());
          return;
        }
        if (logger_.start_logging(parsed.path)) {
          RCLCPP_INFO(get_logger(), "CSV 로깅 시작: %s", parsed.path.c_str());
        } else {
          RCLCPP_ERROR(get_logger(), "CSV 파일 열기 실패: %s", parsed.path.c_str());
        }
        break;
      }

      case epos_control::LogCommandKind::INVALID:
        RCLCPP_WARN(get_logger(), "%s", parsed.error.c_str());
        break;

      case epos_control::LogCommandKind::UNKNOWN:
        break;
    }
  }

  // ── 파형 명령 처리 ────────────────────────────────────────────────
  bool start_hyst_sine(double freq_hz,
                       double amp_rpm,
                       double offset_rpm,
                       int settle_cycles,
                       int record_cycles,
                       const std::string& path)
  {
    epos_control::commands::HystVelocityCommand request;
    request.freq_hz = freq_hz;
    request.amp_rpm = amp_rpm;
    request.offset_rpm = offset_rpm;
    request.settle_cycles = settle_cycles;
    request.record_cycles = record_cycles;
    request.path = path;

    auto plan = make_hyst_velocity_plan(request, max_abs_target_, now_monotonic_ns());
    if (!plan.ok) {
      RCLCPP_WARN(get_logger(), "%s", plan.error.c_str());
      return false;
    }
    auto parent = ensure_parent_dir(plan.path);
    if (!parent.ok) {
      RCLCPP_ERROR(get_logger(), "CSV 디렉토리 생성 실패: %s (%s)", parent.parent.c_str(), parent.error.c_str());
      return false;
    }

    if (!logger_.start_logging_window(plan.path, plan.log_start_ns, plan.log_end_ns)) {
      RCLCPP_ERROR(get_logger(), "히스테리시스 CSV 파일 열기 실패: %s", plan.path.c_str());
      return false;
    }

    axis_.set_waveform(plan.waveform);
    RCLCPP_INFO(get_logger(),
                "히스테리시스 테스트 예약: freq=%.4fHz amp=%.3frpm offset=%.3frpm stable=%dcycle log=%dcycle file=%s",
                plan.freq_hz, plan.amp, plan.offset, plan.settle_cycles, plan.record_cycles, plan.path.c_str());
    return true;
  }

  bool start_hyst_pos_sine(double freq_hz,
                           double amp_ticks,
                           double offset_ticks,
                           double max_tps,
                           int settle_cycles,
                           int record_cycles,
                           const std::string& path)
  {
    epos_control::commands::HystPositionCommand request;
    request.freq_hz = freq_hz;
    request.amp_ticks = amp_ticks;
    request.offset_ticks = offset_ticks;
    request.max_tps = max_tps;
    request.settle_cycles = settle_cycles;
    request.record_cycles = record_cycles;
    request.path = path;

    auto plan = make_hyst_position_plan(request, now_monotonic_ns());
    if (!plan.ok) {
      RCLCPP_WARN(get_logger(), "%s", plan.error.c_str());
      return false;
    }
    auto parent = ensure_parent_dir(plan.path);
    if (!parent.ok) {
      RCLCPP_ERROR(get_logger(), "CSV 디렉토리 생성 실패: %s (%s)", parent.parent.c_str(), parent.error.c_str());
      return false;
    }

    if (!logger_.start_logging_window(plan.path, plan.log_start_ns, plan.log_end_ns)) {
      RCLCPP_ERROR(get_logger(), "히스테리시스 CSV 파일 열기 실패: %s", plan.path.c_str());
      return false;
    }

    requested_op_mode_.store(8, std::memory_order_relaxed);
    pos_speed_limit_.store(static_cast<int32_t>(std::lround(plan.max_tps)), std::memory_order_relaxed);
    axis_.set_waveform(plan.waveform);
    RCLCPP_INFO(get_logger(),
                "히스테리시스 위치 사인 예약: freq=%.4fHz amp=%.1ftick offset=%.1ftick max=%.1ftick/s stable=%dcycle log=%dcycle file=%s",
                plan.freq_hz, plan.amp, plan.offset, plan.max_tps, plan.settle_cycles, plan.record_cycles, plan.path.c_str());
    return true;
  }

  // GUI에서 WaveformCmd 객체를 수신 → WaveformConfig 생성 → 더블버퍼에 저장
  void handle_waveform_msg(const epos_interfaces::msg::WaveformCmd::SharedPtr msg)
  {
    apply_waveform_command(
      epos_control::commands::waveform_command_from_msg(*msg, max_abs_target_, now_monotonic_ns()),
      "[WAVEFORM:v2]");
  }

  // GUI에서 "sine 1.0 500 0" 같은 문자열을 수신 → WaveformConfig 생성 → 더블버퍼에 저장
  void handle_waveform_cmd(const std::string& cmd)
  {
    apply_waveform_command(
      epos_control::commands::waveform_command_from_string(cmd, max_abs_target_, now_monotonic_ns()),
      "[WAVEFORM]",
      cmd);
  }

  void apply_waveform_command(const epos_control::commands::WaveformCommand& cmd,
                              const char* label,
                              const std::string& raw_cmd = std::string())
  {
    using epos_control::commands::WaveformCommandKind;

    switch (cmd.kind) {
      case WaveformCommandKind::STOP:
        axis_.stop_waveform();
        break;

      case WaveformCommandKind::START_GENERAL:
        axis_.set_waveform(cmd.config);  // 더블버퍼 스위치 → RT 루프가 다음 사이클부터 새 파형 사용
        break;

      case WaveformCommandKind::START_HYST_VELOCITY:
        start_hyst_sine(
          cmd.hyst_velocity.freq_hz,
          cmd.hyst_velocity.amp_rpm,
          cmd.hyst_velocity.offset_rpm,
          cmd.hyst_velocity.settle_cycles,
          cmd.hyst_velocity.record_cycles,
          cmd.hyst_velocity.path);
        break;

      case WaveformCommandKind::START_HYST_POSITION:
        start_hyst_pos_sine(
          cmd.hyst_position.freq_hz,
          cmd.hyst_position.amp_ticks,
          cmd.hyst_position.offset_ticks,
          cmd.hyst_position.max_tps,
          cmd.hyst_position.settle_cycles,
          cmd.hyst_position.record_cycles,
          cmd.hyst_position.path);
        break;

      case WaveformCommandKind::INVALID:
        if (raw_cmd.empty()) {
          RCLCPP_WARN(get_logger(), "%s %s", label, cmd.error.c_str());
        } else {
          RCLCPP_WARN(get_logger(), "%s %s: %s", label, cmd.error.c_str(), raw_cmd.c_str());
        }
        break;

      case WaveformCommandKind::UNKNOWN:
        break;
    }
  }

  // ── 힘 제어 명령 처리 ────────────────────────────────────────────
  // v2 구조화 메시지. GUI가 epos_interfaces를 사용할 수 있으면 이 경로를 우선 사용한다.
  // 문자열 파싱을 C++ 제어 노드 밖으로 밀어내서 오타/순서 오류가 RT 상태에 영향을
  // 덜 주도록 만든다. 기존 문자열 토픽은 아래 handle_force_ctrl_cmd()에서 계속 지원한다.
  void handle_force_ctrl_msg(const epos_interfaces::msg::ForceCtrlCmd::SharedPtr msg)
  {
    apply_force_command(
      epos_control::commands::force_command_from_msg(*msg),
      "[FORCE CTRL:v2]",
      "[FORCE LIMIT:v2]");
  }

  // 공통 힘 제어 적용부.
  // v1 문자열 명령과 v2 구조화 메시지를 모두 ForceCommand로 변환한 뒤 여기서만 상태를 바꾼다.
  void apply_force_command(const epos_control::commands::ForceCommand& parsed,
                           const char* force_label,
                           const char* limit_label,
                           const std::string& raw_cmd = std::string())
  {
    using epos_control::commands::ForceCommandKind;

    switch (parsed.kind) {
      case ForceCommandKind::START:
        // release: RT 루프의 acquire와 쌍 → PID 리셋 후에만 활성화
        force_ctrl_active_.store(true, std::memory_order_release);
        RCLCPP_INFO(get_logger(), "%s 활성화 — target=%.1f N, dir=%d, feedback=%d",
                    force_label,
                    target_force_mN_.load(std::memory_order_relaxed) * MN_TO_N,
                    force_direction_.load(std::memory_order_relaxed),
                    force_feedback_mode_.load(std::memory_order_relaxed));
        break;

      case ForceCommandKind::STOP:
        force_ctrl_active_.store(false, std::memory_order_release);
        axis_.stop_force_waveform();
        target_.store(0, std::memory_order_relaxed);  // 안전: 속도 0으로 정지
        RCLCPP_INFO(get_logger(), "%s 비활성화", force_label);
        break;

      case ForceCommandKind::SET_TARGET:
        target_force_mN_.store(n_to_mN(parsed.target_N), std::memory_order_relaxed);
        break;

      case ForceCommandKind::SET_DIRECTION: {
        const int dir = (parsed.direction < 0) ? -1 : 1;
        force_direction_.store(dir, std::memory_order_relaxed);
        RCLCPP_INFO(get_logger(), "%s direction=%d", force_label, dir);
        break;
      }

      case ForceCommandKind::SET_FEEDBACK:
        force_feedback_mode_.store(parsed.feedback_mode, std::memory_order_relaxed);
        RCLCPP_INFO(get_logger(), "%s feedback=%s (%d)",
                    force_label,
                    parsed.feedback_label.c_str(), parsed.feedback_mode);
        break;

      case ForceCommandKind::SET_FORCE_ABS:
        force_abs_mode_.store(parsed.enabled != 0, std::memory_order_relaxed);
        RCLCPP_INFO(get_logger(), "%s |F| mode=%s", force_label, parsed.enabled != 0 ? "ON" : "OFF");
        break;

      case ForceCommandKind::SET_PID:
        force_kp_.store(parsed.kp, std::memory_order_relaxed);
        force_ki_.store(parsed.ki, std::memory_order_relaxed);
        force_kd_.store(parsed.kd, std::memory_order_relaxed);
        force_ctrl_mode_.store(0, std::memory_order_relaxed);  // PID 모드로 전환
        RCLCPP_INFO(get_logger(), "%s mode=PID, gains=%.3f/%.3f/%.3f",
                    force_label,
                    parsed.kp, parsed.ki, parsed.kd);
        break;

      case ForceCommandKind::SET_TANH: {
        // "tanh <sensitivity_N> <deadband_N>"
        // 예: "tanh 1.0 0.01" → 1N 오차는 빠르게, 0.1N/0.01N 근처는 점점 섬세하게 접근
        double sens_N = std::max(0.01, std::min(50.0, parsed.tanh_sens_N));
        double dead_N = std::max(0.0, std::min(10.0, parsed.tanh_dead_N));
        force_tanh_sensitivity_.store(std::max(0.001, sens_N) * N_TO_MN, std::memory_order_relaxed);
        force_tanh_deadband_.store(std::max(0.0, dead_N) * N_TO_MN, std::memory_order_relaxed);
        force_ctrl_mode_.store(1, std::memory_order_relaxed);  // Tanh 모드로 전환
        RCLCPP_INFO(get_logger(), "%s mode=Tanh, sens=%.2fN, dead=%.2fN", force_label, sens_N, dead_N);
        break;
      }

      case ForceCommandKind::SET_TARE_OFFSET: {
        const double offset_N = std::max(-100000.0, std::min(100000.0, parsed.tare_offset_N));
        int32_t offset_mN = n_to_mN(offset_N);
        if (parsed.tare_channel == 0) {
          force_tare_ch0_mN_.store(offset_mN, std::memory_order_relaxed);
        } else {
          force_tare_ch1_mN_.store(offset_mN, std::memory_order_relaxed);
        }
        RCLCPP_INFO(get_logger(), "%s CH%d tare_offset=%.3f N", force_label, parsed.tare_channel, offset_N);
        break;
      }

      case ForceCommandKind::TARE_RESET:
        force_tare_ch0_mN_.store(0, std::memory_order_relaxed);
        force_tare_ch1_mN_.store(0, std::memory_order_relaxed);
        RCLCPP_INFO(get_logger(), "%s tare_offset reset", force_label);
        break;

      case ForceCommandKind::SET_MAX_RPM:
        force_max_rpm_.store(std::max(1, std::min(max_abs_target_, parsed.max_rpm)), std::memory_order_relaxed);
        RCLCPP_INFO(get_logger(), "%s max_rpm=%d", force_label, parsed.max_rpm);
        break;

      case ForceCommandKind::SET_LIMIT: {
        int32_t limit_mN = n_to_mN(std::max(0.0, parsed.limit_N));
        force_limit_mN_.store(limit_mN, std::memory_order_relaxed);
        if (limit_mN <= 0) force_limit_tripped_.store(false, std::memory_order_relaxed);
        RCLCPP_INFO(get_logger(), "%s limit=%.2f N", limit_label, limit_mN * MN_TO_N);
        break;
      }

      case ForceCommandKind::SET_ALPHA:
        // 0.01~1.0 범위 클램프: 0에 가까울수록 부드러움, 1이면 필터 없음
        force_out_alpha_.store(std::max(0.01, std::min(1.0, parsed.alpha)), std::memory_order_relaxed);
        RCLCPP_INFO(get_logger(), "%s output_alpha=%.2f", force_label, parsed.alpha);
        break;

      case ForceCommandKind::SET_WAVEFORM:
        if (parsed.waveform_payload.empty() || parsed.waveform_payload == "none" || parsed.waveform_payload == "stop") {
          axis_.stop_force_waveform();
          return;
        }
        // 힘 파형: 진폭/오프셋이 mN 단위 (속도 파형은 RPM 단위)
        if (auto result = waveform::parse_command(parsed.waveform_payload, 999999, now_monotonic_ns());
            result.error_msg.empty()) {
          axis_.set_force_waveform(result.config);
          RCLCPP_INFO(get_logger(), "%s 힘 파형 시작: %s", force_label, parsed.waveform_payload.c_str());
        }
        break;

      case ForceCommandKind::INVALID:
        if (raw_cmd.empty()) {
          RCLCPP_WARN(get_logger(), "%s %s", force_label, parsed.error.c_str());
        } else {
          RCLCPP_WARN(get_logger(), "%s %s: %s", force_label, parsed.error.c_str(), raw_cmd.c_str());
        }
        break;

      case ForceCommandKind::UNKNOWN:
        break;
    }
  }

  // 문자열 기반 v1 프로토콜 (기존 GUI/스크립트 호환용):
  //   "start"              → 힘 제어 활성화
  //   "stop"               → 힘 제어 비활성화 + 속도 0
  //   "target 50.0"        → 목표 힘 50N으로 변경
  //   "direction 1/-1"     → 모터 양수RPM과 힘 증가 방향의 관계
  //   "pid 0.5 0.05 0.01"  → PID 게인 실시간 변경
  //   "maxrpm 50"          → 힘 제어 시 최대 모터 속도
  //   "alpha 0.3"          → 출력 IIR 필터 계수
  //   "force_abs 1/0"      → 힘 제어를 장력 크기(|F|) 기준으로 수행
  //   "tare_offset 0 1.23" → CH0 외부 Tare 오프셋 1.23N 적용
  //   "tare_reset"         → 외부 Tare 오프셋 전체 해제
  //   "waveform sine 1.0 50000 0" → 힘 파형 (mN 단위)
  void handle_force_ctrl_cmd(const std::string& cmd)
  {
    apply_force_command(
      epos_control::commands::parse_force_ctrl(cmd),
      "[FORCE CTRL]",
      "[FORCE LIMIT]",
      cmd);
  }

  // ══════════════════════════════════════════════════════════════════
  //  EtherCAT 초기화
  // ══════════════════════════════════════════════════════════════════

  // ── EtherCAT 초기화 시퀀스 ────────────────────────────────────────
  // SOEM 상태 머신: Init → Pre-OP → Safe-OP → Operational
  //
  // Pre-OP → Safe-OP 전환 시 setup_epos_pdo_mapping()이 자동 호출되어 PDO 매핑 설정.
  // Safe-OP에서 PDO 교환을 50회 수행하여 모터가 안정화된 후 OP로 전환.
  // OP 전환 실패 시 false 반환 → 노드 초기화 중단.
  bool init_ethercat() {
    std::memset(IOmap_, 0, sizeof(IOmap_));
    if (!ec_init(iface_.c_str())) return false;        // 네트워크 인터페이스 열기
    if (ec_config_init(FALSE) <= 0) { ec_close(); return false; }  // 슬레이브 탐색

    int si = axis_.slave_index;
    if (si < 1 || si > ec_slavecount) si = 1;
    axis_.slave_index = si;

    // PO2SOconfig: Pre-OP → Safe-OP 전환 시 호출될 콜백 등록
    ec_slave[si].PO2SOconfig = &epos_control::setup_epos_pdo_mapping;

    // IOmap 매핑: PDO 데이터가 이 버퍼를 통해 교환됨
    ec_config_map(&IOmap_);
    ec_statecheck(0, EC_STATE_SAFE_OP, EC_TIMEOUTSTATE * 4);

    // Safe-OP에서 PDO 교환 반복 → 모터 내부 버퍼 안정화
    for (int i = 0; i < 50; i++) {
      ec_send_processdata();
      ec_receive_processdata(EC_TIMEOUTRET);
      std::this_thread::sleep_for(2ms);
    }

    // OP 전환 요청
    ec_slave[0].state = EC_STATE_OPERATIONAL;
    ec_writestate(0);

    // OP 도달 확인 (최대 40회 × 2ms = 80ms 대기)
    // 미확인 시 초반 burst 에러 유발 가능
    for (int i = 0; i < 40; i++) {
      ec_send_processdata();
      ec_receive_processdata(EC_TIMEOUTRET);
      ec_statecheck(0, EC_STATE_OPERATIONAL, 50000);
      if (ec_slave[0].state == EC_STATE_OPERATIONAL) break;
      std::this_thread::sleep_for(2ms);
    }
    if (ec_slave[0].state != EC_STATE_OPERATIONAL) {
      RCLCPP_ERROR(get_logger(), "OP 전환 실패. state=0x%x", ec_slave[0].state);
      return false;
    }
    operational_.store(true);
    return true;
  }

  // ── 모노토닉 시계 (나노초) ────────────────────────────────────────
  // CLOCK_MONOTONIC: 시스템 시간 변경에 영향받지 않는 단조 증가 시계.
  // RT 타이밍의 기준으로 사용. NTP 보정 등에 영향 안 받음.
  static int64_t now_monotonic_ns() {
    timespec ts{}; clock_gettime(CLOCK_MONOTONIC, &ts);
    return static_cast<int64_t>(ts.tv_sec) * 1000000000LL + ts.tv_nsec;
  }

  // ══════════════════════════════════════════════════════════════════
  //  RT 제어 루프 (별도 스레드)
  // ══════════════════════════════════════════════════════════════════

  // ── RT 스레드 설정 ────────────────────────────────────────────────
  // 이 함수는 control_loop_rt() 진입 직후 1회 호출.
  // 3가지 RT 최적화를 적용:
  void try_configure_realtime() {
    auto result = configure_realtime_thread(rt_priority_, rt_cpu_);
    if (!result.mlock_ok) {
      RCLCPP_WARN(get_logger(), "mlockall 실패");
    }
    if (!result.scheduler_ok) {
      RCLCPP_WARN(get_logger(), "RT 스케줄러 설정 실패");
    }
    if (result.affinity_requested) {
      if (result.affinity_ok) {
        RCLCPP_INFO(get_logger(), "RT 스레드 CPU %d 고정", rt_cpu_);
      } else {
        RCLCPP_WARN(get_logger(), "RT 스레드 CPU %d 고정 실패", rt_cpu_);
      }
    }
  }

  // ── 메인 제어 루프 (1000Hz) ───────────────────────────────────────
  // 이 함수가 모터 제어의 핵심. 매 1ms마다:
  //   1. 정확한 타이밍에 깨어남 (clock_nanosleep 절대 시각)
  //   2. EtherCAT PDO 송수신
  //   3. 모터 상태 읽기
  //   4. 제어 계산 (속도/위치/토크/힘)
  //   5. 명령 쓰기
  //   6. 로그 기록
  void control_loop_rt()
  {
    try_configure_realtime();

    const int hz = std::max(1, cycle_hz_);
    const int64_t period_ns = 1000000000LL / hz;  // 1ms = 1,000,000 ns

    int64_t next_ns = now_monotonic_ns();          // 다음 깨어날 시각
    int64_t last_cycle_ns = now_monotonic_ns();    // 지난 사이클 시각 (dt 계산용)
    bool first = true;                              // 첫 사이클 플래그 (dt=0 방지)
    int si = axis_.slave_index;

    // 상태 변수 (이 스레드 로컬 — atomic 불필요)
    bool was_fault = false;              // 이전 사이클 fault 여부
    bool was_force_ctrl = false;         // 이전 사이클 힘 제어 여부
    double current_cmd_vel = 0.0;        // 현재 속도 명령 (slew rate limiter 출력)
    epos_control::PositionControlState pos_control_state;

    while (running_.load() && rclcpp::ok())
    {
      if (!operational_.load()) { std::this_thread::sleep_for(10ms); continue; }

      // ── 타이밍: 다음 깨어날 절대 시각 계산 ──────────────────────
      next_ns += period_ns;
      const int64_t now = now_monotonic_ns();
      if (next_ns <= now) {
        // 과거 시각이면 즉시 리턴하며 burst 발생 → 현재 기준으로 리셋
        next_ns = now + period_ns;
      }

      // clock_nanosleep(TIMER_ABSTIME): 절대 시각까지 대기.
      // sleep(duration)과 달리 누적 오차가 없음 → 장시간 운전에도 정확.
      // EINTR: 시그널에 의해 깨어난 경우 → 재시도
      timespec ts{};
      ts.tv_sec  = next_ns / 1000000000LL;
      ts.tv_nsec = next_ns % 1000000000LL;
      int sleep_rc;
      do {
        sleep_rc = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &ts, nullptr);
      } while (sleep_rc == EINTR);

      // ── 주기 측정 ────────────────────────────────────────────────
      const int64_t now_ns = now_monotonic_ns();
      const int64_t dt_ns  = now_ns - last_cycle_ns;  // 실제 경과 시간
      last_cycle_ns = now_ns;

      int32_t dt_us_val = 0;
      if (!first) {
        dt_us_val = static_cast<int32_t>(dt_ns / 1000LL);  // ns → μs
        cycle_dt_us_.store(dt_us_val, std::memory_order_relaxed);
        diag_ring_.push(dt_us_val);  // 진단 통계용 링버퍼에 기록
        // overrun 감지: 주기가 (목표 + 임계값)을 초과하면 카운트 증가
        if (dt_ns > period_ns + static_cast<int64_t>(overrun_thresh_us_) * 1000LL)
          cycle_overrun_count_.fetch_add(1, std::memory_order_relaxed);
      } else first = false;

      // ── EtherCAT PDO 교환 ────────────────────────────────────────
      // send: 이전 사이클에서 준비한 출력 데이터를 모터로 전송
      // receive: 모터의 최신 상태를 수신
      // WKC (Working Counter): 정상 응답한 슬레이브 수. 0이면 통신 실패.
      ec_send_processdata();
      const int wkc = ec_receive_processdata(EC_TIMEOUTRET);
      last_wkc_.store(wkc, std::memory_order_relaxed);

      if (wkc <= 0) {
          // 통신 실패 → 이번 사이클은 제어 계산 건너뛰기
          // (잘못된 데이터로 제어하면 위험)
          wkc_error_count_.fetch_add(1, std::memory_order_relaxed);
          consecutive_wkc_errors_.fetch_add(1, std::memory_order_relaxed);
          if (logger_.is_active()) {
            LogRecord rec{};
            rec.timestamp_ns = now_ns;
            rec.dt_us = dt_us_val;
            rec.error_code = -1;  // WKC 실패 표시
            logger_.push_record(rec);
          }
          continue;  // 제어 계산 건너뜀
      }
      consecutive_wkc_errors_.store(0, std::memory_order_relaxed);

      // ── PDO 데이터 포인터 획득 ────────────────────────────────────
      // SOEM이 IOmap 안에 슬레이브별 입출력 영역을 매핑해둠.
      // 이 포인터를 OutPDO/InPDO로 캐스팅하면 구조체 멤버로 직접 접근 가능.
      auto *in  = reinterpret_cast<InPDO*>(ec_slave[si].inputs);
      auto *out = reinterpret_cast<OutPDO*>(ec_slave[si].outputs);
      if (!in || !out) continue;

      // ── 모터 상태 읽기 → atomic에 저장 (non-RT가 읽어감) ──────────
      axis_.last_status.store(in->status_word, std::memory_order_relaxed);
      axis_.last_pos.store(in->actual_position, std::memory_order_relaxed);
      axis_.last_vel.store(in->actual_velocity, std::memory_order_relaxed);
      axis_.last_trq.store(in->actual_torque, std::memory_order_relaxed);

      // ── CiA402 상태 머신: Fault 감지 ──────────────────────────────
      const bool enable_desired = (auto_enable_ || enable_req_.load(std::memory_order_relaxed));
      const uint16_t status = in->status_word;
      const bool is_fault = epos_control::cia402::is_fault(status);

      // Fault 발생 순간 (was_fault=false → is_fault=true)
      if (is_fault && !was_fault) {
        // non-RT의 publish_feedback에서 SDO로 에러코드를 읽도록 플래그 설정
        pending_fault_status_.store(status, std::memory_order_relaxed);
        fault_log_pending_.store(true, std::memory_order_relaxed);
        // Fault 시 현재 위치/속도로 동기화 → 복구 후 갑자기 튀는 것 방지
        target_pos_.store(in->actual_position, std::memory_order_relaxed);
        target_.store(0, std::memory_order_relaxed);
        current_cmd_vel = 0;
        target_trq_.store(0, std::memory_order_relaxed);
      }
      was_fault = is_fault;

      // ── 동작 모드 전환 ────────────────────────────────────────────
      int8_t current_mode = axis_.op_mode.load(std::memory_order_relaxed);
      int8_t req_mode = requested_op_mode_.load(std::memory_order_relaxed);

      if (current_mode != req_mode) {
        // 모드 변경 시 안전 초기화: 새 모드의 목표값을 현재 상태로 맞춤
        if (req_mode == 8) {  // → 위치 제어
          target_pos_.store(in->actual_position, std::memory_order_relaxed);
        } else if (req_mode == 9) {  // → 속도 제어
          target_.store(0, std::memory_order_relaxed);
          current_cmd_vel = 0;
        } else if (req_mode == 10) {  // → 토크 제어
          target_trq_.store(0, std::memory_order_relaxed);
        }
        axis_.op_mode.store(req_mode, std::memory_order_relaxed);
        current_mode = req_mode;
      }

      // ── 제어 출력 계산 ────────────────────────────────────────────
      int32_t out_vel = 0;
      int32_t out_pos = in->actual_position;  // 위치 기본값: 현재 위치 유지
      int16_t out_trq = 0;

      // 파형 확인: 속도 파형은 CSV, 위치 사인파는 내부 위치 추종 모드로 전환
      WaveformConfig wf = axis_.get_waveform_copy();
      if (wf.type == WaveformType::POSITION_SINE) {
          if (current_mode != 8) {
            current_mode = 8;
            axis_.op_mode.store(8, std::memory_order_relaxed);
            requested_op_mode_.store(8, std::memory_order_relaxed);
          }
      } else if (wf.type != WaveformType::NONE && current_mode != 9) {
          current_mode = 9;
          axis_.op_mode.store(9, std::memory_order_relaxed);
          requested_op_mode_.store(9, std::memory_order_relaxed);
      } else if (wf.type != WaveformType::POSITION_SINE) {
          pos_control_state.active_wave_start_ns = 0;
      }

      // ── 위치 제어 (mode 8 → 내부적으로 CSV mode 9로 변환) ────────
      // EPOS4 CSP 모드를 직접 쓰지 않는 이유:
      //   CSP는 매 사이클 정확한 위치를 보내야 하는데,
      //   마스터(PC)와 슬레이브(모터)의 클럭이 미세하게 다르면
      //   위치가 한 틱씩 밀리면서 꿀렁거리는 현상 발생.
      //   → 마스터에서 P제어로 속도를 계산한 뒤 CSV로 보내면 해결.
      if (current_mode == 8) {
        int32_t current_pos = in->actual_position;
        auto pos_cmd = compute_position_csv_command(
            wf,
            now_ns,
            current_pos,
            target_pos_.load(std::memory_order_relaxed),
            pos_speed_limit_.load(std::memory_order_relaxed),
            pos_p_gain_,
            motor_ticks_per_rev_,
            pos_control_state);
        target_pos_.store(pos_cmd.target_pos, std::memory_order_relaxed);
        out_vel = pos_cmd.target_rpm;
        out_pos = current_pos;

        // EPOS4에게는 mode=9(CSV)로 보냄 → CSP 클럭 불일치 문제 회피
        out->mode_of_operation = 9;

      // ── 속도 제어 (mode 9) ──────────────────────────────────────
      } else if (current_mode == 9) {
        auto vel_cmd = compute_velocity_csv_command(
            wf,
            now_ns,
            in->actual_position,
            target_.load(std::memory_order_relaxed),
            accel_limit_rpm_s_.load(std::memory_order_relaxed),
            max_abs_target_,
            current_cmd_vel,
            dt_ns);
        current_cmd_vel = vel_cmd.filtered_rpm;
        out_vel = vel_cmd.target_rpm;
        out_pos = vel_cmd.hold_position;  // CSV 모드에서는 위치 필드 무시됨

      // ── 토크 제어 (mode 10) ─────────────────────────────────────
      } else if (current_mode == 10) {
        out_trq = target_trq_.load(std::memory_order_relaxed);
        out_pos = in->actual_position;
      }

      // ── 힘 제어 (활성 시 속도 출력을 PID 출력으로 덮어씀) ────────
      // 힘 제어는 CSV 모드 위에서 동작: PID가 RPM을 출력 → 모터 속도 명령
      int32_t force_ch0_mN = last_force_ch0_mN_.load(std::memory_order_relaxed)
                            - force_tare_ch0_mN_.load(std::memory_order_relaxed);
      int32_t force_ch1_mN = last_force_ch1_mN_.load(std::memory_order_relaxed)
                            - force_tare_ch1_mN_.load(std::memory_order_relaxed);
      auto force_selection = select_force_feedback(
          force_ch0_mN,
          force_ch1_mN,
          force_feedback_mode_.load(std::memory_order_relaxed),
          force_abs_mode_.load(std::memory_order_relaxed));

      // ── RT 힘 한계 체크 ──────────────────────────────────────────
      // 힘 한계는 안전장치이므로 50Hz 피드백 타이머가 아니라 1kHz RT 루프에서 판단한다.
      // 로그 출력은 RT 밖의 publish_feedback()에서 처리하도록 이벤트만 남긴다.
      int32_t limit_mN = force_limit_mN_.load(std::memory_order_relaxed);
      auto force_limit = check_force_limit(
          limit_mN,
          now_ns,
          force_ch0_mN,
          force_ch1_mN,
          last_force_ch0_ns_.load(std::memory_order_relaxed),
          last_force_ch1_ns_.load(std::memory_order_relaxed));
      if (force_limit.has_valid_data) {
        bool was_tripped = force_limit_tripped_.load(std::memory_order_relaxed);
        if (force_limit.over_limit && !was_tripped) {
          force_limit_tripped_.store(true, std::memory_order_relaxed);
          force_limit_peak_mN_.store(force_limit.peak_mN, std::memory_order_relaxed);
          force_limit_threshold_mN_.store(limit_mN, std::memory_order_relaxed);
          force_limit_event_.store(1, std::memory_order_release);
          target_.store(0, std::memory_order_relaxed);
          current_cmd_vel = 0.0;
        } else if (!force_limit.over_limit && was_tripped) {
          force_limit_tripped_.store(false, std::memory_order_relaxed);
          force_limit_peak_mN_.store(force_limit.peak_mN, std::memory_order_relaxed);
          force_limit_threshold_mN_.store(limit_mN, std::memory_order_relaxed);
          force_limit_event_.store(-1, std::memory_order_release);
        }
      }

      bool fc_active = force_ctrl_active_.load(std::memory_order_acquire);
      if (fc_active && !was_force_ctrl) {
        // 힘 제어 시작 순간: 상태 초기화 + CSV 모드 강제
        force_pid_.reset();
        current_cmd_vel = 0.0;
        target_.store(0, std::memory_order_relaxed);
        current_mode = 9;
        axis_.op_mode.store(9, std::memory_order_relaxed);
        requested_op_mode_.store(9, std::memory_order_relaxed);
      }
      was_force_ctrl = fc_active;

      if (fc_active) {
        // CSV 모드 유지 강제
        if (current_mode != 9) {
          current_mode = 9;
          axis_.op_mode.store(9, std::memory_order_relaxed);
          requested_op_mode_.store(9, std::memory_order_relaxed);
        }

        // 실제 힘은 선택된 모드에 따라 signed 또는 |F| 기준으로 사용한다.
        // direction은 "양수 제어출력(힘 증가 명령)"을 실제 모터 RPM 방향으로 바꿀 때 적용한다.
        ForceControlParams force_params;
        force_params.target_force_mN = target_force_mN_.load(std::memory_order_relaxed);
        force_params.direction = force_direction_.load(std::memory_order_relaxed);
        force_params.max_rpm = force_max_rpm_.load(std::memory_order_relaxed);
        force_params.ctrl_mode = force_ctrl_mode_.load(std::memory_order_relaxed);
        force_params.fallback_max_rpm = max_abs_target_;
        force_params.kp = force_kp_.load(std::memory_order_relaxed);
        force_params.ki = force_ki_.load(std::memory_order_relaxed);
        force_params.kd = force_kd_.load(std::memory_order_relaxed);
        force_params.tanh_sensitivity_mN = force_tanh_sensitivity_.load(std::memory_order_relaxed);
        force_params.tanh_deadband_mN = force_tanh_deadband_.load(std::memory_order_relaxed);
        force_params.output_alpha = force_out_alpha_.load(std::memory_order_relaxed);

        auto force_cmd = compute_force_control_command(
            axis_.get_force_wf_copy(),
            now_ns,
            force_selection.control_mN,
            force_params,
            current_cmd_vel,
            dt_ns,
            force_pid_,
            force_tanh_);

        current_cmd_vel = force_cmd.filtered_rpm;
        out_vel = force_cmd.target_rpm;
        if (force_limit_tripped_.load(std::memory_order_relaxed)) {
          current_cmd_vel = 0.0;
          out_vel = 0;
        }
        out_pos = in->actual_position;
        out->mode_of_operation = 9;
      }

      // ── CiA402 상태 머신: control_word 결정 ──────────────────────
      // EPOS4는 CiA402 표준 상태 머신을 따름:
      //   Not Ready → Switch On Disabled → Ready to Switch On
      //     → Switched On → Operation Enabled
      // 각 상태에서 적절한 control_word를 보내야 다음 상태로 전환됨.
      uint16_t control = epos_control::cia402::CONTROL_SHUTDOWN;  // 기본: Shutdown

      if (is_fault) {
        // Fault 상태: 0x0080(Fault Reset)을 20사이클(20ms) 유지
        if (fault_reset_req_.exchange(false)) {
          fault_reset_hold_ = 20;
        }
        if (fault_reset_hold_ > 0) {
          control = epos_control::cia402::CONTROL_FAULT_RESET;
          fault_reset_hold_--;
        }
      } else {
        fault_reset_hold_ = 0;
        // 정상 상태: status_word의 하위 비트를 보고 적절한 전환 명령 결정
        control = epos_control::cia402::next_control_word(status, enable_desired);
      }

      // ── 최종 출력 안전장치 ────────────────────────────────────────
      // 모드별 제어 계산이 끝난 뒤, PDO에 쓰기 직전 공통 안전 조건을 한 번에 적용한다.
      OutputSafetyInput safety_input;
      safety_input.now_ns = now_ns;
      safety_input.is_fault = is_fault;
      safety_input.enable_desired = enable_desired;
      safety_input.force_limit_tripped = force_limit_tripped_.load(std::memory_order_relaxed);
      safety_input.cmd_timeout_ms = cmd_timeout_ms_;
      safety_input.last_cmd_ns = last_cmd_ns_.load(std::memory_order_relaxed);
      safety_input.heartbeat_timeout_ms = heartbeat_timeout_ms_;
      safety_input.last_heartbeat_ns = last_heartbeat_ns_.load(std::memory_order_relaxed);
      safety_input.max_abs_rpm = max_abs_target_;
      auto safe_output = apply_output_safety(out_vel, out_trq, safety_input);
      out_vel = safe_output.target_velocity;
      out_trq = safe_output.target_torque;

      // ── PDO 출력 쓰기 ────────────────────────────────────────────
      // 위치 모드(8)일 때는 이미 mode_of_operation=9로 설정했으므로 여기서 덮어쓰지 않음
      if (current_mode != 8) out->mode_of_operation = current_mode;
      out->control_word      = control;
      out->target_position   = out_pos;
      out->target_velocity   = out_vel;
      out->target_torque     = out_trq;

      // ── CSV 로그 레코드 생성 ──────────────────────────────────────
      LogRecord rec;
      rec.timestamp_ns = now_ns;
      rec.op_mode      = current_mode;
      rec.target_pos   = out_pos;
      rec.actual_pos   = in->actual_position;
      rec.target_vel   = out_vel;
      rec.actual_vel   = in->actual_velocity;
      rec.target_trq   = out_trq;
      rec.actual_trq   = in->actual_torque;
      rec.dt_us        = dt_us_val;
      rec.status_word  = status;
      rec.error_code   = axis_.last_error_code.load(std::memory_order_relaxed);
      rec.wf_type      = static_cast<int>(wf.type);
      int32_t raw_ch0_mN = last_force_ch0_mN_.load(std::memory_order_relaxed);
      int32_t raw_ch1_mN = last_force_ch1_mN_.load(std::memory_order_relaxed);
      rec.load_cell_N      = mN_to_N_float(force_selection.signed_mN);
      rec.lc_ch0_N         = mN_to_N_float(raw_ch0_mN);
      rec.lc_ch1_N         = mN_to_N_float(raw_ch1_mN);
      rec.load_cell_abs_N  = mN_to_N_float(force_selection.abs_mN);
      rec.lc_ch0_abs_N     = mN_to_N_float(std::abs(raw_ch0_mN));
      rec.lc_ch1_abs_N     = mN_to_N_float(std::abs(raw_ch1_mN));
      rec.linear_encoder_count = last_linear_count_.load(std::memory_order_relaxed);
      rec.linear_encoder_mm    = static_cast<float>(
        static_cast<double>(last_linear_um_.load(std::memory_order_relaxed)) / 1000.0);

      logger_.push_record(rec);  // 링버퍼에 넣기 (lock-free)
    }
  }

  // ══════════════════════════════════════════════════════════════════
  //  GUI 피드백 발행 (non-RT 타이머 콜백, 50Hz)
  // ══════════════════════════════════════════════════════════════════
  // RT 스레드에서 atomic에 저장한 값을 읽어 ROS2 토픽으로 발행.
  // SDO 읽기(느림)도 여기서 수행 → RT 스레드의 지연 방지.
  void publish_feedback()
  {
    publish_core_feedback();
    handle_pending_fault_log();
    handle_wkc_recovery();
    publish_force_limit_events();
  }

  static void publish_int32(
      const rclcpp::Publisher<std_msgs::msg::Int32>::SharedPtr& publisher,
      int32_t value)
  {
    if (!publisher) return;
    std_msgs::msg::Int32 msg{};
    msg.data = value;
    publisher->publish(msg);
  }

  void publish_core_feedback()
  {
    publish_int32(pub_speed_,        axis_.last_vel.load(std::memory_order_relaxed));
    publish_int32(pub_stat_,         static_cast<int32_t>(axis_.last_status.load(std::memory_order_relaxed)));
    publish_int32(pub_pos_,          axis_.last_pos.load(std::memory_order_relaxed));
    publish_int32(pub_trq_,          static_cast<int32_t>(axis_.last_trq.load(std::memory_order_relaxed)));
    publish_int32(pub_wkc_,          last_wkc_.load(std::memory_order_relaxed));
    publish_int32(pub_cycle_dt_,     cycle_dt_us_.load(std::memory_order_relaxed));
    publish_int32(pub_cycle_jitter_, cycle_jitter_us_.load(std::memory_order_relaxed));
    publish_int32(pub_overrun_cnt_,  cycle_overrun_count_.load(std::memory_order_relaxed));
    publish_int32(pub_wkc_err_cnt_,  wkc_error_count_.load(std::memory_order_relaxed));
    publish_int32(pub_error_code_,   axis_.last_error_code.load(std::memory_order_relaxed));
  }

  void handle_pending_fault_log()
  {
    // RT 스레드에서 fault_log_pending_=true로 설정하면 여기서 SDO로
    // 0x603F(Error Code Register)를 읽는다. SDO는 느리므로 RT에서 호출하지 않는다.
    if (fault_log_pending_.exchange(false, std::memory_order_relaxed)) {
      uint16_t fs = pending_fault_status_.load(std::memory_order_relaxed);
      uint32_t sdo_err = 0;
      int sdo_size = static_cast<int>(sizeof(sdo_err));
      if (ec_SDOread(axis_.slave_index, EposReg::ERROR_CODE, 0x00, FALSE, &sdo_size, &sdo_err, EC_TIMEOUTSAFE) > 0) {
        axis_.last_error_code.store(static_cast<int32_t>(sdo_err & 0xFFFF), std::memory_order_relaxed);
      }
      uint16_t fe = static_cast<uint16_t>(axis_.last_error_code.load(std::memory_order_relaxed));
      RCLCPP_ERROR(get_logger(), "FAULT! status=0x%04X, error=0x%04X (%s)", fs, fe, epos_error_str(fe));
    }
  }

  void handle_wkc_recovery()
  {
    // 일정 횟수 이상 WKC 오류가 연속되면 슬레이브가 OP에서 빠졌을 가능성이 있다.
    if (wkc_recover_threshold_ <= 0) return;

    int32_t consec = consecutive_wkc_errors_.load(std::memory_order_relaxed);
    if (consec > 0 && (consec % wkc_recover_threshold_) == 0) {
      RCLCPP_WARN(get_logger(), "WKC 연속 오류 %d회 → EtherCAT 상태 복구 시도", consec);
      ec_statecheck(0, EC_STATE_OPERATIONAL, 50000);
      if (ec_slave[0].state != EC_STATE_OPERATIONAL) {
        ec_slave[0].state = EC_STATE_OPERATIONAL;
        ec_writestate(0);
      }
    }
  }

  void publish_force_limit_events()
  {
    // 한계 판단은 RT 루프에서 1kHz로 수행하고, 여기서는 전환 이벤트만 로그로 남긴다.
    int32_t force_limit_event = force_limit_event_.exchange(0, std::memory_order_acquire);
    if (force_limit_event != 0) {
      int32_t peak_mN = force_limit_peak_mN_.load(std::memory_order_relaxed);
      int32_t limit_mN = force_limit_threshold_mN_.load(std::memory_order_relaxed);
      if (force_limit_event > 0) {
        RCLCPP_ERROR(get_logger(), "[FORCE LIMIT] max|F| %.2f N > %.1f N → 속도 0 강제",
                     peak_mN * MN_TO_N, limit_mN * MN_TO_N);
      } else {
        RCLCPP_INFO(get_logger(), "[FORCE LIMIT] 해제 (현재 max|F| %.2f N)", peak_mN * MN_TO_N);
      }
    }
  }

  // ══════════════════════════════════════════════════════════════════
  //  진단 요약 발행 (non-RT 타이머 콜백, 10Hz)
  // ══════════════════════════════════════════════════════════════════
  // RT 루프에서 수집한 주기(dt) 데이터의 통계를 JSON으로 발행.
  // GUI의 진단 바에서 평균 주기, 최소/최대, 평균 지터를 표시하는 데 사용.
  void publish_diag_summary()
  {
    if (!pub_diag_summary_) return;

    std::vector<int32_t> dt_data;
    size_t count = diag_ring_.drain(dt_data);

    if (count > 0) {
      int64_t sum_dt = 0;
      int64_t sum_jitter = 0;
      int32_t min_dt = 9999999;
      int32_t max_dt = 0;

      // 기대 주기 [μs] = 1000000 / Hz
      const int32_t expected_dt = 1000000 / std::max(1, cycle_hz_);

      for (int32_t dt : dt_data) {
        sum_dt += dt;
        int32_t jitter = std::abs(dt - expected_dt);  // 지터 = |실측 - 기대|
        sum_jitter += jitter;
        if (dt < min_dt) min_dt = dt;
        if (dt > max_dt) max_dt = dt;
      }

      int32_t avg_dt = static_cast<int32_t>(sum_dt / count);
      int32_t avg_jitter = static_cast<int32_t>(sum_jitter / count);

      cycle_jitter_us_.store(avg_jitter, std::memory_order_relaxed);

      // JSON 형태로 발행 → GUI에서 json.loads()로 파싱
      char buf[256];
      snprintf(buf, sizeof(buf),
               "{\"count\":%zu, \"avg_dt\":%d, \"min_dt\":%d, \"max_dt\":%d, \"avg_jitter\":%d}",
               count, avg_dt, min_dt, max_dt, avg_jitter);

      std_msgs::msg::String msg;
      msg.data = buf;
      pub_diag_summary_->publish(msg);
    }
  }

  // ══════════════════════════════════════════════════════════════════
  //  멤버 변수
  // ══════════════════════════════════════════════════════════════════

  // ── ROS2 파라미터 (생성자에서 초기화, 이후 불변) ──────────────────
  std::string iface_;
  int cycle_hz_{1000}, publish_hz_{50}, max_abs_target_{3000}, cmd_timeout_ms_{0};
  bool auto_enable_{true}, rt_enable_{true};
  int overrun_thresh_us_{200}, rt_priority_{50}, rt_cpu_{-1};
  int wkc_recover_threshold_{50}, heartbeat_timeout_ms_{0}, diag_hz_{10};

  // ── 모터 축 + 로거 + 진단 ─────────────────────────────────────────
  AxisState axis_;                                     // 축 상태 + 더블버퍼
  AsyncLogger logger_;                                 // 비동기 CSV 로거
  SimpleRingBuffer<int32_t, 2048> diag_ring_;          // 진단 dt 수집용

  // ── ROS2 구독자 ──────────────────────────────────────────────────
  rclcpp::Subscription<std_msgs::msg::Int32>::SharedPtr sub_target_, sub_heartbeat_;
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr sub_waveform_, sub_log_cmd_;
  rclcpp::Subscription<epos_interfaces::msg::WaveformCmd>::SharedPtr sub_waveform_v2_;

  // ── ROS2 발행자 ──────────────────────────────────────────────────
  rclcpp::Publisher<std_msgs::msg::Int32>::SharedPtr pub_speed_, pub_stat_, pub_pos_, pub_trq_, pub_wkc_, pub_cycle_dt_, pub_cycle_jitter_, pub_overrun_cnt_, pub_wkc_err_cnt_, pub_error_code_;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr pub_diag_summary_;

  // ── ROS2 서비스 + 타이머 ──────────────────────────────────────────
  rclcpp::Service<std_srvs::srv::SetBool>::SharedPtr srv_enable_;
  rclcpp::Service<std_srvs::srv::Trigger>::SharedPtr srv_fault_reset_;
  rclcpp::TimerBase::SharedPtr pub_timer_, diag_timer_;

  // ── EtherCAT ──────────────────────────────────────────────────────
  char IOmap_[4096]{};           // SOEM IOmap — 모든 슬레이브의 PDO가 여기에 매핑됨
  std::thread control_thread_;   // RT 제어 스레드

  // ── 스레드 간 공유 상태 (atomic) ──────────────────────────────────
  // 규칙: RT 스레드가 쓰고 non-RT가 읽거나, 그 반대인 변수들.
  // relaxed ordering: 최신 값이 수 μs 늦게 보여도 안전한 경우.
  std::atomic<bool> running_{false}, operational_{false}, enable_req_{false}, fault_reset_req_{false};
  std::atomic<int32_t> target_{0}, last_wkc_{0}, cycle_dt_us_{0}, cycle_jitter_us_{0}, cycle_overrun_count_{0}, wkc_error_count_{0};
  std::atomic<int64_t> last_cmd_ns_{0}, last_heartbeat_ns_{0};

  // ── 제어 모드별 목표값 (GUI → RT) ─────────────────────────────────
  std::atomic<int32_t> target_pos_{0};        // 위치 목표 [encoder tick]
  std::atomic<int16_t> target_trq_{0};        // 토크 목표 [‰]
  std::atomic<int8_t>  requested_op_mode_{9}; // 요청된 동작 모드
  std::atomic<int32_t> accel_limit_rpm_s_{5000}; // 가속도 한계 [RPM/s]
  rclcpp::Subscription<std_msgs::msg::Int32>::SharedPtr sub_accel_;

  std::atomic<int32_t> pos_speed_limit_{10000}; // 위치 이동 속도 한계 [Tick/s]

  // ── Fault 처리 ────────────────────────────────────────────────────
  std::atomic<bool>     fault_log_pending_{false};   // RT→non-RT: SDO 읽기 요청
  std::atomic<uint16_t> pending_fault_status_{0};
  int fault_reset_hold_{0};                          // Fault Reset 유지 카운터

  // ── 추가 구독자 ──────────────────────────────────────────────────
  rclcpp::Subscription<std_msgs::msg::Int32>::SharedPtr sub_target_pos_;
  rclcpp::Subscription<std_msgs::msg::Int32>::SharedPtr sub_target_trq_;
  rclcpp::Subscription<std_msgs::msg::Int32>::SharedPtr sub_op_mode_;
  rclcpp::Subscription<std_msgs::msg::Int32>::SharedPtr sub_pos_speed_limit_;

  // ── 로드셀 + 힘 안전 장치 ────────────────────────────────────────
  rclcpp::Subscription<std_msgs::msg::Float32>::SharedPtr sub_force_ch0_;
  rclcpp::Subscription<std_msgs::msg::Float32>::SharedPtr sub_force_ch1_;
  rclcpp::Subscription<std_msgs::msg::Int32>::SharedPtr sub_linear_count_;
  rclcpp::Subscription<std_msgs::msg::Float32>::SharedPtr sub_linear_mm_;
  std::atomic<int32_t> last_force_ch0_mN_{0};  // 최신 CH0 힘 [mN]
  std::atomic<int32_t> last_force_ch1_mN_{0};  // 최신 CH1 힘 [mN]
  std::atomic<int64_t> last_force_ch0_ns_{0};  // 최신 CH0 힘 수신 시각 [ns]
  std::atomic<int64_t> last_force_ch1_ns_{0};  // 최신 CH1 힘 수신 시각 [ns]
  std::atomic<int32_t> last_linear_count_{0};   // 최신 리니어 엔코더 위치 [count]
  std::atomic<int32_t> last_linear_um_{0};      // 최신 리니어 엔코더 위치 [um]
  std::atomic<int64_t> last_linear_ns_{0};      // 최신 리니어 엔코더 수신 시각 [ns]
  std::atomic<int32_t> force_tare_ch0_mN_{0};  // 외부 Tare 오프셋 [mN]
  std::atomic<int32_t> force_tare_ch1_mN_{0};  // 외부 Tare 오프셋 [mN]
  std::atomic<int32_t> force_limit_mN_{0};      // 힘 안전 한계 [mN] (0=비활성, RT 안전)
  std::atomic<bool>    force_limit_tripped_{false}; // 힘 한계 초과 플래그
  std::atomic<int32_t> force_limit_peak_mN_{0};      // RT→non-RT 로그용 피크 힘 [mN]
  std::atomic<int32_t> force_limit_threshold_mN_{0}; // RT→non-RT 로그용 한계 힘 [mN]
  std::atomic<int32_t> force_limit_event_{0};        // 1=초과, -1=해제, 0=이벤트 없음

  // ── 위치 P 게인 (생성자에서 설정, 이후 불변 → RT 읽기 안전) ───────
  double pos_p_gain_{5.0};
  int motor_ticks_per_rev_{2000};

  // ── 힘 제어 (Force Feedback Control) ──────────────────────────────
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr sub_force_ctrl_;
  rclcpp::Subscription<epos_interfaces::msg::ForceCtrlCmd>::SharedPtr sub_force_ctrl_v2_;
  rclcpp::Subscription<std_msgs::msg::Float32>::SharedPtr sub_target_force_;
  std::atomic<bool>    force_ctrl_active_{false};   // 힘 제어 ON/OFF
  std::atomic<int32_t> target_force_mN_{0};         // 목표 힘 [mN]
  std::atomic<int32_t> force_direction_{1};          // +1 또는 -1
  std::atomic<int32_t> force_feedback_mode_{0};      // 0=CH0, 1=CH1, 2=평균, 3=절댓값 큰 채널
  std::atomic<bool>    force_abs_mode_{false};       // true이면 장력 크기(|F|)로 제어
  std::atomic<double>  force_kp_{0.5};              // PID 게인 (GUI에서 실시간 변경)
  std::atomic<double>  force_ki_{0.05};
  std::atomic<double>  force_kd_{0.01};
  std::atomic<int32_t> force_max_rpm_{50};          // 힘 제어 최대 속도 [RPM]
  std::atomic<double>  force_out_alpha_{0.3};       // 출력 IIR 필터 계수
  ForcePID  force_pid_;                              // PID 인스턴스 (RT 스레드 전용)
  // ── Tanh 비선형 제어기 ──────────────────────────────────────────────
  std::atomic<int32_t> force_ctrl_mode_{0};          // 0=PID, 1=Tanh
  std::atomic<double>  force_tanh_sensitivity_{1000.0}; // Tanh 민감도 [mN]
  std::atomic<double>  force_tanh_deadband_{10.0};     // Tanh 데드밴드 [mN]
  ForceTanh force_tanh_;                             // Tanh 인스턴스 (RT 스레드 전용)

  // ── WKC 연속 오류 카운터 ──────────────────────────────────────────
  std::atomic<int32_t> consecutive_wkc_errors_{0};
};


// ══════════════════════════════════════════════════════════════════
//  main — ROS2 노드 실행
// ══════════════════════════════════════════════════════════════════
// rclcpp::spin()은 이 스레드에서 모든 ROS2 콜백을 처리.
// EposNode 생성자에서 RT 스레드와 로거 스레드가 별도로 시작됨.
int main(int argc, char *argv[])
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<EposNode>());
  rclcpp::shutdown();
  return 0;
}
