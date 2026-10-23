#pragma once
#include <string>
#include <functional>
namespace savior {
std::string quote(const std::string &value);
std::wstring wide(const std::string &value);
std::string utf8(const std::wstring &value);
std::string callCore(const std::string &request,
                     const std::function<void(const std::string &)> &progress = {});
std::string executableDirectory();
bool systemDark();
std::string localTimestamp();
void watchSystemTheme(std::function<void()> redraw);
std::string cancellationPath();
bool launch(const std::string &path, std::string &error);
std::string canonical(const std::string &path);
} // namespace savior
