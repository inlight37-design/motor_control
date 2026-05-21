# Motor_gui_jh

모터 GUI와 C++ ROS2 제어 노드를 한 폴더에서 보기 쉽게 묶은 배포용 구조입니다.

## 폴더 구조

- `run_gui.py`: GUI 실행 런처.
- `run_cli.py`: GUI 없이 상태 확인/간단한 제어 명령을 보내는 CLI 런처.
- `py/`: Python GUI, 로그 분석 도구, 센서 노드 코드.
  - `motor_gui_app/`: 메인 모터 GUI 코드.
    - `core/config.py`: 실행 경로/환경변수와 `config/defaults.json`을 읽어 타입 있는 기본값 상수로 공개하는 설정 로더.
    - `core/topics.py`: GUI와 C++ 노드가 공유하는 ROS2 토픽 이름.
    - `core/epos_errors.py`: EPOS4 에러 코드 설명표.
    - `core/feedback_state.py`: 모터, RT 진단, 로드셀, 리니어 엔코더 최신 피드백 값 컨테이너.
    - `core/load_cell_calibration.py`: GUI 내장 로드셀 리더와 ROS2 로드셀 노드가 공유하는 캘리브레이션 JSON 해석.
    - `core/linear_encoder_math.py`: GUI 내장 리니어 엔코더 리더와 ROS2 노드가 공유하는 count/mm 변환.
    - `core/control_client.py`: GUI/CLI가 공유하는 고수준 제어 API.
    - `core/session/`: 제어 API, 상태 조회, 실행 플래그를 묶는 세션 모델.
    - `core/ros_environment.py`: ROS2/DDS 환경 설정과 EtherCAT 인터페이스 감지.
    - `core/ros_bootstrap.py`: `rclpy` import 전에 필요한 DDS 환경 준비.
    - `core/motor_process.py`: C++ `epos_motor_node` 실행 명령 조립.
  - `tools/`: 실험 보조 도구. 로그 분석, 장력 루프 CLI, 로드셀 캘리브레이션 GUI.
- `cpp/`: C++/ROS2 colcon 워크스페이스.
  - `README.md`: C++ 빌드, 직접 실행, 패키지/토픽/파라미터 설명.
  - `src/epos_control/include/control/`: 속도/위치/힘 제어 계산, PID, slew-rate 제한.
  - `src/epos_control/include/safety/`: 힘 한계와 최종 출력 안전장치.
  - `src/epos_control/include/ethercat/`: EPOS 레지스터, PDO 구조, CiA402, EtherCAT 초기 설정.
  - `src/epos_control/include/logging/`: CSV 로거, 로그 명령, 로그 파일 경로 헬퍼.
  - `src/epos_control/include/waveform/`: 파형 생성과 히스테리시스 계획.
  - `src/epos_control/include/commands/`: GUI/스크립트 명령 파싱.
  - `src/epos_control/include/util/`: 단위 변환, 네트워크 감지, RT 설정, 링버퍼.
- `logs/`: CSV 로그와 분석 결과 기본 저장 위치.

## 현재 분리 기준

이번 정리 후 Python 쪽은 “보이는 화면”, “사용자 동작”, “공유 제어 로직”, “장치 접근”, “독립 ROS2 노드”가 나뉘어 있습니다.

- `panels/`는 위젯을 만들고 배치합니다. 버튼을 눌렀을 때의 실제 처리는 `actions/`로 넘깁니다.
- `actions/`는 GUI 이벤트를 받아 `core/control_client.py`, 세션 상태, 장치 리더를 호출합니다.
- `core/`는 GUI와 CLI가 같이 쓰는 설정, ROS2 통신, 명령 생성, 상태 조회, 실험 실행 흐름을 맡습니다.
- `devices/`는 GUI 프로세스 안에서 Phidget 장치를 직접 읽을 때 사용합니다.
- `nodes/`는 GUI 없이 센서만 ROS2 토픽으로 퍼블리시할 때 사용합니다.

지금 구조는 일부러 “완전한 플러그인 시스템”까지는 가지 않았습니다. 로드셀 캘리브레이션과 리니어 엔코더 count/mm 변환처럼 GUI 리더와 독립 노드가 같이 쓰는 계산만 `core/`로 빼고, 장치 연결 자체는 `devices/`와 `nodes/`에 남겼습니다. 그래서 새 모터나 센서를 추가할 때 공통 계산/토픽/상태 저장 위치는 명확하지만, 작은 파일이 불필요하게 더 쪼개지는 부담은 줄였습니다.

호환을 위해 `window.commander`, `window.monitor`, `window.lc_reader` 같은 기존 이름은 아직 alias로 남아 있습니다. 새 코드는 가능하면 `window.runtime_threads`, `window.device_readers`, `window.session`을 우선 보면 되고, 기존 actions가 모두 옮겨진 뒤 alias를 줄이면 됩니다.

## 설정 파일과 설정 로더

- `py/motor_gui_app/config/defaults.json`: 사용자가 조정하는 기본값 데이터입니다. 모터 상한, 파형 기본값, 힘 제어 PID, 로드셀/리니어 엔코더 기본값이 들어 있습니다.
- `py/motor_gui_app/core/config.py`: 위 JSON을 읽고, 환경변수 override를 적용하고, 위험한 값은 허용 범위 안으로 제한한 뒤 `DEFAULT_*` 상수로 내보내는 Python 코드입니다.

루트 `run_gui.py`와 `run_cli.py`는 실행 시 `EPOS_DEFAULTS_FILE`을 배포 폴더 안의 `defaults.json`으로 잡아 줍니다. 다른 설정 파일을 시험하려면 실행 전에 `EPOS_DEFAULTS_FILE=/path/to/defaults.json`을 지정하면 됩니다.

## 첫 설치 명령

새 PC에서 이 폴더를 처음 사용할 때는 아래 순서대로 실행합니다. ROS2 Jazzy는 Ubuntu에 이미 설치되어 있고 `/opt/ros/jazzy`가 있는 상태를 기준으로 합니다.

ROS2 설치 확인:

```bash
source /opt/ros/jazzy/setup.bash
ros2 --version
```

기본 빌드 도구와 Python GUI/분석 패키지 설치:

```bash
sudo apt update
sudo apt install -y \
  build-essential \
  cmake \
  git \
  python3-colcon-common-extensions \
  python3-pip \
  python3-venv \
  python3-tk \
  python3-numpy \
  python3-matplotlib \
  python3-sklearn \
  python3-pyqt5 \
  python3-pyqtgraph
```

Python 패키지 설치. 현재 PC처럼 시스템 Python을 그대로 쓰면 venv 없이도 됩니다. 다른 PC에서 Python 패키지를 폴더별로 맞추고 싶으면 아래처럼 venv를 사용합니다.

```bash
cd /home/user/K-FLEX/TS_vivration_project/Motor_gui_jh
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r py/requirements.txt
```

venv를 쓰지 않고 시스템 Python에 바로 설치할 때:

```bash
cd /home/user/K-FLEX/TS_vivration_project/Motor_gui_jh
python3 -m pip install --user -r py/requirements.txt
```

Ubuntu에서 `externally-managed-environment` 오류가 나오면 venv 방식을 쓰는 편이 안전합니다.

C++/ROS2 노드 빌드:

```bash
cd /home/user/K-FLEX/TS_vivration_project/Motor_gui_jh/cpp
./build_cpp.sh
```

GUI 실행:

```bash
cd /home/user/K-FLEX/TS_vivration_project/Motor_gui_jh
source /opt/ros/jazzy/setup.bash
python3 run_gui.py
```

## C++ 빌드

ROS2 자체는 이 폴더에 넣지 않습니다. Ubuntu에 설치된 `/opt/ros/jazzy`를 사용합니다.

```bash
cd /home/user/K-FLEX/TS_vivration_project/Motor_gui_jh/cpp
./build_cpp.sh
```

직접 빌드하려면:

```bash
cd /home/user/K-FLEX/TS_vivration_project/Motor_gui_jh/cpp
source /opt/ros/jazzy/setup.bash
colcon build --packages-select soem epos_interfaces epos_control --cmake-args -DCMAKE_BUILD_TYPE=Release
```

`cpp/src` 안의 패키지:

- `soem`: EtherCAT 통신 라이브러리. `epos_control`이 의존하므로 이 폴더 안에 함께 둡니다.
- `epos_interfaces`: GUI와 C++ 노드가 공유하는 구조화 ROS2 메시지.
- `epos_control`: EPOS4 EtherCAT 실시간 제어 노드.

## GUI 실행

```bash
cd /home/user/K-FLEX/TS_vivration_project/Motor_gui_jh
python3 run_gui.py
```

`rclpy`를 찾지 못한다는 오류가 나면 먼저 `source /opt/ros/jazzy/setup.bash`를 실행한 뒤 다시 실행합니다.

## CLI 실행

GUI를 켜지 않고 C++ 모터 노드가 이미 실행 중인 상태를 확인하거나, 짧은 수동 명령을 보낼 때 사용합니다.
제어 명령은 기본적으로 `ControlClient`를 통과하므로 GUI 버튼과 같은 명령 경로를 씁니다.

인자 없이 실행하면 대화형 프롬프트가 열립니다. 이 모드에서는 GUI처럼 `CommandThread`와 `MonitorThread`를 한 번만 띄운 뒤 계속 재사용합니다. 그래서 그 안에서 `status`, `stop`, `rpm ...` 같은 명령을 이어서 입력할 수 있습니다.

```bash
cd /home/user/K-FLEX/TS_vivration_project/Motor_gui_jh
python3 run_cli.py
```

대화형 프롬프트 예:

```text
motor> status
motor> rpm 50 --seconds 1
motor> stop
motor> exit
```

도움말:

```bash
python3 run_cli.py --help
```

현재 적용된 설정 파일과 주요 기본값 확인:

```bash
python3 run_cli.py config
```

스크립트나 자동화에서는 한 줄 명령도 그대로 사용할 수 있습니다. 한 줄 명령은 필요한 ROS2 세션을 잠깐 만들고, 명령이 끝나면 정리합니다. 상태 한 번 출력:

```bash
python3 run_cli.py status
```

2초 동안 상태 출력:

```bash
python3 run_cli.py status --seconds 2 --hz 5
```

정지 명령:

```bash
python3 run_cli.py stop
```

짧은 RPM 테스트. 지정 시간이 지나면 0 rpm으로 되돌립니다.

```bash
python3 run_cli.py rpm 50 --seconds 1
```

tick 위치 명령:

```bash
python3 run_cli.py position 4000 --speed 500 --seconds 2
```

속도 사인 기반 히스테리시스 테스트. GUI와 같은 `HysteresisExperiment` 흐름을 사용합니다.

```bash
python3 run_cli.py hyst-velocity --freq 1 --amp-rpm 50 --settle-cycles 1 --record-cycles 3
```

루트 `run_gui.py`와 `run_cli.py`가 자동으로 설정하는 값:

- `EPOS_WORKSPACE_DIR=Motor_gui_jh/cpp`
- `WS_SETUP=Motor_gui_jh/cpp/install/setup.bash`
- `EPOS_LOG_DIR=Motor_gui_jh/logs`
- `EPOS_DEFAULTS_FILE=Motor_gui_jh/py/motor_gui_app/config/defaults.json`

## Python 환경

현재 PC처럼 ROS2, PyQt5, pyqtgraph, Phidget22가 시스템에 설치되어 있으면 venv 없이 시스템 Python으로 실행하는 쪽이 가장 단순합니다.

다른 PC에서 Python 패키지만 따로 맞추고 싶으면 venv를 선택적으로 만들 수 있습니다. ROS2의 `rclpy`는 pip 패키지가 아니라 ROS 설치에서 오므로, 일반 venv보다 `--system-site-packages`를 쓰는 편이 덜 헷갈립니다.

```bash
cd /home/user/K-FLEX/TS_vivration_project/Motor_gui_jh
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python3 -m pip install -r py/requirements.txt
```

GUI나 노드를 실행하기 전에 ROS2 환경이 필요하면 아래처럼 먼저 source 합니다.

```bash
source /opt/ros/jazzy/setup.bash
```

## 독립 노드 실행

로드셀 노드:

```bash
cd /home/user/K-FLEX/TS_vivration_project/Motor_gui_jh
python3 py/motor_gui_app/nodes/load_cell_node.py --ros-args \
  -p n_channels:=2 \
  -p publish_hz:=200 \
  -p debug_print_hz:=10
```

리니어 엔코더 노드:

```bash
cd /home/user/K-FLEX/TS_vivration_project/Motor_gui_jh
python3 py/motor_gui_app/nodes/linear_encoder_node.py --ros-args \
  -p channel:=0 \
  -p counts_per_mm:=314.4 \
  -p publish_hz:=100 \
  -p debug_print_hz:=10
```

## 도구 실행

로그 분석 GUI:

```bash
cd /home/user/K-FLEX/TS_vivration_project/Motor_gui_jh
python3 py/tools/log_analysis_gui.py
```

장력 루프 CLI 플롯:

```bash
cd /home/user/K-FLEX/TS_vivration_project/Motor_gui_jh
python3 py/tools/plot_tension_loop.py logs/example.csv --mode both --show
```

로드셀 캘리브레이션 GUI:

```bash
cd /home/user/K-FLEX/TS_vivration_project/Motor_gui_jh
python3 py/tools/load_cell_calibration_gui.py
```

## 주의

- ROS2 Jazzy, colcon, Python Qt/pyqtgraph, Phidget22 라이브러리는 시스템에 설치되어 있어야 합니다.
- 로드셀 캘리브레이션 GUI는 `tkinter`, `matplotlib`, `scikit-learn`, `Phidget22`를 사용합니다. Ubuntu에서 `tkinter`가 없으면 `sudo apt install python3-tk`가 필요할 수 있습니다.
- `cpp/build`, `cpp/install`, `cpp/log`는 빌드 산출물이므로 다른 PC로 옮기기 전에는 지워도 됩니다.
- `logs/`는 실험 데이터가 쌓이는 위치입니다. 코드만 배포할 때는 비워둬도 됩니다.
