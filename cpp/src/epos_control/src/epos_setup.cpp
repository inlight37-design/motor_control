// epos_setup.cpp — EPOS4 PDO 매핑 설정

#include "ethercat/epos_setup.hpp"

#include <cstdint>

#include "ethercat/epos_registers.hpp"

namespace epos_control {

int setup_epos_pdo_mapping(uint16 slave)
{
  uint8_t zero = 0;
  uint8_t one = 1;
  uint16_t pdo_rx = EposReg::RX_PDO_MAPPING;  // RxPDO: PC→모터 매핑 오브젝트
  uint16_t pdo_tx = EposReg::TX_PDO_MAPPING;  // TxPDO: 모터→PC 매핑 오브젝트

  // RxPDO 매핑 (0x1C12 = Sync Manager 2 PDO Assignment)
  // 절차: 카운트를 0으로 → 매핑할 PDO 번호 지정 → 카운트를 1로
  (void)ec_SDOwrite(slave, EposReg::SM2_PDO_ASSIGN, 0x00, FALSE, sizeof(zero), &zero, EC_TIMEOUTSAFE);
  (void)ec_SDOwrite(slave, EposReg::SM2_PDO_ASSIGN, 0x01, FALSE, sizeof(pdo_rx), &pdo_rx, EC_TIMEOUTSAFE);
  (void)ec_SDOwrite(slave, EposReg::SM2_PDO_ASSIGN, 0x00, FALSE, sizeof(one), &one, EC_TIMEOUTSAFE);

  // TxPDO 매핑 (0x1C13 = Sync Manager 3 PDO Assignment)
  (void)ec_SDOwrite(slave, EposReg::SM3_PDO_ASSIGN, 0x00, FALSE, sizeof(zero), &zero, EC_TIMEOUTSAFE);
  (void)ec_SDOwrite(slave, EposReg::SM3_PDO_ASSIGN, 0x01, FALSE, sizeof(pdo_tx), &pdo_tx, EC_TIMEOUTSAFE);
  (void)ec_SDOwrite(slave, EposReg::SM3_PDO_ASSIGN, 0x00, FALSE, sizeof(one), &one, EC_TIMEOUTSAFE);

  // 통신 안정화 설정
  uint16_t abort_code = 0x0000;
  (void)ec_SDOwrite(slave, EposReg::ABORT_CONNECTION, 0x00, FALSE, sizeof(abort_code), &abort_code, EC_TIMEOUTSAFE);

  uint16_t fault_reaction = 0x0000;
  (void)ec_SDOwrite(slave, EposReg::FAULT_REACTION, 0x00, FALSE, sizeof(fault_reaction), &fault_reaction, EC_TIMEOUTSAFE);

  // Sync Mode = Free Run (0x0000) → DC 동기화 미사용
  uint16_t sync_mode = 0x0000;
  (void)ec_SDOwrite(slave, EposReg::SYNC_MANAGER_PARAM, 0x01, FALSE, sizeof(sync_mode), &sync_mode, EC_TIMEOUTSAFE);

  // RxPDO (0x1601) 상세 매핑: PC → 모터로 보낼 데이터
  // 형식: 0xIIIISSOO  (IIII=인덱스, SS=서브인덱스, OO=비트수)
  // OutPDO 구조체와 순서/크기가 정확히 일치해야 한다.
  uint8_t rx_cnt = 5;
  uint32_t rx_map[5] = {
    (static_cast<uint32_t>(EposReg::CONTROL_WORD) << 16) | 0x0010,
    (static_cast<uint32_t>(EposReg::MODE_OF_OPERATION) << 16) | 0x0008,
    (static_cast<uint32_t>(EposReg::TARGET_POSITION) << 16) | 0x0020,
    (static_cast<uint32_t>(EposReg::TARGET_VELOCITY) << 16) | 0x0020,
    (static_cast<uint32_t>(EposReg::TARGET_TORQUE) << 16) | 0x0010
  };
  (void)ec_SDOwrite(slave, EposReg::RX_PDO_MAPPING, 0x00, FALSE, sizeof(zero), &zero, EC_TIMEOUTSAFE);
  for (int i = 0; i < 5; i++) {
    (void)ec_SDOwrite(slave, EposReg::RX_PDO_MAPPING, static_cast<uint8>(i + 1), FALSE, sizeof(rx_map[i]), &rx_map[i], EC_TIMEOUTSAFE);
  }
  (void)ec_SDOwrite(slave, EposReg::RX_PDO_MAPPING, 0x00, FALSE, sizeof(rx_cnt), &rx_cnt, EC_TIMEOUTSAFE);

  // TxPDO (0x1A01) 상세 매핑: 모터 → PC로 받을 데이터
  // InPDO 구조체와 순서/크기가 정확히 일치해야 한다.
  uint8_t tx_cnt = 4;
  uint32_t tx_map[4] = {
    (static_cast<uint32_t>(EposReg::STATUS_WORD) << 16) | 0x0010,
    (static_cast<uint32_t>(EposReg::ACTUAL_POSITION) << 16) | 0x0020,
    (static_cast<uint32_t>(EposReg::ACTUAL_VELOCITY) << 16) | 0x0020,
    (static_cast<uint32_t>(EposReg::ACTUAL_TORQUE) << 16) | 0x0010
  };
  (void)ec_SDOwrite(slave, EposReg::TX_PDO_MAPPING, 0x00, FALSE, sizeof(zero), &zero, EC_TIMEOUTSAFE);
  for (int i = 0; i < 4; i++) {
    (void)ec_SDOwrite(slave, EposReg::TX_PDO_MAPPING, static_cast<uint8>(i + 1), FALSE, sizeof(tx_map[i]), &tx_map[i], EC_TIMEOUTSAFE);
  }
  (void)ec_SDOwrite(slave, EposReg::TX_PDO_MAPPING, 0x00, FALSE, sizeof(tx_cnt), &tx_cnt, EC_TIMEOUTSAFE);

  return 1;
}

}  // namespace epos_control
