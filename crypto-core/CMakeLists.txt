cmake_minimum_required(VERSION 3.20)

project(radh_crypto_core LANGUAGES C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

add_compile_options(
    "$<$<C_COMPILER_ID:GNU,Clang,AppleClang>:-Wall;-Wextra;-Wpedantic>"
    "$<$<C_COMPILER_ID:MSVC>:/W4>"
)

add_library(radh_crypto_core SHARED src/modexp.c src/rsa.c src/dh.c)
target_include_directories(radh_crypto_core PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/include")

# Eksport publicznych funkcji także przy budowaniu DLL.
set_target_properties(radh_crypto_core PROPERTIES WINDOWS_EXPORT_ALL_SYMBOLS ON)

include(CTest)
if(BUILD_TESTING)
    add_executable(radh_crypto_core_tests tests/crypto_core_test.c)
    target_link_libraries(radh_crypto_core_tests PRIVATE radh_crypto_core)
    add_test(NAME radh_crypto_core_tests COMMAND radh_crypto_core_tests)
endif()
