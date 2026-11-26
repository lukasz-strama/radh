cmake_minimum_required(VERSION 3.23)
project(RADHInspector VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

include(CTest)
include(FetchContent)
find_package(Threads REQUIRED)
find_package(CURL 7.85 REQUIRED)
find_package(nlohmann_json 3.11 QUIET)
if(NOT nlohmann_json_FOUND)
    FetchContent_Declare(nlohmann_json
        GIT_REPOSITORY https://github.com/nlohmann/json.git
        GIT_TAG 55f93686c01528224f448c19128836e7df245f72)
    FetchContent_MakeAvailable(nlohmann_json)
endif()

add_library(inspector-model STATIC src/event.cpp src/telemetry.cpp)
target_include_directories(inspector-model PUBLIC include)
target_link_libraries(inspector-model PUBLIC nlohmann_json::nlohmann_json CURL::libcurl Threads::Threads)

option(RADH_INSPECTOR_GUI "Zbuduj aplikację graficzną" ON)
if(RADH_INSPECTOR_GUI)
    FetchContent_Declare(cppfx
        GIT_REPOSITORY https://github.com/OryginalnaNazwa/CPPFX.git
        GIT_TAG 38cf694525cfa1ae0b997d94e84a98e1d997dceb)
    FetchContent_MakeAvailable(cppfx)

    add_executable(radh-inspector src/main.cpp src/inspector.cpp src/panels.cpp)
    target_link_libraries(radh-inspector PRIVATE inspector-model CPPFX::CPPFX)
    target_compile_definitions(radh-inspector PRIVATE RADH_INSPECTOR_VERSION="${PROJECT_VERSION}")
endif()

if(BUILD_TESTING)
    add_executable(inspector-tests tests/inspector_tests.cpp)
    target_link_libraries(inspector-tests PRIVATE inspector-model)
    add_test(NAME inspector-tests COMMAND inspector-tests)
    set_tests_properties(inspector-tests PROPERTIES TIMEOUT 15)
endif()
