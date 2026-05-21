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
    Nodes --> Topics
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
| 모터 노드 시작/종료 | `top_status_panel.py` | `system_actions.py` | - | `NodeRunner`가 `epos_motor_node` subprocess 실행 | `epos_motor_node.cpp` main |
| 수동 RPM | `motion_control_panel.py` | `motion_actions.py` | `ControlClient.set_manual_rpm()` | `/target_speed` | target atomic |
| 위치 이동 | `motion_control_panel.py` | `motion_actions.py` | `move_to_position_ticks()` | `/target_position`, `/pos_speed_limit` | position control |
| 수동 토크 | `motion_control_panel.py` | `motion_actions.py` | `set_manual_torque()` | `/target_torque` | torque pass-through |
| 파형 시작/정지 | `motion_control_panel.py` | `waveform_actions.py` | `start_waveform()` | `/epos/waveform_cmd_v2` 또는 v1 | waveform double buffer |
| 힘 제어 시작/정지 | `force_control_panel.py` | `force_control_actions.py` | `start_force_control()` | `/epos/force_ctrl_cmd_v2` 또는 v1 | force PID/Tanh |
| 로드셀 tare/단위/한계 | `load_cell_panel.py` | `load_cell_actions.py` | `set_force_limit()`, tare sync | `/load_cell/*`, force limit cmd | force feedback/limit |
| 리니어 엔코더 연결/zero | `motion_control_panel.py` | `linear_encoder_actions.py` | - | `/linear_encoder/*` | CSV/log/후속 위치 분석 |
| 스크립트 실행 | `script_logging_panel.py` | `script_actions.py` | `start_motion_script()` | `CommandThread`가 200 Hz 평가 | `/target_speed` |
| 히스테리시스 실험 | `hysteresis_panel.py` | `hysteresis_actions.py` | `HysteresisExperiment` | waveform + log command | RT waveform + CSV |
| CSV 로깅 | `script_logging_panel.py` | `logging_actions.py` | `start_logging()` | `/epos/log_cmd` | `AsyncLogger` |

## 5. CommandThread 200 Hz 루프

```mermaid
flowchart TD
    Start([loop tick<br/>target_dt = 1/cmd_hz]) --> Heartbeat{heartbeat due?}
    Heartbeat -->|yes| PubHb["publish /epos/heartbeat"]
    Heartbeat -->|no| Sensor
    PubHb --> Sensor

    Sensor{sensor publish due?} -->|load cell| PubLC["publish /load_cell/ch0_N<br/>/load_cell/ch1_N"]
    Sensor -->|linear encoder| PubLE["publish /linear_encoder/count<br/>/linear_encoder/position_mm"]
    Sensor -->|no| Queues
    PubLC --> Warn["external publisher warning<br/>if duplicate topic publishers"]
    PubLE --> Warn
    Warn --> Queues

    Queues["drain command queues"] --> WaveQ["waveform queue<br/>v2 msg or v1 string"]
    Queues --> LogQ["log command queue"]
    Queues --> ForceQ["force control queue<br/>v2 msg or v1 string"]

    WaveQ --> Mode{mode}
    LogQ --> Mode
    ForceQ --> Mode
    Mode -->|waveform| Sleep["sleep until next tick"]
    Mode -->|manual/script| Target["compute target rpm"]
    Target --> Script{script mode?}
    Script -->|yes| Eval["evaluate MotionScript.func(t,state)"]
    Script -->|no| Manual["use manual target rpm"]
    Eval --> Soft["apply Python soft limit"]
    Manual --> Soft
    Soft --> PubTarget["publish /target_speed"]
    PubTarget --> Sleep
```

## 6. MonitorThread 피드백 경로

```mermaid
flowchart LR
    CppPub["C++ publishers<br/>50 Hz feedback<br/>10 Hz diagnostics"] --> Monitor["MonitorThread<br/>rclpy.spin_once"]

    Monitor --> MotorFb["MotorFeedback<br/>target/actual/status/error"]
    Monitor --> RtDiag["RealtimeDiagnostics<br/>loop_us/wkc/overruns"]
    Monitor --> LoadFb["LoadCellFeedback<br/>force_N/safety"]
    Monitor --> LinearFb["LinearEncoderFeedback<br/>count/mm"]

    MotorFb --> StateView["StateView"]
    RtDiag --> StateView
    LoadFb --> StateView
    LinearFb --> StateView

    StateView --> Status["ui/status_update.py"]
    StateView --> Graph["ui/graph_update.py"]
    Monitor --> Fault["fault auto reset<br/>if enabled"]
```

## 7. C++ 제어 노드 내부 맵

```mermaid
flowchart TD
    Node["src/epos_motor_node.cpp<br/>EposNode"] --> Params["ROS params<br/>iface, max rpm, rt cpu,<br/>force gains, timeout"]
    Node --> Subs["ROS subscribers"]
    Node --> Pubs["ROS publishers"]
    Node --> Ethercat["ethercat/<br/>EPOS setup, PDO, CiA402"]
    Node --> RtThread["control_loop_rt()<br/>1 kHz"]
    Node --> Logger["logging/async_logger.hpp<br/>SPSC ring buffer"]

    Subs --> Parse["commands/command_parsing.hpp<br/>v2 msg + v1 string"]
    Parse --> Atomic["atomic state<br/>target/mode/force/waveform/log"]
    Atomic --> RtThread

    RtThread --> Control["control/<br/>velocity, position,<br/>force PID/Tanh,<br/>slew limiter"]
    RtThread --> Wave["waveform/<br/>waveform_generator<br/>hysteresis_plan"]
    RtThread --> Safety["safety/<br/>force_limit_guard<br/>output_safety_guard"]
    RtThread --> Units["util/motor_units.hpp"]
    RtThread --> Ethercat
    RtThread --> Logger

    Ethercat --> Drive["EPOS4 drive"]
    Drive --> Ethercat
    RtThread --> Pubs
```

## 8. C++ 1 ms RT 루프 상세

```mermaid
flowchart TD
    Tick([clock_nanosleep<br/>1 ms period]) --> PdoRead["EtherCAT PDO read"]
    PdoRead --> Wkc{WKC ok?}
    Wkc -->|no| Skip["skip control<br/>recover counter"]
    Wkc -->|yes| Read["read status/pos/vel/trq"]

    Read --> Fault{EPOS fault?}
    Fault -->|yes| Reset["fault reset sequence<br/>target = 0"]
    Fault -->|no| Mode{op_mode}

    Mode -->|CSV velocity| Velocity["velocity_control<br/>slew_rate_limiter"]
    Mode -->|CSP position| Position["position_control<br/>P gain -> velocity target"]
    Mode -->|CST torque| Torque["torque pass-through"]

    Velocity --> Wave{waveform active?}
    Position --> Wave
    Torque --> Wave

    Wave -->|yes| Waveform["waveform_generator<br/>sine/square/triangle/chirp/hyst"]
    Wave -->|no| Force
    Waveform --> Force{force control active?}

    Force -->|yes| ForceCtrl["force_control<br/>PID or Tanh<br/>output LPF"]
    Force -->|no| Limit
    ForceCtrl --> Limit["force_limit_guard<br/>hard force limit"]

    Limit --> Safety["output_safety_guard<br/>fault/disable/cmd timeout<br/>heartbeat/max rpm"]
    Safety --> Cw["CiA402 control_word<br/>target output"]
    Cw --> PdoWrite["EtherCAT PDO write"]
    PdoWrite --> Log["push CSV record<br/>non-blocking"]
    Log --> Tick
    Reset --> PdoWrite
    Skip --> Tick
```

## 9. 센서와 로그 데이터 경로

```mermaid
flowchart LR
    subgraph GuiSensor["GUI 내장 센서 경로"]
        LCDev["devices/load_cell.py<br/>Phidget VoltageRatioInput"] --> LCCalc["core/load_cell_calibration.py<br/>core/iir_filter.py"]
        LEDev["devices/linear_encoder.py<br/>Phidget Encoder"] --> LECalc["core/linear_encoder_math.py"]
        LCCalc --> Cmd["CommandThread"]
        LECalc --> Cmd
    end

    subgraph StandaloneNodes["독립 센서 노드 경로"]
        LCNode["nodes/load_cell_node.py"] --> LCTopic["/load_cell/ch*_N"]
        LENode["nodes/linear_encoder_node.py"] --> LETopic["/linear_encoder/*"]
    end

    Cmd --> LCTopic
    Cmd --> LETopic
    LCTopic --> Cpp["C++ force feedback / log"]
    LETopic --> Cpp
    Cpp --> Csv["logs/*.csv"]
    Cpp --> Feedback["ROS2 feedback topics"]
    Feedback --> Monitor["MonitorThread"]
    Monitor --> Ui["status + graph"]
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
