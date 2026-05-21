// epos_registers.hpp — EPOS4 EtherCAT Object Dictionary 주소
#pragma once

#include <cstdint>

namespace EposReg {
  constexpr uint16_t RX_PDO_MAPPING     = 0x1601;
  constexpr uint16_t TX_PDO_MAPPING     = 0x1A01;
  constexpr uint16_t SM2_PDO_ASSIGN     = 0x1C12;
  constexpr uint16_t SM3_PDO_ASSIGN     = 0x1C13;
  constexpr uint16_t SYNC_MANAGER_PARAM = 0x1C32;

  constexpr uint16_t ERROR_CODE         = 0x603F;
  constexpr uint16_t CONTROL_WORD       = 0x6040;
  constexpr uint16_t STATUS_WORD        = 0x6041;
  constexpr uint16_t FAULT_REACTION     = 0x605E;
  constexpr uint16_t MODE_OF_OPERATION  = 0x6060;
  constexpr uint16_t ACTUAL_POSITION    = 0x6064;
  constexpr uint16_t ACTUAL_VELOCITY    = 0x606C;
  constexpr uint16_t TARGET_TORQUE      = 0x6071;
  constexpr uint16_t ACTUAL_TORQUE      = 0x6077;
  constexpr uint16_t TARGET_POSITION    = 0x607A;
  constexpr uint16_t TARGET_VELOCITY    = 0x60FF;
  constexpr uint16_t ABORT_CONNECTION   = 0x6007;
}

