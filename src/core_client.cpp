#define WIN32_LEAN_AND_MEAN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <shellapi.h>
#include <shlobj.h>
#include <filesystem>
#include <stdexcept>
#include <mutex>
#include <thread>
#include <cstdio>
#include "core_client.h"
#include "eui/json.h"
namespace savior {
std::wstring wide(const std::string &s) {
    if (s.empty())
        return {};
    int n = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s.data(), (int)s.size(), nullptr, 0);
    if (!n)
        throw std::runtime_error("无效 UTF-8 路径");
    std::wstring r(n, 0);
    MultiByteToWideChar(CP_UTF8, 0, s.data(), (int)s.size(), r.data(), n);
    return r;
}
std::string utf8(const std::wstring &s) {
    if (s.empty())
        return {};
    int n = WideCharToMultiByte(CP_UTF8, 0, s.data(), (int)s.size(), nullptr, 0, nullptr, nullptr);
    std::string r(n, 0);
    WideCharToMultiByte(CP_UTF8, 0, s.data(), (int)s.size(), r.data(), n, nullptr, nullptr);
    return r;
}
std::string quote(const std::string &s) {
    std::string r = "\"";
    for (unsigned char c : s) {
        switch (c) {
        case '"':
            r += "\\\"";
            break;
        case '\\':
            r += "\\\\";
            break;
        case '\n':
            r += "\\n";
            break;
        case '\r':
            r += "\\r";
            break;
        case '\t':
            r += "\\t";
            break;
        default:
            if (c < 32) {
                const char *h = "0123456789abcdef";
                r += "\\u00";
                r += h[c >> 4];
                r += h[c & 15];
            } else
                r += char(c);
        }
    }
    return r + '"';
}
std::string executableDirectory() {
    wchar_t path[32768];
    DWORD n = GetModuleFileNameW(nullptr, path, 32768);
    return utf8(std::filesystem::path(std::wstring(path, n)).parent_path().wstring());
}
struct Handle {
    HANDLE h = nullptr;
    ~Handle() {
        if (h && h != INVALID_HANDLE_VALUE)
            CloseHandle(h);
    }
    Handle() = default;
    Handle(const Handle &) = delete;
};
std::string callCore(const std::string &request,
                     const std::function<void(const std::string &)> &progress) {
    auto base = std::filesystem::path(wide(executableDirectory()));
    auto program = base / L"savior-core" / L"savior-core.exe";
    std::wstring args = L"\"" + program.wstring() + L"\"";
    auto cwd = base;
#ifdef SAVIOR_DEV_ROOT
    if (!std::filesystem::exists(program)) {
        cwd = std::filesystem::path(wide(SAVIOR_DEV_ROOT));
        program = cwd / L".venv" / L"Scripts" / L"python.exe";
        args = L"\"" + program.wstring() + L"\" -m savior";
        cwd /= L"core";
    }
#endif
    if (!std::filesystem::exists(program))
        throw std::runtime_error("缺少 savior-core/savior-core.exe，请重新安装完整应用。");
    static std::mutex spawnMutex;
    std::unique_lock<std::mutex> spawnLock(spawnMutex);
    SECURITY_ATTRIBUTES sa{sizeof(sa), nullptr, TRUE};
    Handle inRead, inWrite, outRead, outWrite, err;
    if (!CreatePipe(&inRead.h, &inWrite.h, &sa, 0) || !CreatePipe(&outRead.h, &outWrite.h, &sa, 0))
        throw std::runtime_error("无法建立核心通信管道");
    SetHandleInformation(inWrite.h, HANDLE_FLAG_INHERIT, 0);
    SetHandleInformation(outRead.h, HANDLE_FLAG_INHERIT, 0);
    // The core deliberately emits exception types only to stderr, never request bodies or signed URLs.
    // Keep diagnostics bounded while stdout remains exclusively the JSON protocol.
    wchar_t appData[MAX_PATH]{};
    std::filesystem::path logPath;
    if (SUCCEEDED(SHGetFolderPathW(nullptr, CSIDL_LOCAL_APPDATA, nullptr, SHGFP_TYPE_CURRENT, appData)))
        logPath = std::filesystem::path(appData) / L"PCL Savior" / L"logs" / L"core.log";
    else
        logPath = std::filesystem::temp_directory_path() / L"PCL Savior" / L"logs" / L"core.log";
    std::error_code logError;
    std::filesystem::create_directories(logPath.parent_path(), logError);
    auto logSize = std::filesystem::file_size(logPath, logError);
    DWORD disposition = !logError && logSize >= 1024 * 1024 ? CREATE_ALWAYS : OPEN_ALWAYS;
    err.h = CreateFileW(logPath.c_str(), FILE_APPEND_DATA,
                        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, &sa, disposition,
                        FILE_ATTRIBUTE_NORMAL, nullptr);
    if (err.h == INVALID_HANDLE_VALUE)
        throw std::runtime_error("无法创建核心诊断日志，请检查本地应用数据目录权限。");
    STARTUPINFOW si{};
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_HIDE;
    si.hStdInput = inRead.h;
    si.hStdOutput = outWrite.h;
    si.hStdError = err.h;
    PROCESS_INFORMATION pi{};
    if (!CreateProcessW(program.c_str(), args.data(), nullptr, nullptr, TRUE, CREATE_NO_WINDOW, nullptr,
                        cwd.c_str(), &si, &pi))
        throw std::runtime_error("核心进程启动失败，Windows 错误 " + std::to_string(GetLastError()));
    Handle process, thread;
    process.h = pi.hProcess;
    thread.h = pi.hThread;
    CloseHandle(inRead.h);
    inRead.h = nullptr;
    CloseHandle(outWrite.h);
    outWrite.h = nullptr;
    spawnLock.unlock();
    std::string payload = request + "\n";
    DWORD written = 0;
    if (!WriteFile(inWrite.h, payload.data(), (DWORD)payload.size(), &written, nullptr) ||
        written != payload.size())
        throw std::runtime_error("核心请求写入失败");
    CloseHandle(inWrite.h);
    inWrite.h = nullptr;
    std::string pending, result;
    char buf[4096];
    DWORD count = 0;
    while (ReadFile(outRead.h, buf, sizeof(buf), &count, nullptr) && count) {
        pending.append(buf, count);
        if (pending.size() > 8 * 1024 * 1024)
            throw std::runtime_error("核心响应过大");
        size_t pos;
        while ((pos = pending.find('\n')) != std::string::npos) {
            auto line = pending.substr(0, pos);
            pending.erase(0, pos + 1);
            eui::json::Document d;
            if (!d.parse(line))
                continue;
            std::string type;
            d.root().get("type").string(type);
            if (type == "progress") {
                if (progress)
                    progress(line);
            } else if (type == "result" || type == "error")
                result = line;
        }
    }
    WaitForSingleObject(process.h, INFINITE);
    if (result.empty())
        throw std::runtime_error("核心未返回有效结果");
    return result;
}
std::string localTimestamp() {
    SYSTEMTIME time{};
    GetLocalTime(&time);
    char output[32];
    std::snprintf(output, sizeof(output), "%04d-%02d-%02d %02d:%02d", time.wYear, time.wMonth, time.wDay,
                  time.wHour, time.wMinute);
    return output;
}
bool systemDark() {
    DWORD value = 1, size = sizeof(value);
    RegGetValueW(HKEY_CURRENT_USER, L"Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize",
                 L"AppsUseLightTheme", RRF_RT_REG_DWORD, nullptr, &value, &size);
    return value == 0;
}
// Registry notifications request a new UI composition without polling or mutating UI state.
void watchSystemTheme(std::function<void()> redraw) {
    struct Watcher {
        HANDLE stop = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        std::thread worker;
        explicit Watcher(std::function<void()> notify) {
            worker = std::thread([this, notify] {
                HKEY key = nullptr;
                if (RegOpenKeyExW(HKEY_CURRENT_USER,
                                  L"Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize",
                                  0, KEY_NOTIFY, &key) != ERROR_SUCCESS)
                    return;
                HANDLE changed = CreateEventW(nullptr, FALSE, FALSE, nullptr);
                HANDLE waits[] = {stop, changed};
                while (changed && RegNotifyChangeKeyValue(key, FALSE, REG_NOTIFY_CHANGE_LAST_SET,
                                                          changed, TRUE) == ERROR_SUCCESS) {
                    if (WaitForMultipleObjects(2, waits, FALSE, INFINITE) != WAIT_OBJECT_0 + 1)
                        break;
                    notify();
                }
                if (changed)
                    CloseHandle(changed);
                RegCloseKey(key);
            });
        }
        ~Watcher() {
            SetEvent(stop);
            if (worker.joinable())
                worker.join();
            CloseHandle(stop);
        }
    };
    static Watcher watcher(std::move(redraw));
}
std::string cancellationPath() {
    wchar_t buffer[32768];
    DWORD count = GetTempPathW(32768, buffer);
    if (!count || count >= 32768)
        throw std::runtime_error("无法访问临时目录");
    auto name = L"pcl-savior-cancel-" + std::to_wstring(GetCurrentProcessId()) + L"-" +
                std::to_wstring(GetTickCount64()) + L".flag";
    return utf8((std::filesystem::path(buffer) / name).wstring());
}
bool launch(const std::string &path, std::string &error) {
    auto p = std::filesystem::path(wide(path));
    std::wstring exe = p.wstring(), args;
    if (p.extension() == L".jar") {
        exe = L"javaw.exe";
        args = L"-jar \"" + p.wstring() + L"\"";
    }
    auto r = ShellExecuteW(nullptr, L"open", exe.c_str(), args.empty() ? nullptr : args.c_str(),
                           p.parent_path().c_str(), SW_SHOWNORMAL);
    if ((INT_PTR)r <= 32) {
        error = "无法启动，请检查程序或 Java 安装（错误 " + std::to_string((INT_PTR)r) + "）";
        return false;
    }
    return true;
}
std::string canonical(const std::string &path) {
    if (path.empty())
        return {};
    std::error_code ec;
    auto p = std::filesystem::weakly_canonical(std::filesystem::path(wide(path)), ec);
    auto s = (ec ? std::filesystem::path(wide(path)).lexically_normal() : p).wstring();
    CharLowerBuffW(s.data(), (DWORD)s.size());
    return utf8(s);
}
} // namespace savior
