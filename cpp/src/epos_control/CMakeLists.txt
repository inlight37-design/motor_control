cmake_minimum_required(VERSION 3.8)
project(epos_control)
if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
endif()
find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)
find_package(std_srvs REQUIRED)
find_package(epos_interfaces REQUIRED)
find_package(soem REQUIRED)

# 실행 파일 이름: GUI의 EPOS_NODE_EXECUTABLE 값과 맞춰야 한다.
add_executable(epos_motor_node
  src/epos_motor_node.cpp
  src/epos_setup.cpp
)

target_include_directories(epos_motor_node PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/include)

ament_target_dependencies(epos_motor_node
  rclcpp
  std_msgs
  std_srvs
  epos_interfaces
  soem
)

set_target_properties(epos_motor_node PROPERTIES
  INSTALL_RPATH_USE_LINK_PATH TRUE
  INSTALL_RPATH "/opt/ros/jazzy/lib;${CMAKE_INSTALL_PREFIX}/lib"
)

install(TARGETS epos_motor_node
  DESTINATION lib/${PROJECT_NAME})

ament_package()
