# 힘 제어 명령용 구조화 메시지.
# 기존 문자열 토픽(/epos/force_ctrl_cmd)은 호환용으로 유지하고,
# 새 GUI는 /epos/force_ctrl_cmd_v2 로 이 메시지를 보낸다.

uint8 ACTION_START=1
uint8 ACTION_STOP=2
uint8 ACTION_SET_TARGET=3
uint8 ACTION_SET_DIRECTION=4
uint8 ACTION_SET_FEEDBACK=5
uint8 ACTION_SET_PID=6
uint8 ACTION_SET_TANH=7
uint8 ACTION_SET_MAX_RPM=8
uint8 ACTION_SET_OUTPUT_ALPHA=9
uint8 ACTION_SET_LIMIT=10
uint8 ACTION_SET_FORCE_ABS=11
uint8 ACTION_SET_TARE_OFFSET=12
uint8 ACTION_TARE_RESET=13

uint8 MODE_PID=0
uint8 MODE_TANH=1

uint8 FEEDBACK_CH0=0
uint8 FEEDBACK_CH1=1
uint8 FEEDBACK_AVG=2
uint8 FEEDBACK_MAX_ABS=3

uint8 action

# 공통/모드 필드. action에 필요한 필드만 읽는다.
float64 target_n
int32 direction
uint8 feedback
int32 max_rpm
float64 output_alpha

float64 kp
float64 ki
float64 kd

float64 tanh_sensitivity_n
float64 tanh_deadband_n

float64 limit_n
bool force_abs

int32 tare_channel
float64 tare_offset_n
