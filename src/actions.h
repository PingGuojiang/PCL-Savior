#pragma once
#include "app_state.h"
namespace savior_ui {
using Completion = std::function<void(V)>;
void invoke(const std::string &command, const std::string &fields, Completion then,
            std::function<bool()> current = {});
void saveSettings();
void inspect(int index, const std::string &command = "inspect");
void setPath(int index, const std::string &path);
void browse(int index);
void loadReleases(int page = 1);
void download(int ri, int ai);
void checkUpdate();
} // namespace savior_ui
