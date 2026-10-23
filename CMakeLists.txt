cmake_minimum_required(VERSION 3.20)
project(PCLSavior VERSION 1.0.0 LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
option(SAVIOR_DEVELOPMENT_CORE "Allow the absolute development Python interpreter fallback" OFF)
set(EUI_BUILD_APPS OFF CACHE BOOL "" FORCE)
set(EUI_BUILD_USER_APPS OFF CACHE BOOL "" FORCE)
set(EUI_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(EUI_WINDOW_BACKEND glfw CACHE STRING "" FORCE)
set(EUI_RENDER_BACKEND opengl CACHE STRING "" FORCE)
# Pinned SDK: sudoevolve/EUI-NEO 1647709068e36834ab26da5a97ef4ad98aa34c9d
execute_process(COMMAND git rev-parse HEAD WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/third_party/EUI-NEO" OUTPUT_VARIABLE EUI_REV OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)
if(EUI_REV AND NOT EUI_REV STREQUAL "1647709068e36834ab26da5a97ef4ad98aa34c9d")
 message(FATAL_ERROR "Unexpected EUI-NEO checkout: ${EUI_REV}")
endif()
add_subdirectory(third_party/EUI-NEO)
# FreeType is linked statically; its DLL version resource is unnecessary. Older
# windres preprocessors mishandle include paths containing spaces in that file.
if(MINGW AND TARGET freetype)
 get_target_property(FREETYPE_APP_SOURCES freetype SOURCES)
 list(FILTER FREETYPE_APP_SOURCES EXCLUDE REGEX "[.]rc$")
 set_property(TARGET freetype PROPERTY SOURCES "${FREETYPE_APP_SOURCES}")
endif()
add_executable(pcl_savior WIN32 src/main.cpp src/core_client.cpp src/actions.cpp
 src/pages/home_page.cpp src/pages/download_page.cpp src/pages/about_page.cpp)
eui_neo_configure_app(pcl_savior)
# Use our authored shield. Link a prebuilt RES rather than asking windres to
# spawn a C preprocessor under a toolchain/workspace path containing spaces.
get_target_property(SAVIOR_APP_SOURCES pcl_savior SOURCES)
list(FILTER SAVIOR_APP_SOURCES EXCLUDE REGEX "[.]rc$")
set_property(TARGET pcl_savior PROPERTY SOURCES "${SAVIOR_APP_SOURCES}")
if(MINGW)
 set(SAVIOR_ICON_OBJECT "${CMAKE_CURRENT_BINARY_DIR}/savior_icon.obj")
 add_custom_command(OUTPUT "${SAVIOR_ICON_OBJECT}"
  COMMAND "${CMAKE_RC_COMPILER}" --input-format=res --output-format=coff
   "${CMAKE_CURRENT_SOURCE_DIR}/assets/app.res" "${SAVIOR_ICON_OBJECT}"
  DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/assets/app.res" VERBATIM)
 set_source_files_properties("${SAVIOR_ICON_OBJECT}" PROPERTIES GENERATED TRUE EXTERNAL_OBJECT TRUE)
 target_sources(pcl_savior PRIVATE "${SAVIOR_ICON_OBJECT}")
elseif(MSVC)
 target_link_libraries(pcl_savior PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/assets/app.res")
endif()
target_link_libraries(pcl_savior PRIVATE shell32 advapi32)
if(MSVC)
 target_compile_options(pcl_savior PRIVATE /utf-8 /EHsc)
else()
 # The bridge catches filesystem/process failures and reports them to the UI.
 target_compile_options(pcl_savior PRIVATE $<$<COMPILE_LANGUAGE:CXX>:-fexceptions>)
endif()
if(SAVIOR_DEVELOPMENT_CORE)
 target_compile_definitions(pcl_savior PRIVATE SAVIOR_DEV_ROOT="${CMAKE_CURRENT_SOURCE_DIR}")
endif()
set_target_properties(pcl_savior PROPERTIES OUTPUT_NAME "PCL Savior")
add_custom_command(TARGET pcl_savior POST_BUILD COMMAND ${CMAKE_COMMAND} -E copy_directory "${CMAKE_CURRENT_SOURCE_DIR}/assets" "$<TARGET_FILE_DIR:pcl_savior>/assets")
