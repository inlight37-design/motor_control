// epos_setup.hpp — EPOS4 EtherCAT PDO/SDO 초기 설정
#pragma once

extern "C" {
#include "ethercat.h"
}

namespace epos_control {

// SOEM이 Pre-OP → Safe-OP 전환 중 PO2SOconfig 콜백으로 호출한다.
int setup_epos_pdo_mapping(uint16 slave);

}  // namespace epos_control

