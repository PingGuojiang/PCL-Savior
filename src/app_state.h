#pragma once
#include "eui_neo.h"
#include "eui/async.h"
#include "core_client.h"
#include <array>
#include <atomic>
#include <filesystem>
#include <fstream>
#include <functional>
#include <mutex>
#include <queue>
#include <sstream>
#include <iomanip>
namespace savior_ui {
namespace async = app::async;
using V = eui::json::Value;
inline std::string str(V v, const std::string &key) {
    std::string r;
    v.get(key).string(r);
    return r;
}
inline bool boolean(V v, const std::string &key) {
    bool r = false;
    v.get(key).boolean(r);
    return r;
}
inline int integer(V v, const std::string &key) {
    double r = 0;
    v.get(key).number(r);
    return (int)r;
}
inline std::string q(const std::string &s) { return savior::quote(s); }
struct Inspection {
    std::string status, version, sha, message;
    bool backup = false;
    std::string launcher, assemblyVersion, detectedAt;
    bool matches = true;
};
struct Launcher {
    std::string key, name, full, icon, path;
    Inspection info;
    bool busy = false;
    unsigned request = 0;
};
struct Asset {
    std::string name, url, digest, local, sha;
    double size = 0;
};
struct Release {
    std::string tag, date, notes, url;
    bool preview = false, latest = false, expanded = false;
    std::vector<Asset> assets;
};
struct State {
    std::array<Launcher, 3> launchers{
        {{"PCL", "PCL", "Plain Craft Launcher 2", "pcl_logo.png"},
         {"HMCL", "HMCL", "Hello Minecraft! Launcher", "hmcl_logo.png"},
         {"PCL_CE", "PCL CE", "PCL Community Edition", "pcl_ce_logo.png"}}};
    int page = 0, selected = 0, downloadTab = 0, filter = 0, catalogPage = 1, nextPage = 0;
    unsigned catalogRequest = 0;
    bool settingsSaving = false, initialized = false, loading = false, downloading = false,
         checking = false, hasUpdate = false, deleteOpen = false, downloadNoticeOpen = false;
    std::string settingsPending, theme = "system", directory, repo, updateUrl, updateVersion,
                                 updateNotes, updateStatus = "配置项目仓库后检查更新",
                                 message = "准备就绪 · 请选择本地启动器", officialUrl, cancelFile,
                                 downloadLabel, deletePath, deleteSha, deletingPath;
    int percent = 0;
    std::vector<Release> releases;
    eui::Signal<float> scroll{0};
};
inline State &state() {
    static State s;
    return s;
}
inline std::atomic<unsigned> sequence{0};
inline std::mutex progressMutex;
inline std::queue<std::pair<std::string, int>> progressQueue;
} // namespace savior_ui
