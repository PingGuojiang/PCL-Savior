#include "actions.h"
namespace savior_ui {
void invoke(const std::string &command, const std::string &fields, Completion then,
            std::function<bool()> current) {
    const auto id = std::to_string(++sequence);
    const auto request = "{\"protocol\":1,\"id\":" + q(id) + ",\"command\":" + q(command) +
                         (fields.empty() ? "" : "," + fields) + "}";
    async::runOnce(
        "core." + id,
        [request, id]() {
            try {
                return async::success(savior::callCore(request, [id](const std::string &line) {
                    eui::json::Document document;
                    if (document.parse(line) && str(document.root(), "id") == id) {
                        std::lock_guard<std::mutex> lock(progressMutex);
                        progressQueue.emplace(id, integer(document.root().get("data"), "percent"));
                    }
                    app::requestUpdate();
                }));
            } catch (const std::exception &error) {
                return async::failure<std::string>(error.what());
            }
        },
        [then, id, current](const async::Result<std::string> &result) {
            // Completion and all application-state mutations run on EUI's UI thread.
            if (current && !current())
                return;
            auto &s = state();
            if (!result.ok) {
                s.message = result.error;
                then(V{});
                return;
            }
            eui::json::Document document;
            if (!document.parse(result.value) || str(document.root(), "id") != id ||
                integer(document.root(), "protocol") != 1) {
                s.message = "核心响应协议或请求标识不匹配";
                then(V{});
                return;
            }
            auto data = document.root().get("data");
            if (str(document.root(), "type") == "error") {
                s.message = str(data, "code") + " · " + str(data, "message");
                then(V{});
                return;
            }
            then(data);
        });
}
Inspection inspectData(V v) {
    auto status = str(v, "status");
    for (auto &c : status)
        if (c >= 'a' && c <= 'z')
            c = char(c - 'a' + 'A');
    return {status,
            str(v, "file_version"),
            str(v, "sha256"),
            str(v, "message"),
            boolean(v, "backup_available"),
            str(v, "launcher_name"),
            str(v, "assembly_version"),
            savior::localTimestamp()};
}
// Serialize preference snapshots: quick theme/path changes must not be persisted out of order.
void flushSettings() {
    auto &s = state();
    if (s.settingsSaving || s.settingsPending.empty())
        return;
    s.settingsSaving = true;
    auto fields = std::move(s.settingsPending);
    s.settingsPending.clear();
    invoke("settings", fields, [](V) {
        state().settingsSaving = false;
        flushSettings();
    });
}
void saveSettings() {
    auto &s = state();
    std::string paths = "{";
    for (int i = 0; i < 3; ++i) {
        if (i)
            paths += ",";
        paths += q(s.launchers[i].key) + ":" + q(s.launchers[i].path);
    }
    paths += "}";
    s.settingsPending = "\"action\":\"save\",\"preferences\":{\"theme\":" + q(s.theme) +
                        ",\"paths\":" + paths + ",\"download_directory\":" + q(s.directory) +
                        ",\"update_repo\":" + q(s.repo) + "}";
    flushSettings();
}
void inspect(int index, const std::string &command) {
    auto &l = state().launchers[index];
    if (l.path.empty() || l.busy)
        return;
    if (!state().deletingPath.empty() &&
        savior::canonical(l.path) == savior::canonical(state().deletingPath)) {
        state().message = "此启动器正在删除，请等待操作完成。";
        return;
    }
    const auto path = l.path;
    auto request = ++l.request;
    l.busy = true;
    if (command == "inspect")
        l.info = {};
    auto fields = "\"path\":" + q(path);
    if (command != "inspect")
        fields += ",\"expected_sha256\":" + q(l.info.sha);
    invoke(
        command, fields,
        [index, path, request, command](V v) {
            auto &s = state();
            auto &l = s.launchers[index];
            if (l.path != path || l.request != request)
                return;
            l.busy = false;
            if (v.valid()) {
                l.info = inspectData(v);
                const auto &detected = l.info.launcher;
                int actual = detected == "PCL2" || detected == "PCL" ? 0
                             : detected == "HMCL"                    ? 1
                             : detected == "PCL2 CE" || detected == "PCL CE" || detected == "PCL_CE"
                                 ? 2
                                 : -1;
                if (actual >= 0 && actual != index) {
                    l.info.status = "UNSUPPORTED";
                    l.info.message = "检测到 " + detected + "。当前选择为 " + l.name +
                                     "，请切换对应启动器分类并重新导入。";
                    l.info.backup = false;
                    l.info.matches = false;
                }
                s.message = command == "inspect" ? "文件检测完成"
                            : command == "patch" ? "修补完成 · 原文件已备份"
                                                 : "已还原原始文件";
            }
        },
        [index, path, request] {
            const auto &l = state().launchers[index];
            return l.path == path && l.request == request;
        });
}
void setPath(int index, const std::string &path) {
    auto &l = state().launchers[index];
    if (l.busy)
        return;
    l.path = path;
    l.info = {};
    ++l.request;
    saveSettings();
    inspect(index);
}
void browse(int index) {
    eui::platform::FileDialogOptions options;
    options.prompt = "选择本地启动器";
    options.allowedExtensions =
        index == 1 ? std::vector<std::string>{".exe", ".jar"} : std::vector<std::string>{".exe"};
    options.filterName = "启动器文件";
    auto r = eui::platform::openFileDialog(options);
    if (r.selected())
        setPath(index, r.paths.front());
    else if (r.status == eui::platform::FileDialogStatus::Failed)
        state().message = r.error;
}
void loadReleases(int page) {
    auto &s = state();
    s.loading = true;
    s.catalogPage = page;
    s.releases.clear();
    s.nextPage = 0;
    s.scroll.set(0);
    const char *official[] = {"https://github.com/Meloong-Git/PCL/releases",
                              "https://github.com/HMCL-dev/HMCL/releases",
                              "https://github.com/PCL-Community/PCL-CE/releases"};
    s.officialUrl = official[s.downloadTab];
    int tab = s.downloadTab, filter = s.filter;
    auto rid = ++s.catalogRequest;
    const char *filters[] = {"all", "stable", "preview", "local"};
    invoke(
        "releases",
        "\"launcher\":" + q(s.launchers[tab].key) + ",\"page\":" + std::to_string(page) +
            ",\"filter\":" + q(filters[filter]),
        [tab, filter, rid](V v) {
            auto &s = state();
            if (s.downloadTab != tab || s.filter != filter || s.catalogRequest != rid)
                return;
            s.loading = false;
            if (!v.valid())
                return;
            s.releases.clear();
            s.nextPage = integer(v, "next_page");
            s.officialUrl = str(v, "official_url");
            auto items = v.get("items");
            for (size_t i = 0; i < items.size(); ++i) {
                auto item = items.at(i);
                Release r;
                r.tag = str(item, "tag");
                r.date = str(item, "published_at");
                r.notes = str(item, "notes");
                r.url = str(item, "url");
                r.preview = boolean(item, "prerelease");
                r.latest = boolean(item, "latest");
                auto assets = item.get("assets");
                for (size_t j = 0; j < assets.size(); ++j) {
                    auto a = assets.at(j);
                    Asset x;
                    x.name = str(a, "name");
                    x.url = str(a, "url");
                    x.digest = str(a, "digest");
                    x.local = str(a, "local_path");
                    x.sha = str(a, "sha256");
                    a.get("size").number(x.size);
                    r.assets.push_back(x);
                }
                s.releases.push_back(std::move(r));
            }
            s.message = "版本列表已更新";
        },
        [tab, filter, rid] {
            const auto &s = state();
            return s.downloadTab == tab && s.filter == filter && s.catalogRequest == rid;
        });
}
void download(int ri, int ai) {
    auto &s = state();
    if (s.downloading)
        return;
    auto r = s.releases[ri];
    auto a = r.assets[ai];
    int tab = s.downloadTab;
    s.downloading = true;
    s.percent = 0;
    s.downloadLabel = a.name;
    s.cancelFile = savior::cancellationPath();
    std::error_code ec;
    std::filesystem::remove(std::filesystem::path(savior::wide(s.cancelFile)), ec);
    auto sentinel = s.cancelFile;
    invoke("download",
           "\"launcher\":" + q(s.launchers[tab].key) + ",\"tag\":" + q(r.tag) +
               ",\"asset\":{\"name\":" + q(a.name) + ",\"size\":" + std::to_string((long long)a.size) +
               ",\"url\":" + q(a.url) + ",\"digest\":" + q(a.digest) +
               "},\"directory\":" + q(s.directory) + ",\"cancel_file\":" + q(sentinel),
           [tab, sentinel](V v) {
               auto &s = state();
               s.downloading = false;
               std::error_code ec;
               std::filesystem::remove(std::filesystem::path(savior::wide(sentinel)), ec);
               if (v.valid()) {
                   s.message = "下载与文件校验完成 · " + str(v, "path");
                   if (s.downloadTab == tab)
                       loadReleases(s.catalogPage);
               }
           });
}
void checkUpdate() {
    auto &s = state();
    if (s.checking)
        return;
    s.checking = true;
    auto repo = s.repo;
    invoke("update", "\"repo\":" + q(repo) + ",\"current_version\":\"1.0.0-beta.1\"", [repo](V v) {
        auto &s = state();
        s.checking = false;
        if (s.repo != repo || !v.valid())
            return;
        s.hasUpdate = boolean(v, "update_available");
        s.updateUrl = str(v, "url");
        s.updateVersion = str(v, "version");
        s.updateNotes = str(v, "notes");
        s.updateStatus = !boolean(v, "configured") ? "尚未配置更新仓库"
                         : s.hasUpdate             ? "发现新版本 " + s.updateVersion
                                                   : "当前版本已是最新版本";
    });
}
} // namespace savior_ui
