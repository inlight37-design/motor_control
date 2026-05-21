# cpp

`Motor_gui_jh`의 C++/ROS2 colcon 워크스페이스입니다. Maxon EPOS4를 SOEM 기반 EtherCAT으로 제어하는 실시간 노드와, Python GUI가 쓰는 구조화 메시지 패키지가 들어 있습니다.

GUI에서 모터를 시작하면 내부적으로 이 워크스페이스의 `install/setup.bash`를 source 한 뒤 `epos_motor_node`를 실행합니다.

## 빌드

권장 빌드:

```bash
cd /home/user/K-FLEX/TS_vivration_project/Motor_gui_jh/cpp
./build_cpp.sh
```

직접 빌드:

```bash
cd /home/user/K-FLEX/TS_vivration_project/Motor_gui_jh/cpp
source /opt/ros/jazzy/setup.bash
colcon build --packages-select soem epos_interfaces epos_control \
  --cmake-args -DCMAKE_BUILD_TYPE=Release
```

빌드 후 환경 적용:

```bash
source /home/user/K-FLEX/TS_vivration_project/Motor_gui_jh/cpp/install/setup.bash
```

`build_cpp.sh`는 `ROS_SETUP` 환경변수가 있으면 그 값을 사용하고, 없으면 `/opt/ros/jazzy/setup.bash`를 사용합니다.

```bash
ROS_SETUP=/opt/ros/jazzy/setup.bash ./build_cpp.sh
```

## 실행

보통은 루트 GUI 런처가 C++ 노드를 자동 실행합니다.

```bash
cd /home/user/K-FLEX/TS_vivration_project/Motor_gui_jh
python3 run_gui.py
```

C++ 노드만 직접 실행해서 확인하려면 EtherCAT 인터페이스 이름을 지정합니다. 실제 모터를 움직일 수 있으니 축이 안전한 상태인지 먼저 확인하세요.

```bash
cd /home/user/K-FLEX/TS_vivration_project/Motor_gui_jh/cpp
source /opt/ros/jazzy/setup.bash
source install/setup.bash
sudo bash -lc 'source /opt/ros/jazzy/setup.bash && source install/setup.bash && chrt -f 50 ros2 run epos_control epos_motor_node --ros-args -p iface:=enx588694f746d0'
```

사용 가능한 이더넷 인터페이스 확인:

```bash
ip link
```

GUI는 `enx*`, `enp*` 계열 인터페이스를 자동 후보로 보여줍니다. EPOS EtherCAT용 어댑터를 고르면 됩니다.

## 패키지 구성

- `src/soem/`: EtherCAT 통신 라이브러리. `epos_control`에서 링크해서 사용합니다.
- `src/epos_interfaces/`: GUI와 C++ 노드가 공유하는 ROS2 메시지 패키지입니다.
- `src/epos_control/`: EPOS4 EtherCAT 실시간 제어 노드입니다.

빌드 산출물:

- `build/`: colcon 빌드 중간 산출물.
- `install/`: 실행에 필요한 설치 산출물과 `setup.bash`.
- `log/`: colcon 빌드 로그.

위 세 폴더는 다시 빌드하면 생기는 산출물입니다. 코드만 옮길 때는 지워도 됩니다.

## epos_interfaces

구조화 메시지 2개를 제공합니다.

- `msg/ForceCtrlCmd.msg`: 힘 제어 시작/정지, 목표힘, PID, Tanh, soft limit, tare offset 명령.
- `msg/WaveformCmd.msg`: 속도 파형, 위치 사인파, 히스테리시스 테스트 예약 명령.

Python GUI는 메시지가 빌드되어 있으면 v2 구조화 토픽을 사용합니다.

- `/epos/force_ctrl_cmd_v2`
- `/epos/waveform_cmd_v2`

호환성을 위해 기존 문자열 토픽도 C++ 노드에서 계속 받습니다.

- `/epos/force_ctrl_cmd`
- `/epos/waveform_cmd`

## epos_control 구조

중심 실행 파일은 `src/epos_control/src/epos_motor_node.cpp`입니다. ROS2 노드 생성, 토픽/서비스 연결, EtherCAT RT 루프 소유권을 담당합니다.

보조 구현:

- `src/epos_control/src/epos_setup.cpp`: EPOS4 SDO/PDO 초기 설정.

헤더 폴더:

- `include/commands/`: 문자열 명령과 구조화 메시지를 내부 명령 구조로 변환.
- `include/control/`: 속도, 위치, 힘 제어 계산. PID, Tanh, slew-rate limiter 포함.
- `include/ethercat/`: EPOS 레지스터, PDO 구조체, CiA402 상태, EtherCAT setup 선언.
- `include/logging/`: RT 루프용 비동기 CSV 로거와 로그 명령 파싱.
- `include/safety/`: 힘 한계와 최종 출력 안전 조건.
- `include/util/`: 단위 변환, 네트워크 인터페이스 감지, RT 설정, SPSC 링버퍼.
- `include/waveform/`: 사인/사각/삼각/chirp/위치 사인파 생성과 히스테리시스 기록 구간 계산.

큰 원칙은 이렇습니다.

- ROS2 콜백은 값을 atomic 변수나 lock-free 버퍼에 저장만 합니다.
- 1 kHz RT 루프는 ROS2 콜백과 분리되어 EtherCAT PDO를 주기적으로 교환합니다.
- RT 루프 안에서는 동적 할당, 파일쓰기, ROS 로그 출력을 피합니다.
- CSV 파일 쓰기는 `AsyncCsvLogger`가 별도 스레드에서 처리합니다.
- 안전 조건은 RT 루프에서 먼저 판단하고, 사용자에게 보여줄 로그/진단은 non-RT 쪽에서 발행합니다.

## 주요 ROS2 입력

GUI 또는 스크립트가 C++ 노드로 보내는 토픽입니다.

- `/target_speed` (`std_msgs/Int32`): 속도 명령 [rpm]
- `/target_position` (`std_msgs/Int32`): 위치 명령 [motor tick]
- `/target_torque` (`std_msgs/Int32`): 토크 명령 [rated torque per mille]
- `/op_mode_cmd` (`std_msgs/Int32`): EPOS 동작 모드, `8=position`, `9=velocity`, `10=torque`
- `/accel_limit_rpm_s` (`std_msgs/Int32`): 속도 명령 slew-rate 제한 [rpm/s]
- `/pos_speed_limit` (`std_msgs/Int32`): 위치 제어용 최대 속도 [tick/s]
- `/epos/waveform_cmd_v2` (`epos_interfaces/WaveformCmd`): 구조화 파형 명령
- `/epos/force_ctrl_cmd_v2` (`epos_interfaces/ForceCtrlCmd`): 구조화 힘 제어 명령
- `/epos/log_cmd` (`std_msgs/String`): CSV 기록 시작/정지
- `/epos/heartbeat` (`std_msgs/Int32`): GUI 생존 신호
- `/load_cell/ch0_N`, `/load_cell/ch1_N` (`std_msgs/Float32`): 로드셀 힘 [N]
- `/linear_encoder/position_count` (`std_msgs/Int32`): 리니어 엔코더 count
- `/linear_encoder/position_mm` (`std_msgs/Float32`): 리니어 엔코더 위치 [mm]

## 주요 ROS2 출력

C++ 노드가 GUI로 보내는 피드백입니다.

- `/measured_speed`
- `/epos/status_word`
- `/epos/actual_position`
- `/epos/actual_torque`
- `/epos/wkc`
- `/epos/cycle_dt_us`
- `/epos/cycle_jitter_us`
- `/epos/cycle_overrun_count`
- `/epos/wkc_error_count`
- `/epos/error_code`
- `/epos/diag_summary`

서비스:

- `/epos_motor_node/enable` (`std_srvs/SetBool`): 모터 enable/disable 요청.
- `/epos_motor_node/fault_reset` (`std_srvs/Trigger`): EPOS fault reset 요청.

## 주요 파라미터

직접 실행할 때 `--ros-args -p 이름:=값`으로 바꿀 수 있습니다.

- `iface`: EtherCAT 네트워크 인터페이스. 예: `enx588694f746d0`
- `cycle_hz`: RT 루프 주기. 기본 `1000`
- `publish_hz`: GUI 피드백 발행 주기. 기본 `50`
- `diag_hz`: 진단 요약 발행 주기. 기본 `10`
- `max_abs_target`: 속도 명령 안전 한계 [rpm]. 기본 `3000`
- `accel_limit_rpm_s`: 속도 slew-rate 제한 [rpm/s]. `0` 이하면 제한 없음.
- `cmd_timeout_ms`: 명령 타임아웃. `0`이면 비활성.
- `heartbeat_timeout_ms`: heartbeat 타임아웃. `0`이면 비활성.
- `auto_enable`: 시작 시 자동 enable 여부.
- `rt_enable`: SCHED_FIFO, mlockall, CPU pinning 시도 여부.
- `rt_priority`: RT 우선순위. 기본 `50`
- `rt_cpu`: RT 스레드 고정 CPU. `-1`이면 고정하지 않음.
- `op_mode`: 초기 모드. `8=position`, `9=velocity`, `10=torque`
- `motor_ticks_per_rev`: 모터 1회전 tick 수. 기본 `2000`
- `pos_p_gain`: 위치 제어 P 게인.
- `force_limit_N`: 힘 soft limit [N]. `0`이면 비활성.
- `force_max_rpm`: 힘 제어 출력 최대 rpm. 기본 `50`
- `force_kp`, `force_ki`, `force_kd`: PID 힘 제어 게인.
- `force_out_alpha`: 힘 제어 출력 저역통과 계수.
- `force_tanh_sensitivity_N`: Tanh 힘 제어 민감도 [N].
- `force_tanh_deadband_N`: Tanh 힘 제어 데드밴드 [N].

GUI에서 실행할 때는 `py/motor_gui_app/config/defaults.json`과 GUI 입력값이 주요 파라미터를 조립해서 전달합니다.

## 로그

CSV 로깅은 `/epos/log_cmd`로 시작/정지합니다. RT 루프는 링버퍼에 샘플을 push만 하고, 실제 파일 쓰기는 별도 로거 스레드가 합니다.

GUI 기본 로그 위치:

```text
Motor_gui_jh/logs/
```

루트 `run_gui.py`는 `EPOS_LOG_DIR=Motor_gui_jh/logs`를 자동으로 지정합니다.

## 주의

- EPOS EtherCAT 제어는 실제 모터가 움직일 수 있는 코드입니다. 직접 `ros2 topic pub`로 명령을 넣을 때는 축 이동 범위와 비상정지를 먼저 확인하세요.
- C++ 노드는 raw EtherCAT 통신과 RT 스케줄링 때문에 GUI에서 `sudo`와 `chrt -f 50`으로 실행합니다.
- `cpp/build`, `cpp/install`, `cpp/log`는 산출물입니다. 소스 수정은 기본적으로 `cpp/src` 아래에서 합니다.
- `soem`은 외부 라이브러리 소스입니다. EPOS 제어 로직을 수정할 때는 보통 `epos_control`만 보면 됩니다.
