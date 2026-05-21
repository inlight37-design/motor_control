# nodes

GUI와 별개로 단독 실행할 수 있는 ROS2 센서 노드 모음입니다. 장비 연결 확인, 토픽 주기 확인, GUI 없이 센서값만 보고 싶을 때 사용합니다.

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

`debug_print_hz:=0`이면 터미널 출력은 꺼집니다. GUI 내장 센서 리더와 독립 노드를 같은 장치에 동시에 붙이면 Phidget 연결이 충돌하거나 같은 토픽에 값이 섞일 수 있으니, 실험 로그를 남길 때는 한쪽만 실행하는 편이 좋습니다.
