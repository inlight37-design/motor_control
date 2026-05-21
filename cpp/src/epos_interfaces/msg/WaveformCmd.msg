# 속도/위치 파형 및 히스테리시스 테스트 예약용 구조화 메시지.
# 기존 문자열 토픽(/epos/waveform_cmd)은 호환용으로 유지하고,
# 새 GUI는 /epos/waveform_cmd_v2 로 이 메시지를 보낸다.

uint8 ACTION_START=1
uint8 ACTION_STOP=2
uint8 ACTION_START_HYST_VELOCITY=3
uint8 ACTION_START_HYST_POSITION=4

uint8 TYPE_NONE=0
uint8 TYPE_SINE=1
uint8 TYPE_SQUARE=2
uint8 TYPE_TRIANGLE=3
uint8 TYPE_CHIRP=4
uint8 TYPE_POSITION_SINE=5

uint8 action
uint8 waveform_type

# 일반 속도 파형
float64 freq_hz
float64 freq_end_hz
float64 amp_rpm
float64 offset_rpm
float64 duration_s

# 위치 사인/히스테리시스 위치 사인
float64 amp_pos_ticks
float64 offset_pos_ticks
float64 max_pos_tps

# 히스테리시스 기록 창
int32 settle_cycles
int32 record_cycles
string log_path
