# wows_renderer —— WoWS 模型查看器 D3D11 渲染后端（P0 骨架）
#
# 用法（在项目根目录）：
#   cmake -S native -B native/build
#   cmake --build native/build --config Release
#
# 产物：release/wows_renderer.dll
# 依赖：MSVC 工具链 + Windows SDK（提供 d3d11.h / dxgi1_2.h / fxc.exe）
#
# HLSL 采用「构建期 fxc → 生成 C 头（内嵌字节码）」方式：
# 运行期无 d3dcompiler 依赖，启动更快、打包更简单（见架构文档 §11.1）。

cmake_minimum_required(VERSION 3.20)
project(wows_renderer LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

set(WSR_PROJECT_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/..")
if(NOT DEFINED WSR_OUTPUT_DIR)
    set(WSR_OUTPUT_DIR "${WSR_PROJECT_ROOT}/release")
endif()
file(MAKE_DIRECTORY "${WSR_OUTPUT_DIR}")

# ---------------------------------------------------------------- fxc
find_program(FXC_EXECUTABLE NAMES fxc fxc.exe)
if(NOT FXC_EXECUTABLE)
    message(STATUS "fxc not in PATH - searching Windows SDK ...")
    set(_wsr_sdk_roots)
    if(DEFINED ENV{WindowsSdkDir} AND EXISTS "$ENV{WindowsSdkDir}")
        list(APPEND _wsr_sdk_roots "$ENV{WindowsSdkDir}")
    endif()
    foreach(_hive
            "HKEY_LOCAL_MACHINE\\SOFTWARE\\WOW6432Node\\Microsoft\\Microsoft SDKs\\Windows\\v10.0"
            "HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Microsoft SDKs\\Windows\\v10.0")
        get_filename_component(_root "[${_hive};InstallationFolder]" ABSOLUTE)
        if(_root AND EXISTS "${_root}")
            list(APPEND _wsr_sdk_roots "${_root}")
        endif()
    endforeach()
    foreach(_root IN LISTS _wsr_sdk_roots)
        file(GLOB _fxcs "${_root}/bin/10.*/x64/fxc.exe")
        if(_fxcs)
            list(SORT _fxcs)
            list(REVERSE _fxcs)
            list(GET _fxcs 0 FXC_EXECUTABLE)
            break()
        endif()
    endforeach()
endif()
if(NOT FXC_EXECUTABLE)
    message(FATAL_ERROR
        "fxc.exe not found. Install the Windows 10/11 SDK, or configure with -DFXC_EXECUTABLE=<path>.")
endif()
message(STATUS "fxc: ${FXC_EXECUTABLE}")

# ------------------------------------------------------------- library
add_library(wows_renderer SHARED
    src/renderer.cpp
)

target_include_directories(wows_renderer PRIVATE include)
target_compile_definitions(wows_renderer PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)
if(MSVC)
    target_compile_options(wows_renderer PRIVATE /utf-8 /W4 /permissive-)
endif()
target_link_libraries(wows_renderer PRIVATE d3d11 dxgi)

# ------------------------------------------------- HLSL -> C header
set(WSR_SHADER_OUT "${CMAKE_CURRENT_BINARY_DIR}/generated")
file(MAKE_DIRECTORY "${WSR_SHADER_OUT}")

# wows_compile_shader(<hlsl> <entry> <profile> <out_header> <symbol>)
function(wows_compile_shader hlsl entry profile out_header symbol)
    add_custom_command(
        OUTPUT "${out_header}"
        COMMAND "${FXC_EXECUTABLE}" /nologo /T ${profile} /E ${entry}
                /Fh "${out_header}" /Vn ${symbol} "${hlsl}"
        DEPENDS "${hlsl}"
        COMMENT "fxc ${profile} ${entry} -> ${out_header}"
        VERBATIM)
endfunction()

set(WSR_SHADER_SRC "${CMAKE_CURRENT_SOURCE_DIR}/shaders/material.hlsl")
set(WSR_VS_HEADER "${WSR_SHADER_OUT}/material_vs.h")
set(WSR_PS_HEADER "${WSR_SHADER_OUT}/material_ps.h")
set(WSR_PS_MRT_HEADER "${WSR_SHADER_OUT}/material_ps_mrt.h")
set(WSR_FS_VS_HEADER "${WSR_SHADER_OUT}/fullscreen_vs.h")
set(WSR_FS_PS_HEADER "${WSR_SHADER_OUT}/fullscreen_ps.h")

wows_compile_shader("${WSR_SHADER_SRC}" VSMain vs_5_0 "${WSR_VS_HEADER}" g_material_vs_bytes)
wows_compile_shader("${WSR_SHADER_SRC}" PSMain ps_5_0 "${WSR_PS_HEADER}" g_material_ps_bytes)
wows_compile_shader("${WSR_SHADER_SRC}" PSMainMRT ps_5_0 "${WSR_PS_MRT_HEADER}" g_material_ps_mrt_bytes)
wows_compile_shader("${WSR_SHADER_SRC}" VSFullscreen vs_5_0 "${WSR_FS_VS_HEADER}" g_fullscreen_vs_bytes)
wows_compile_shader("${WSR_SHADER_SRC}" PSFullscreen ps_5_0 "${WSR_FS_PS_HEADER}" g_fullscreen_ps_bytes)

set_source_files_properties("${WSR_VS_HEADER}" "${WSR_PS_HEADER}" "${WSR_PS_MRT_HEADER}"
    "${WSR_FS_VS_HEADER}" "${WSR_FS_PS_HEADER}"
    PROPERTIES GENERATED TRUE HEADER_FILE_ONLY TRUE)

target_sources(wows_renderer PRIVATE "${WSR_VS_HEADER}" "${WSR_PS_HEADER}"
    "${WSR_PS_MRT_HEADER}" "${WSR_FS_VS_HEADER}" "${WSR_FS_PS_HEADER}")
target_include_directories(wows_renderer PRIVATE "${WSR_SHADER_OUT}")

# ------------------------------------------------------------ output
foreach(_cfg IN ITEMS DEBUG RELEASE RELWITHDEBINFO MINSIZEREL)
    set_target_properties(wows_renderer PROPERTIES
        "RUNTIME_OUTPUT_DIRECTORY_${_cfg}" "${WSR_OUTPUT_DIR}"
        "LIBRARY_OUTPUT_DIRECTORY_${_cfg}" "${WSR_OUTPUT_DIR}"
        "ARCHIVE_OUTPUT_DIRECTORY_${_cfg}" "${WSR_OUTPUT_DIR}")
endforeach()
set_target_properties(wows_renderer PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${WSR_OUTPUT_DIR}"
    LIBRARY_OUTPUT_DIRECTORY "${WSR_OUTPUT_DIR}"
    ARCHIVE_OUTPUT_DIRECTORY "${WSR_OUTPUT_DIR}"
    OUTPUT_NAME "wows_renderer")

message(STATUS "wows_renderer output dir: ${WSR_OUTPUT_DIR}")
