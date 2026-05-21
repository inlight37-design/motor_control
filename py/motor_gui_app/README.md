# motor_gui_app

`Motor_gui_jh`의 Python GUI 패키지입니다. PyQt5 화면, ROS2 명령/모니터 스레드, 로드셀/리니어 엔코더 리더, 독립 실행 센서 노드를 한곳에 묶어 둔 구조입니다.

이 README는 `py/motor_gui_app` 내부 구조를 보는 용도입니다. 전체 설치, C++ 빌드, 실행 준비는 루트의 `../../README.md`를 먼저 보면 됩니다.

## Python 의존성

`py/requirements.txt`에는 GUI와 도구 실행에 필요한 pip 패키지만 들어 있습니다. ROS2의 `rclpy`, `std_msgs`, `std_srvs`는 pip가 아니라 ROS2 설치와 `setup.bash` source가 필요합니다.

```bash
cd /home/user/K-FLEX/TS_vivration_project/Motor_gui_jh/py
python3 -m pip install -r requirements.txt
```

## 실행

가장 권장하는 실행 방법은 `Motor_gui_jh` 루트 런처를 쓰는 것입니다. 이 방식은 C++ 워크스페이스 경로, 로그 폴더, 기본 설정 파일 경로를 자동으로 맞춥니다.

```bash
cd /home/user/K-FLEX/TS_vivration_project/Motor_gui_jh
python3 run_gui.py
```

CLI로 상태 확인/간단한 수동 명령을 보낼 수도 있습니다. GUI를 띄우지 않지만 `core/control_client.py`를 통해 같은 제어 명령 경로를 사용합니다.

```bash
cd /home/user/K-FLEX/TS_vivration_project/Motor_gui_jh
python3 run_cli.py
python3 run_cli.py --help
python3 run_cli.py config
python3 run_cli.py status
python3 run_cli.py stop
python3 run_cli.py rpm 50 --seconds 1
python3 run_cli.py position 4000 --speed 500 --seconds 2
python3 run_cli.py hyst-velocity --freq 1 --amp-rpm 50 --settle-cycles 1 --record-cycles 3
```

`python3 run_cli.py`처럼 인자 없이 실행하면 `motor>` 프롬프트가 뜹니다. 이때는 GUI와 비슷하게 command/monitor 세션을 계속 유지하므로, 그 안에서 여러 명령을 이어서 입력할 수 있습니다. 자동화나 기록용으로는 `python3 run_cli.py status`처럼 한 줄 명령을 쓰면 됩니다.

Python 패키지 폴더 기준으로 직접 실행할 수도 있습니다.

```bash
cd /home/user/K-FLEX/TS_vivration_project/Motor_gui_jh/py
python3 -m motor_gui_app
```

또는 앱 폴더 안의 런처를 바로 실행합니다.

```bash
cd /home/user/K-FLEX/TS_vivration_project/Motor_gui_jh/py/motor_gui_app
python3 run_gui.py
```

앱 폴더 런처만 직접 쓸 때 C++ 노드 위치를 별도로 지정해야 하면 아래 환경변수를 사용할 수 있습니다.

```bash
export EPOS_WORKSPACE_DIR=/home/user/K-FLEX/TS_vivration_project/Motor_gui_jh/cpp
export WS_SETUP=/home/user/K-FLEX/TS_vivration_project/Motor_gui_jh/cpp/install/setup.bash
export EPOS_LOG_DIR=/home/user/K-FLEX/TS_vivration_project/Motor_gui_jh/logs
export EPOS_DEFAULTS_FILE=/home/user/K-FLEX/TS_vivration_project/Motor_gui_jh/py/motor_gui_app/config/defaults.json
```

## 코드 흐름

Python GUI의 시작 흐름은 아래처럼 한 방향으로 이어집니다.

```text
Motor_gui_jh/run_gui.py
  -> py/motor_gui_app/app/main.py
    -> ui/main_window.py
      -> ui/runtime_init.py
      -> ui/window_layout.py
      -> panels/*
      -> core/control_client.py
      -> core/session/*
      -> core/commander.py, core/monitor.py
```

CLI의 시작 흐름은 더 짧습니다.

```text
Motor_gui_jh/run_cli.py
  -> py/motor_gui_app/cli/main.py
    -> core/session/motor_session.py
      -> core/control_client.py, core/session/state_view.py
        -> core/commander.py, core/monitor.py
        -> ROS2 topics
```

각 파일의 역할은 이렇습니다.

- `Motor_gui_jh/run_gui.py`: 배포 폴더 기준 런처. `app/launcher_env.py`를 통해 `EPOS_WORKSPACE_DIR`, `WS_SETUP`, `EPOS_LOG_DIR`, `EPOS_DEFAULTS_FILE`을 잡습니다.
- `Motor_gui_jh/run_cli.py`: 배포 폴더 기준 CLI 런처. 같은 환경 설정을 공유하고, GUI 없이 `config`, `status`, `stop`, `rpm`, `position` 명령을 실행합니다.
- `app/main.py`: `QApplication`, `rclpy`, `MasterWindow`를 만들고 이벤트 루프를 시작합니다.
- `ui/main_window.py`: GUI 중심 클래스입니다. 세션 상태, 그래프/로그 flush, 종료 처리처럼 창 생명주기에 가까운 일만 남기고, 버튼 동작은 `panels/`에서 `actions/`로 직접 연결합니다.
- `ui/runtime_init.py`: 런타임 상태, 모터 통신 스레드, 모니터 스레드, 센서 리더, 타이머, signal 연결을 초기화합니다.
- `ui/window_layout.py`: 화면에 보이는 패널과 그래프를 조립합니다.
- `panels/*`: 버튼, 스핀박스, 라벨 같은 PyQt 위젯을 생성합니다.
- `core/control_client.py`: UI와 CLI가 함께 쓸 수 있는 고수준 제어 API입니다. 수동 RPM/위치/토크, 힘 제어, 파형 제어, 히스테리시스 예약, CSV 로깅처럼 C++ 노드로 보내는 명령 순서를 이곳에 모읍니다.
- `core/session/*`: `ControlClient`, 읽기 전용 `StateView`, 실행 상태 `SessionFlags`를 묶어 GUI와 CLI가 같은 세션 모델을 쓰게 합니다.

다만 실행이 시작된 뒤에는 C++처럼 한 줄짜리 메인 루프를 계속 따라가는 구조가 아닙니다. Python GUI는 이벤트 기반입니다.

```text
사용자 버튼/스핀박스 조작
  -> panels/*
    -> actions/*
    -> core/control_client.py
      -> core/commander.py
        -> ROS2 토픽 발행

C++ 모터 노드 피드백 토픽
  -> core/monitor.py
    -> core/session/state_view.py
    -> ui/status_update.py, ui/graph_update.py

로드셀/리니어 엔코더 샘플
  -> devices/* 또는 nodes/*
    -> GUI 표시 / ROS2 토픽 / CSV 로그

Qt 타이머
  -> 화면 갱신, 그래프 갱신, 로그 flush
```

그래서 “처음 어디서 시작하나”를 볼 때는 `run_gui.py -> app/main.py -> ui/main_window.py` 순서로 보고, “버튼을 눌렀을 때 무슨 일이 생기나”를 볼 때는 해당 `actions/` 파일과 `core/control_client.py`를 같이 보는 편이 빠릅니다.

## 독립 센서 노드

GUI를 켜지 않고 로드셀이나 리니어 엔코더만 ROS2 토픽으로 보고 싶을 때 쓰는 노드입니다. 터미널 출력은 `debug_print_hz`로 조절하고, `0`이면 출력하지 않습니다.

로드셀 노드:

```bash
cd /home/user/K-FLEX/TS_vivration_project/Motor_gui_jh/py
python3 -m motor_gui_app.nodes.load_cell_node --ros-args \
  -p n_channels:=2 \
  -p publish_hz:=200 \
  -p debug_print_hz:=10
```

캘리브레이션 파일을 지정한 로드셀 노드:

```bash
cd /home/user/K-FLEX/TS_vivration_project/Motor_gui_jh/py
python3 -m motor_gui_app.nodes.load_cell_node --ros-args \
  -p cal_file:=/home/user/K-FLEX/Load_cell/ch0_3cycle_cal.json \
  -p n_channels:=2 \
  -p publish_hz:=200 \
  -p debug_print_hz:=10
```

리니어 엔코더 노드:

```bash
cd /home/user/K-FLEX/TS_vivration_project/Motor_gui_jh/py
python3 -m motor_gui_app.nodes.linear_encoder_node --ros-args \
  -p channel:=0 \
  -p counts_per_mm:=314.4 \
  -p publish_hz:=100 \
  -p debug_print_hz:=10
```

토픽 주기 확인:

```bash
ros2 topic hz /load_cell/ch0_N
ros2 topic hz /linear_encoder/position_mm
```

리니어 엔코더 현재 위치를 0으로 재설정:

```bash
ros2 service call /linear_encoder/zero std_srvs/srv/Trigger "{}"
```

주의할 점: GUI 내장 센서 리더와 독립 센서 노드를 같은 장치에 동시에 붙이면 Phidget 연결이 충돌하거나 같은 ROS2 토픽에 값이 섞일 수 있습니다. 실험 로그를 남길 때는 한쪽만 켜는 편이 좋습니다.

## 폴더 구조

### 실행 진입점

- `run_gui.py`: `py/motor_gui_app` 폴더 안에서 바로 실행할 때 쓰는 런처.
- `__main__.py`: `python3 -m motor_gui_app` 실행 진입점.
- `app/main.py`: Qt 애플리케이션과 rclpy를 초기화하고 메인 윈도우를 생성합니다.
- `app/launcher_env.py`: 루트 GUI/CLI 런처가 공유하는 배포 폴더 환경 설정.
- `cli/main.py`: GUI 없이 쓰는 argparse 기반 CLI 진입점.

### `core/`

ROS2 통신, 설정, 백그라운드 스레드처럼 앱 전체가 공유하는 핵심 코드입니다.

- `config.py`: `config/defaults.json`을 읽고 경로/환경변수 override/안전 범위 제한을 적용해 `DEFAULT_*` 상수로 공개하는 설정 로더.
- `topics.py`: ROS2 토픽 이름.
- `epos_errors.py`: EPOS 에러 코드 설명.
- `feedback_state.py`: 모터, RT 진단, 로드셀, 리니어 엔코더 최신 피드백 값 컨테이너.
- `load_cell_calibration.py`: GUI 내장 로드셀 리더와 ROS2 로드셀 노드가 공유하는 캘리브레이션 JSON 해석.
- `linear_encoder_math.py`: GUI 내장 리니어 엔코더 리더와 ROS2 노드가 공유하는 count/mm 변환.
- `iir_filter.py`: GUI 내장 로드셀 리더와 ROS2 로드셀 노드가 공유하는 1차 IIR 필터.
- `motor_units.py`: 위치 tick/mm 변환처럼 UI 동작과 실험 로직이 함께 쓰는 모터 단위 계산.
- `ros_environment.py`: rclpy import 전에 필요한 ROS2/DDS 환경 설정, FastDDS UDP 프로파일 생성, EtherCAT 인터페이스 감지.
- `ros_bootstrap.py`: GUI/CLI/스레드가 공유하는 ROS2/DDS 준비 진입점.
- `ros_messages.py`: `epos_interfaces`의 `ForceCtrlCmd`, `WaveformCmd` 사용 가능 여부 감지.
- `phidget_support.py`: Phidget 라이브러리 사용 가능 여부, 로드셀/엔코더 클래스, 중력가속도 상수.
- `motor_process.py`: C++ `epos_motor_node` 실행 명령 생성.
- `time_utils.py`: 로그 타임스탬프 같은 작은 시간 유틸.
- `command_builders.py`: GUI 명령을 구조화 메시지 또는 기존 문자열 명령으로 변환.
- `control_client.py`: GUI/CLI 공용 제어 API. 수동 RPM/위치/토크, 힘 제어, 파형 제어, 히스테리시스 테스트, CSV 로깅처럼 C++ 노드 명령 순서가 중요한 동작을 함수 단위로 제공합니다.
- `session/`: GUI/CLI 공용 세션 모델.
  - `motor_session.py`: 제어 API, 상태 조회, 실행 플래그를 하나로 묶는 컨테이너.
  - `state_view.py`: `MonitorThread` 최신값을 읽기 전용 메서드로 제공.
  - `flags.py`: 모터 실행, 파형, 스크립트, 히스테리시스 테스트 실행 상태.
- `experiments/`: GUI와 CLI가 공유하는 실험 실행 흐름.
  - `hysteresis_experiment.py`: 히스테리시스 테스트의 예약, 안정화, 기록 상태 전환, 종료/중지 처리.
- `commander.py`: GUI 명령, heartbeat, 로드셀/엔코더 값을 ROS2로 퍼블리시하는 스레드.
- `monitor.py`: 모터 피드백과 진단 토픽을 구독하는 스레드.
- `node_runner.py`: C++ `epos_motor_node` 프로세스 시작/종료 관리.

`ForceCtrlCmd`, `WaveformCmd` 메시지가 빌드되어 있으면 v2 구조화 토픽을 사용하고, 메시지를 찾지 못하는 환경에서는 기존 문자열 토픽으로 되돌아갑니다.

### `config/`와 `core/config.py`

- `config/defaults.json`: 사용자가 조정하는 기본값 데이터입니다.
- `core/config.py`: `defaults.json`을 읽고, 환경변수 override와 안전 범위 제한을 적용해 `DEFAULT_*` 상수로 공개하는 설정 로더입니다.

즉 `defaults.json`은 값이고, `core/config.py`는 그 값을 GUI/CLI/C++ 노드 실행 코드가 쓰기 좋은 형태로 바꾸는 계층입니다.

### `ui/`

메인 윈도우 조립과 화면 갱신 흐름입니다.

- `main_window.py`: 세션 상태 속성, 그래프/로그 갱신, 종료 처리만 남긴 얇은 메인 윈도우 클래스.
- `runtime_init.py`: 창 크기, 런타임 상태 컨테이너, 스레드, 센서 리더, signal, 타이머 초기화.
- `runtime_components.py`: `RuntimeThreads`, `DeviceReaders`처럼 실행 중 붙잡는 스레드/장치 핸들을 묶는 컨테이너.
- `session_properties.py`: `window.motor_running` 같은 기존 상태 접근을 `session.flags`로 연결하는 property 묶음.
- `graph_buffers.py`: 그래프용 NumPy 배열, 큐, 포인터 상태를 묶는 버퍼 객체.
- `log_buffer.py`: GUI 로그 메시지 큐와 flush 타이머를 묶는 버퍼 객체.
- `window_state.py`: 위젯 핸들이 아닌 GUI 실행 상태를 묶는 객체.
- `widget_groups.py`: 패널별 PyQt 위젯 핸들을 묶는 컨테이너. `MasterWindow`에 개별 버튼/라벨/스핀박스가 흩어지지 않도록 상단 상태, 그래프, 로드셀, 힘 제어, 파형, 수동 모션, 위치/토크, 리니어 엔코더, 히스테리시스, 패널 표시 토글을 기능 단위로 보관합니다.
- `window_layout.py`: 상단 상태 영역, 제어 패널, 그래프 영역 배치.
- `status_update.py`: 모터 상태, 로드셀, 리니어 엔코더, fault 표시 갱신.
- `graph_update.py`: 속도 그래프와 RT 주기 그래프 갱신.
- `visibility_actions.py`: 패널/그래프 표시 토글.
- `log_view_actions.py`: GUI 로그창 append/flush.
- `styles.py`: 여러 패널에서 공유하는 작은 Qt 스타일 상수.

### `panels/`

PyQt 위젯을 만드는 모듈입니다. 가능한 한 “위젯 생성”에만 집중하고, 실제 동작은 `actions/` 쪽으로 넘깁니다.

- `top_status_panel.py`: 인터페이스 선택, 시스템 시작/종료, 진단 라벨.
- `motion_control_panel.py`: 수동 속도, 위치/토크, 파형, 리니어 엔코더 제어.
- `force_control_panel.py`: PID/Tanh 힘 제어 설정.
- `load_cell_panel.py`: 로드셀 캘리브레이션, tare, 소프트 리미트.
- `hysteresis_panel.py`: 히스테리시스 테스트 설정.
- `script_logging_panel.py`: CSV 로깅과 Python 모션 스크립트.
- `graph_panel.py`: 그래프 영역.
- `log_viewer_panel.py`: GUI 로그창.
- `emergency_stop_panel.py`: 비상정지 버튼 행.
- `panel_visibility_bar.py`: 패널 표시/숨김 체크박스.

### `actions/`

버튼 클릭, 스핀박스 변경, 시작/정지 같은 UI 이벤트의 실제 동작입니다.

- `system_actions.py`: 인터페이스 새로고침, 시스템 시작/종료, fault reset.
- `motion_actions.py`: 수동 RPM, 위치/mm 변환, 토크, 비상정지.
- `waveform_actions.py`: 속도/위치 사인파와 chirp 파형 시작/정지.
- `force_control_actions.py`: 힘 제어 시작/정지, PID/Tanh 모드와 파라미터 적용.
- `hysteresis_actions.py`: 히스테리시스 테스트 시작, 예약, 중지, 완료 처리.
- `logging_actions.py`: CSV 로깅 시작/정지.
- `script_actions.py`: 모션 스크립트 선택, 시작/정지.
- `load_cell_actions.py`: 캘리브레이션 파일 선택, tare, 단위, 소프트 리미트.
- `linear_encoder_actions.py`: 리니어 엔코더 연결, zero, 설정 적용.

### `devices/`

GUI 안에서 직접 Phidget 장치를 읽는 코드입니다.

- `load_cell.py`: GUI 내장 로드셀 리더, tare, N/g 변환. 캘리브레이션 JSON 해석은 `core/load_cell_calibration.py`, 필터는 `core/iir_filter.py`를 공유합니다.
- `linear_encoder.py`: GUI 내장 리니어 엔코더 리더. count/mm 변환은 `core/linear_encoder_math.py`를 공유합니다.

### `nodes/`

GUI와 별개로 단독 실행 가능한 ROS2 센서 노드입니다.

- `load_cell_node.py`: Phidget 로드셀 값을 `/load_cell/*` 토픽으로 퍼블리시.
- `linear_encoder_node.py`: Phidget 리니어 엔코더 값을 `/linear_encoder/*` 토픽으로 퍼블리시.
- `README.md`: 노드 단독 실행 예시.

### `logic/`

UI나 ROS2에 직접 묶이지 않는 계산/검증 코드입니다.

- `hysteresis.py`: 히스테리시스 테스트 라벨, 진폭 변환, 동작 요약.
- `motion_script.py`: 사용자 모션 스크립트 로드와 검증.

### `config/`

- `defaults.json`: GUI/CLI 기본값. 루트 `run_gui.py`와 `run_cli.py`는 이 파일을 `EPOS_DEFAULTS_FILE`로 지정합니다.

## 정리 기준

- `panels/`는 화면을 만들고, `actions/`는 동작을 처리합니다.
- `core/`는 ROS2/Qt 스레드와 공통 설정을 담당합니다.
- `devices/`는 GUI 안에서 장치를 직접 읽을 때 사용합니다.
- `nodes/`는 GUI 없이 센서만 ROS2로 퍼블리시할 때 사용합니다.
- C++ RT 노드와 맞물리는 명령 포맷은 `core/command_builders.py`에서 한 번에 관리합니다.

새 기능을 추가할 때는 먼저 “화면”, “동작”, “통신/스레드”, “순수 계산” 중 어디에 속하는지 정하면 파일 위치를 잡기 쉽습니다.

## 구조 검토 메모

현재 분리는 용도 기준으로 적당한 편입니다. 원래 GUI 한 덩어리에 있던 책임을 화면 생성(`panels/`), 이벤트 처리(`actions/`), 공용 제어 API(`core/control_client.py`), 상태 조회(`core/session/state_view.py`), 실행 플래그(`core/session/flags.py`), 실험 흐름(`core/experiments/`)으로 나눴기 때문에 CLI와 GUI가 같은 제어 경로를 공유할 수 있습니다.

과하게 쪼개지지 않도록 작은 계산은 필요할 때만 분리했습니다. 예를 들어 로드셀 캘리브레이션 JSON 해석은 `core/load_cell_calibration.py`, 로드셀 IIR 필터는 `core/iir_filter.py`, 리니어 엔코더 count/mm 변환은 `core/linear_encoder_math.py`, 모터 tick/mm 변환은 `core/motor_units.py`가 공유합니다. 장치 연결과 콜백 처리는 여전히 `devices/`와 `nodes/`에 남아 있어 파일 수가 목적 없이 늘어나지는 않습니다.

클로드 코드 리뷰에서 지적된 죽은 호환 계층은 정리했습니다. 더 이상 쓰이지 않던 `core/runtime.py`와 `MonitorThread.latest_*` alias property는 제거했고, ROS2/DDS 환경 준비도 앱/CLI 진입점에서 명시적으로 수행하도록 top-level import 부작용을 줄였습니다. GUI 쪽도 `window.commander`, `window.monitor`, `window.control`, `window.lc_reader`, `window.linear_encoder` alias를 제거해 `window.runtime_threads`, `window.device_readers`, `window.session`으로 접근 경로를 통일했습니다.

`CommandThread.run()`은 여전히 하나의 200 Hz 명령 루프이지만, 내부 책임은 heartbeat, 센서 피드백 발행, 비동기 명령 큐 처리, 수동/스크립트 목표 계산, 소프트 리미트 적용 메서드로 분리했습니다. 그래서 새 센서나 명령 경로를 붙일 때 루프 전체를 다시 읽기보다 해당 메서드만 확인하면 됩니다.

로드셀 힘 한계는 의도적으로 Python과 C++ 양쪽에 있습니다. Python `CommandThread`는 soft-start 비율부터 RPM 명령을 서서히 줄이는 완충 역할을 하고, C++ RT 루프는 같은 한계를 hard stop으로 다시 확인합니다. GUI 내장 센서 리더와 독립 센서 노드가 같은 토픽을 동시에 발행하면 로그에 경고가 뜨지만, 실험 중에는 한쪽만 켜는 것이 안전합니다.

리뷰할 때 핵심 질문은 “새 센서/모터를 추가할 때 수정 위치가 예측 가능한가?”입니다. 지금 기준으로는 토픽은 `core/topics.py`, 최신값 구조는 `core/feedback_state.py`, 구독 노출은 `core/monitor.py`와 `core/session/state_view.py`, GUI 위젯은 `panels/`와 `ui/widget_groups.py`, 버튼 동작은 `actions/`, 공용 명령은 `core/control_client.py`와 `core/command_builders.py`로 이어집니다.

## 모터/센서 추가 기준

센서를 추가할 때는 다음 흐름을 기본으로 봅니다.

1. GUI 안에서 직접 장치를 읽어야 하면 `devices/`에 Reader를 추가하고, `ui/runtime_init.py`의 `_init_devices()`와 `DeviceReaders`에 연결합니다.
2. GUI와 독립적으로 ROS2 토픽만 퍼블리시할 센서라면 `nodes/`에 독립 노드를 추가합니다.
3. 새 토픽은 `core/topics.py`에 상수로 두고, 최신 수신값의 저장 구조는 `core/feedback_state.py`에 추가합니다.
4. ROS2 구독 콜백은 `core/monitor.py`에 두고, GUI/CLI가 읽는 공개 조회 API는 `core/session/state_view.py`에 둡니다.
5. 화면이 필요하면 `panels/`에서 위젯을 만들고 `ui/widget_groups.py`에 위젯 묶음을 추가합니다.
6. 버튼/입력 동작은 `actions/`에 두고, C++ 노드로 보내는 명령은 `core/control_client.py`와 `core/command_builders.py`를 통하게 합니다.

모터 축이나 구동 모드가 늘어날 때도 원칙은 같습니다. UI는 `panels/`, 사용자 동작은 `actions/`, 명령 API는 `control_client.py`, 실제 토픽/메시지 포맷은 `command_builders.py`와 C++ 노드 쪽에 둡니다.
