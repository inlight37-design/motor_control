# Motor GUI 상세 아키텍처 맵

이 문서는 메인 `README.md`를 길게 만들지 않기 위해 분리한 상세 구조도입니다.
GitHub에서 열면 Mermaid 블록다이어그램이 바로 렌더링됩니다.

## 1. 실행 진입점과 환경 준비

```mermaid
flowchart TD
    RootGui["run_gui.py<br/>루트 GUI 런처"] --> Env["app/launcher_env.py<br/>배포 경로/환경변수 설정"]
    RootCli["run_cli.py<br/>루트 CLI 런처"] --> Env
    PackageGui["py/motor_gui_app/run_gui.py<br/>패키지 내부 런처"] --> Env

    Env --> Path["sys.path에 py/ 추가<br/>EPOS_WORKSPACE_DIR<br/>WS_SETUP<br/>EPOS_LOG_DIR<br/>EPOS_DEFAULTS_FILE"]

    Path --> GuiMain["app/main.py<br/>Qt + rclpy 초기화"]
    Path --> CliMain["cli/main.py<br/>argparse CLI"]

    GuiMain --> RosPrep["core/ros_bootstrap.py<br/>prepare_ros_environment()"]
    CliMain --> RosPrep
    RosPrep --> RosEnv["core/ros_environment.py<br/>FastDDS profile<br/>ROS_DOMAIN_ID<br/>localhost discovery"]
    RosPrep --> MsgProbe["core/ros_messages.py<br/>ForceCtrlCmd/WaveformCmd 감지"]

    GuiMain --> Window["ui/main_window.py<br/>MasterWindow"]
    Window --> Runtime["ui/runtime_init.py<br/>런타임 객체 생성/연결"]
    Window --> Layout["ui/window_layout.py<br/>패널 배치"]
```

## 2. Python GUI 코드 맵

```mermaid
flowchart LR
    subgraph UI["ui/"]
        MainWindow["main_window.py<br/>MasterWindow"]
        RuntimeInit["runtime_init.py<br/>threads/devices/session"]
        Layout["window_layout.py<br/>패널 조립"]
        State["window_state.py<br/>화면 상태"]
        Widgets["widget_groups.py<br/>위젯 묶음 dataclass"]
        GraphUpdate["graph_update.py<br/>그래프 갱신"]
        StatusUpdate["status_update.py<br/>상태 표시 갱신"]
        RuntimeComponents["runtime_components.py<br/>RuntimeThreads/DeviceReaders"]
        SessionProps["session_properties.py<br/>호환 property"]
    end

    subgraph Panels["panels/ 화면 생성"]
        TopPanel["top_status_panel.py"]
        MotionPanel["motion_control_panel.py"]
        ForcePanel["force_control_panel.py"]
        LoadPanel["load_cell_panel.py"]
        HystPanel["hysteresis_panel.py"]
        ScriptPanel["script_logging_panel.py"]
        GraphPanel["graph_panel.py"]
        LogPanel["log_viewer_panel.py"]
        StopPanel["emergency_stop_panel.py"]
        VisibilityPanel["panel_visibility_bar.py"]
    end

    subgraph Actions["actions/ 사용자 동작"]
        SystemActions["system_actions.py"]
        MotionActions["motion_actions.py"]
        ForceActions["force_control_actions.py"]
        LoadActions["load_cell_actions.py"]
        LinearActions["linear_encoder_actions.py"]
        HystActions["hysteresis_actions.py"]
        WaveActions["waveform_actions.py"]
        ScriptActions["script_actions.py"]
        LoggingActions["logging_actions.py"]
    end

    subgraph Core["core/ 공유 제어"]
        Client["control_client.py<br/>GUI/CLI 공용 API"]
        Commander["commander.py<br/>200 Hz 명령 발행"]
        Monitor["monitor.py<br/>피드백 구독"]
        NodeRunner["node_runner.py<br/>C++ 노드 실행/종료"]
        Builders["command_builders.py<br/>v2 msg 또는 v1 string"]
        Topics["topics.py"]
        Config["config.py<br/>defaults.json loader"]
        Feedback["feedback_state.py"]
        Session["session/<br/>MotorSession/StateView/Flags"]
        Experiments["experiments/<br/>HysteresisExperiment"]
        IIR["iir_filter.py<br/>1차 IIR LPF 공유"]
        Units["motor_units.py<br/>tick/mm 변환 공유"]
        LCCal["load_cell_calibration.py<br/>캘리브레이션 JSON 해석"]
        LEMath["linear_encoder_math.py<br/>count/mm 환산"]
    end

    subgraph Devices["devices/ GUI 내장 장치"]
        LoadDevice["load_cell.py"]
        LinearDevice["linear_encoder.py"]
    end

    subgraph Nodes["nodes/ 독립 센서 노드"]
        LoadNode["load_cell_node.py"]
        LinearNode["linear_encoder_node.py"]
    end

    MainWindow --> RuntimeInit
    MainWindow --> Layout
    MainWindow --> State
    Layout --> Panels
    Panels --> Actions
    Actions --> Client
    Actions --> Devices
    RuntimeInit --> RuntimeComponents
    RuntimeInit --> Commander
    RuntimeInit --> Monitor
    RuntimeInit --> NodeRunner
    RuntimeInit --> Session
    Client --> Builders
    Client --> Commander
    Client --> Experiments
    Commander --> Topics
    Monitor --> Topics
    Monitor --> Feedback
    Devices --> Commander
    Devices --> IIR
    Devices --> LCCal
    Devices --> LEMath
    Nodes --> Topics
    Nodes --> IIR
    Nodes --> LCCal
    Nodes --> LEMath
    Actions --> Units
    GraphUpdate --> Session
    StatusUpdate --> Session
```

## 3. 런타임 객체 관계

```mermaid
flowchart TD
    Window["MasterWindow<br/>ui_state<br/>runtime_threads<br/>device_readers<br/>session<br/>graph/status/log timers"]

    RuntimeThreads["RuntimeThreads<br/>node_runner<br/>commander<br/>monitor"]
    DeviceReaders["DeviceReaders<br/>load_cell<br/>linear_encoder"]
    MotorSession["MotorSession<br/>control<br/>state<br/>flags<br/>hysteresis"]

    NodeRunner["NodeRunner<br/>C++ process start/stop"]
    CommandThread["CommandThread<br/>200 Hz loop<br/>command queues<br/>heartbeat<br/>sensor feedback<br/>soft limit"]
    MonitorThread["MonitorThread<br/>ROS2 spin_once<br/>feedback_state update<br/>fault auto reset"]

    LoadCellReader["LoadCellReader"]
    LinearEncoderReader["LinearEncoderReader"]

    ControlClient["ControlClient"]
    StateView["StateView"]
    SessionFlags["SessionFlags"]
    HysteresisExperiment["HysteresisExperiment"]

    Window --> RuntimeThreads
    Window --> DeviceReaders
    Window --> MotorSession
    RuntimeThreads --> NodeRunner
    RuntimeThreads --> CommandThread
    RuntimeThreads --> MonitorThread
    DeviceReaders --> LoadCellReader
    DeviceReaders --> LinearEncoderReader
    MotorSession --> ControlClient
    MotorSession --> StateView
    MotorSession --> SessionFlags
    MotorSession --> HysteresisExperiment
```

## 4. 동작별 명령 경로

| 사용자 동작 | GUI 파일 | Action | 공용 API | CommandThread/토픽 | C++ 수신 |
| --- | --- | --- | --- | --- | --- |
| 모터 노드 시작/종료 | `top_status_panel.py` | `system_actions.toggle_motor` | - | `NodeRunner.start/stop` (sudo + chrt -f 50) | `epos_motor_node` main |
| 수동 RPM | `motion_control_panel.py` | `motion_actions.send_manual_rpm` | `ControlClient.set_manual_rpm` | `/target_speed` (`Int32`, Reliable) | `target_` atomic |
| 위치 이동 | `motion_control_panel.py` | `motion_actions.send_manual_pos` | `move_to_position_ticks` | `/target_position`, `/pos_speed_limit` | `target_pos_`, `pos_speed_limit_` |
| 수동 토크 | `motion_control_panel.py` | `motion_actions.send_manual_trq` | `set_manual_torque` | `/target_torque` (‰ rated torque) | `target_trq_` |
| 모드 전환 (CSV/CSP/CST) | `motion_control_panel.py` | `motion_actions.change_op_mode` | `set_operation_mode` | `/op_mode_cmd` (8/9/10) | `requested_op_mode_` |
| 파형 시작/정지 | `motion_control_panel.py` | `waveform_actions` | `start_waveform / stop_waveform` | `/epos/waveform_cmd_v2` (v2) / `/epos/waveform_cmd` (v1) | `WaveformConfig` 더블버퍼 |
| 힘 제어 시작/정지 | `force_control_panel.py` | `force_control_actions` | `start_force_control / stop_force_control` | `/epos/force_ctrl_cmd_v2` (v2) / `/epos/force_ctrl_cmd` (v1) | `force_ctrl_active_` + 게인 atomic |
| 힘 제어 PID/Tanh 모드 | `force_control_panel.py` | `force_control_actions` | `apply_force_pid / apply_force_tanh` | 위 토픽 (ACTION_SET_PID / ACTION_SET_TANH) | `force_ctrl_mode_` atomic |
| 로드셀 tare/단위/한계 | `load_cell_panel.py` | `load_cell_actions` | `set_force_limit`, `set_force_tare_offset`, `sync_force_tare_offsets` | `/load_cell/*` 발행 + force ctrl cmd | `force_limit_mN_`, `force_tare_chN_mN_` |
| 리니어 엔코더 연결/zero | `motion_control_panel.py` | `linear_encoder_actions` | `LinearEncoderReader.zero` (로컬) | `/linear_encoder/position_count`, `/linear_encoder/position_mm` 발행 | `last_linear_count_`, `last_linear_um_` (CSV 로그 컬럼) |
| 스크립트 실행 | `script_logging_panel.py` | `script_actions` | `start_motion_script / stop_motion_script` | `CommandThread`가 200 Hz로 `target_rpm(t,state)` 평가 → `/target_speed` | `target_` atomic |
| 히스테리시스 실험 | `hysteresis_panel.py` | `hysteresis_actions` | `HysteresisExperiment.start / abort` | `/epos/waveform_cmd_v2` (ACTION_START_HYST_VELOCITY/POSITION) | `make_hyst_velocity_plan` + AsyncLogger window |
| CSV 로깅 (수동) | `script_logging_panel.py` | `logging_actions` | `start_csv_logging / stop_csv_logging` | `/epos/log_cmd` (`"start <path>"` / `"stop"`) | `AsyncLogger.start/stop_logging` |
| Heartbeat (자동) | - | - | - | `CommandThread`가 10 Hz로 `/epos/heartbeat` 발행 | `last_heartbeat_ns_` (timeout 시 정지) |
| Fault 자동 복구 | `top_status_panel.py` | (체크박스) | `MonitorThread.set_auto_fault_reset` | `/epos_motor_node/fault_reset` 서비스 호출 | `fault_reset_req_` atomic |

## 5. CommandThread 200 Hz 루프

```mermaid
flowchart TD
    Start([loop tick<br/>target_dt = 1/cmd_hz]) --> Heartbeat{"_publish_heartbeat_if_due<br/>(10 Hz)"}
    Heartbeat -->|due| PubHb["publish<br/>/epos/heartbeat"]
    Heartbeat -->|skip| LCDue
    PubHb --> LCDue

    LCDue{"_publish_load_cell_feedback<br/>(200 Hz)"} -->|due| PubLC["publish<br/>/load_cell/ch0_N<br/>/load_cell/ch1_N<br/>+ _warn_if_external_<br/>sensor_publisher"]
    LCDue -->|skip| LEDue
    PubLC --> LEDue

    LEDue{"_publish_linear_encoder_feedback<br/>(100 Hz)"} -->|due| PubLE["publish<br/>/linear_encoder/position_count<br/>/linear_encoder/position_mm<br/>+ _warn_if_external_<br/>sensor_publisher"]
    LEDue -->|skip| Queues
    PubLE --> Queues

    Queues["_drain_command_queues<br/>waveform / log / force_ctrl<br/>v2 msg 우선, fallback v1 string"] --> Mode{"_current_mode()"}

    Mode -->|waveform| Sleep["_sleep_until_next_cycle<br/>(C++ RT가 파형 생성, Python은 대기)"]
    Mode -->|manual / script| Compute["_compute_mode_target_rpm<br/>script면 MotionScript.func(t,state) 평가<br/>manual이면 _manual_target_rpm 사용"]
    Compute --> Soft["_apply_soft_limit<br/>(GUI 내장 LoadCellReader 연결 시에만)"]
    Soft --> PubTarget["publish /target_speed<br/>(int(cmd_rpm))"]
    PubTarget --> Sleep
```

소프트 리미트는 **GUI 내장 `LoadCellReader`가 직접 USB로 연결된 경우에만** 동작합니다.
외부 `load_cell_node.py`만 켜져 있고 GUI 내장 리더는 연결하지 않은 경우 Python soft limit은
적용되지 않고, C++ RT 루프의 `check_force_limit` 하드 컷오프만 작동합니다.

## 6. MonitorThread 피드백 경로

```mermaid
flowchart LR
    CppPub["C++ publishers<br/>50 Hz feedback<br/>10 Hz diagnostics"] --> Monitor["MonitorThread<br/>rclpy.spin_once"]

    Monitor --> MotorFb["MotorFeedback<br/>target_rpm, status_word, error_code<br/>actual_position_ticks<br/>actual_torque_permille<br/>memorized_error_*"]
    Monitor --> RtDiag["RealtimeDiagnostics<br/>jitter_us, overrun_count<br/>wkc_error_count<br/>dt_mean_us, jitter_mean_us<br/>jitter_max_us<br/>(diag_summary JSON)"]
    Monitor --> LoadFb["LoadCellFeedback<br/>forces_n[ch], safety_tripped<br/>last_recv_t (외부 토픽 신선도)"]
    Monitor --> LinearFb["LinearEncoderFeedback<br/>count, mm, last_recv_t"]

    MotorFb --> StateView["StateView"]
    RtDiag --> StateView
    LoadFb --> StateView
    LinearFb --> StateView

    StateView --> Status["ui/status_update.py"]
    StateView --> Graph["ui/graph_update.py"]
    Monitor --> Fault["fault auto reset<br/>if enabled"]
```

## 7. C++ 제어 노드 내부 맵

C++ 노드 안에는 세 종류의 실행 스레드가 있습니다.
**(a) rclcpp::spin 스레드** — ROS2 콜백 처리, non-RT.
**(b) RT 제어 스레드** — `control_loop_rt()`, 1 kHz, SCHED_FIFO + mlockall.
**(c) AsyncLogger 스레드** — 10 ms 간격 CSV flush.

```mermaid
flowchart TD
    Node["src/epos_motor_node.cpp<br/>EposNode"] --> Params["ROS params<br/>iface, max_abs_target,<br/>rt_cpu, force_kp/ki/kd,<br/>cmd_timeout_ms,<br/>heartbeat_timeout_ms"]
    Node --> Subs["ROS subscribers<br/>(rclcpp::spin 스레드)"]
    Node --> Pubs["ROS publishers<br/>publish_feedback 50 Hz<br/>publish_diag_summary 10 Hz<br/>(WallTimer)"]
    Node --> Ethercat["ethercat/<br/>epos_setup PDO mapping<br/>CiA402 state machine"]
    Node --> RtThread["control_loop_rt()<br/>1 kHz<br/>clock_nanosleep TIMER_ABSTIME"]
    Node --> Logger["AsyncLogger<br/>process_loop()<br/>10 ms drain<br/>(별도 스레드)"]

    Subs --> Parse["commands/command_parsing.hpp<br/>force_command_from_msg (v2)<br/>parse_force_ctrl (v1)<br/>waveform_command_from_msg/string"]
    Parse --> Atomic[("atomic 상태<br/>target_velocity / target_position /<br/>target_torque / requested_op_mode /<br/>force_kp/ki/kd / force_max_rpm /<br/>force_limit_mN / WaveformConfig 더블버퍼<br/>last_force_chN_mN / last_heartbeat_ns ...")]
    Atomic --> RtThread

    RtThread --> Control["control/<br/>velocity_control<br/>position_control (CSP→CSV 변환)<br/>force_control (PID + Tanh)<br/>slew_rate_limiter"]
    RtThread --> Wave["waveform/<br/>waveform_generator<br/>hysteresis_plan"]
    RtThread --> Safety["safety/<br/>force_limit_guard (hard cutoff)<br/>output_safety_guard<br/>(fault/timeout/heartbeat/max_rpm)"]
    RtThread --> Units["util/motor_units.hpp<br/>util/realtime_config.hpp<br/>util/simple_ring_buffer.hpp"]
    RtThread --> Ethercat
    RtThread -->|push_record<br/>SPSC ring buffer| Logger

    Ethercat <-->|EtherCAT PDO 1 ms| Drive["EPOS4 drive"]
    RtThread -->|atomic store| Pubs
    Logger --> Csv["logs/*.csv"]
```

## 8. C++ 1 ms RT 루프 상세

EPOS4의 CSP 모드(클럭 sync) 대신 마스터 측 P 제어로 위치를 CSV(속도) 명령으로 변환합니다.
위치 사인파(`POSITION_SINE`)는 자동으로 op_mode=8(CSP) 강제, 다른 파형은 op_mode=9(CSV) 강제.

```mermaid
flowchart TD
    Tick([clock_nanosleep<br/>TIMER_ABSTIME<br/>period 1 ms]) --> PdoRead["EtherCAT<br/>ec_send_processdata +<br/>ec_receive_processdata"]
    PdoRead --> Wkc{"WKC > 0?"}
    Wkc -->|no| Skip["wkc_error_count++<br/>consecutive_wkc_errors++<br/>(임계 초과 시 OP 재진입)"]
    Wkc -->|yes| Read["InPDO 읽기<br/>status_word / actual_position /<br/>actual_velocity / actual_torque"]

    Read --> Fault{"cia402::is_fault<br/>(status & 0x0008)"}
    Fault -->|yes,edge| FaultLog["fault_log_pending = true<br/>(non-RT가 SDO로<br/>error_code 0x603F 읽음)<br/>target = 0"]
    Fault -->|no| WaveCheck{"WaveformConfig<br/>type 확인<br/>(더블버퍼)"}
    FaultLog --> Mode

    WaveCheck -->|POSITION_SINE| ForcePos["op_mode = 8 강제"]
    WaveCheck -->|기타 파형| ForceCsv["op_mode = 9 강제"]
    WaveCheck -->|NONE| Mode
    ForcePos --> Mode
    ForceCsv --> Mode

    Mode{op_mode}
    Mode -->|9 CSV velocity| Velocity["compute_velocity_csv_command<br/>+ slew_rate_limiter<br/>(파형이면 waveform::compute,<br/>아니면 manual target_rpm)"]
    Mode -->|8 CSP position| Position["compute_position_csv_command<br/>P-gain × (target_pos - actual_pos)<br/>→ velocity target (CSV로 송신)"]
    Mode -->|10 CST torque| Torque["target_torque pass-through"]

    Velocity --> ForceCheck{"force_ctrl_active<br/>(atomic acquire)"}
    Position --> ForceCheck
    Torque --> ForceCheck

    ForceCheck -->|yes| ForceCtrl["select_force_feedback<br/>(ch0/ch1/avg/max_abs)<br/>+ compute_force_control_command<br/>(PID 또는 Tanh)<br/>+ output_alpha LPF<br/>→ 속도 출력 덮어쓰기"]
    ForceCheck -->|no| Limit
    ForceCtrl --> Limit["check_force_limit<br/>(stale 500 ms,<br/>peak > limit_mN → trip)"]

    Limit --> Safety["apply_output_safety<br/>is_fault → 0<br/>!enable_desired → 0<br/>force_limit_tripped → 0<br/>cmd_timeout 초과 → 0<br/>heartbeat_timeout 초과 → 0<br/>max_abs_rpm clamp"]
    Safety --> Cw["cia402::next_control_word<br/>(SHUTDOWN/SWITCH_ON/<br/>ENABLE_OPERATION/<br/>FAULT_RESET 20ms hold)"]
    Cw --> PdoWrite["OutPDO 쓰기<br/>control_word /<br/>target_velocity /<br/>target_position /<br/>target_torque /<br/>mode_of_operation"]
    PdoWrite --> Log["AsyncLogger.push_record<br/>(SPSC ring buffer,<br/>non-blocking, lock-free)"]
    Log --> Tick
    Skip --> Tick
```

## 9. 센서와 로그 데이터 경로

같은 ROS2 토픽(`/load_cell/ch*_N`, `/linear_encoder/position_*`)에 두 가지 입력 경로가 있습니다.
실험 중에는 한쪽만 켜야 데이터가 섞이지 않으며, 동시에 켜지면 `CommandThread`가 GUI 로그에 경고를 띄웁니다.

```mermaid
flowchart LR
    subgraph SharedCalc["core/ 공유 계산"]
        IIR["iir_filter.py<br/>1차 IIR LPF"]
        LCCal["load_cell_calibration.py<br/>scale_g / offset_g<br/>채널 매핑"]
        LEMath["linear_encoder_math.py<br/>raw → count → mm"]
    end

    subgraph GuiSensor["경로 A · GUI 내장 (Python 프로세스)"]
        LCDev["devices/load_cell.py<br/>Phidget VoltageRatioInput<br/>+ Tare 관리"]
        LEDev["devices/linear_encoder.py<br/>Phidget Encoder"]
        LCDev --> IIR
        LCDev --> LCCal
        LEDev --> LEMath
        LCDev -->|200 Hz| Cmd["CommandThread<br/>_publish_load_cell_feedback<br/>_publish_linear_encoder_feedback"]
        LEDev -->|100 Hz| Cmd
    end

    subgraph StandaloneNodes["경로 B · 독립 ROS2 노드"]
        LCNode["nodes/load_cell_node.py<br/>(publish_hz 파라미터)"]
        LENode["nodes/linear_encoder_node.py<br/>(publish_hz 파라미터)"]
        LCNode --> IIR
        LCNode --> LCCal
        LENode --> LEMath
    end

    Cmd --> LCTopic["/load_cell/ch0_N<br/>/load_cell/ch1_N"]
    Cmd --> LETopic["/linear_encoder/position_count<br/>/linear_encoder/position_mm"]
    LCNode --> LCTopic
    LENode --> LETopic

    LCTopic --> Cpp["C++ epos_motor_node<br/>force_pid 입력<br/>force_limit_guard<br/>AsyncLogger CSV 컬럼"]
    LETopic --> Cpp
    LCTopic --> Monitor["MonitorThread<br/>LoadCellFeedback<br/>LinearEncoderFeedback<br/>(외부 토픽 표시용)"]
    LETopic --> Monitor

    Cpp --> Csv["logs/*.csv<br/>1 kHz RT 로그"]
    Cpp --> Feedback["ROS2 feedback topics<br/>/measured_speed, /epos/status_word ...<br/>50 Hz publish + 10 Hz diag"]
    Feedback --> Monitor
    Monitor --> Ui["ui/status_update.py<br/>ui/graph_update.py"]
```

## 10. 새 기능을 추가할 때 보는 순서

| 추가 작업 | 수정 후보 |
| --- | --- |
| 새 버튼/입력 추가 | `panels/*_panel.py`에서 위젯 생성, `actions/*_actions.py`에서 동작 구현 |
| 새 제어 명령 추가 | `core/control_client.py`에 고수준 메서드 추가, `core/command_builders.py`에 메시지/문자열 생성 추가 |
| 새 ROS2 토픽 추가 | `core/topics.py`, `core/commander.py` 또는 `core/monitor.py`, C++ subscriber/publisher |
| 새 센서 추가 | `devices/` 직접 리더, 필요 시 `nodes/` 독립 노드, 공통 계산은 `core/` |
| 새 실험 플로우 추가 | `core/experiments/`에 상태 흐름, GUI action/CLI에서 같은 객체 재사용 |
| 새 RT 제어 로직 추가 | `cpp/src/epos_control/include/control/`에 계산 분리, `epos_motor_node.cpp` RT 루프에서 호출 |
| 새 안전 조건 추가 | `include/safety/output_safety_guard.hpp` 또는 별도 guard 헤더 |
| 새 로그 컬럼 추가 | `include/logging/async_logger.hpp`, `epos_motor_node.cpp`의 record push 지점 |
