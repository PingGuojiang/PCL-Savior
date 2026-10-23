#include "pages/pages.h"
namespace app {
using namespace savior_ui;
const DslAppConfig &dslAppConfig() {
    static auto c = DslAppConfig{}
                        .title("PCL Savior")
                        .pageId("pcl_savior")
                        .appId("pcl_savior")
                        .iconPath("assets/app.png")
                        .windowSize(960, 640)
                        .minWindowSize(840, 560)
                        .showDebugStatsInTitle(false)
                        .showDebugOverlay(false);
    return c;
}
void compose(eui::Ui &ui, const eui::Screen &screen) {
    auto &s = state();
    if (!s.initialized) {
        s.initialized = true;
        savior::watchSystemTheme([] { app::requestUpdate(); });
        invoke("settings", "\"action\":\"get\"", [](V data) {
            if (!data.valid())
                return;
            auto &s = state();
            auto v = data.get("preferences");
            if (!v.valid())
                v = data;
            auto theme = str(v, "theme");
            if (theme == "dark" || theme == "light" || theme == "system")
                s.theme = theme;
            s.directory = str(v, "download_directory");
            s.repo = str(v, "update_repo");
            auto paths = v.get("paths");
            for (int i = 0; i < 3; ++i) {
                s.launchers[i].path = str(paths, s.launchers[i].key);
                if (!s.launchers[i].path.empty())
                    inspect(i);
            }
            s.message = "设置已载入 · 请选择启动器";
        });
    }
    {
        std::lock_guard<std::mutex> lock(progressMutex);
        while (!progressQueue.empty()) {
            s.percent = std::clamp(progressQueue.front().second, 0, 100);
            progressQueue.pop();
        }
    }
    bool dark = s.theme == "dark" || (s.theme == "system" && savior::systemDark());
    auto t = dark ? components::theme::dark() : components::theme::light();
    t.background = color(dark ? 0x0f141c : 0xf4f6f9);
    t.surface = color(dark ? 0x1c2536 : 0xffffff);
    t.text = color(dark ? 0xf8fafc : 0x0f172a);
    t.border = color(dark ? 0x2a364b : 0xe2e8f0);
    t.primary = color(dark ? 0x3b82f6 : 0x2563eb);
    ui.rect("window.bg").size(screen.width, screen.height).color(t.background).build();
    ui.rect("sidebar.bg").size(220, screen.height).color(color(dark ? 0x151c28 : 0xffffff)).build();
    ui.image("sidebar.logo").position(22, 28).size(36, 36).source("assets/icons/shield.svg").build();
    Painter side{ui, t, 188};
    side.text("sidebar.title", 70, 26, 145, "PCL Savior", 18);
    side.text("sidebar.tag", 70, 53, 145, "REPAIR TOOL", 10, true);
    side.text("sidebar.menu", 24, 116, 172, "工作空间", 11, true);
    const char *nav[] = {"主页 · 修补中心", "版本下载 · 版本库", "关于 · 项目信息"};
    const char *navIcons[] = {"home", "download", "info"};
    for (int i = 0; i < 3; ++i) {
        side.button(
            "nav." + std::to_string(i), 16, 148 + i * 54.f, 188, nav[i],
            [i] {
                auto &s = state();
                if (i == 1 && s.page != 1)
                    s.downloadNoticeOpen = true;
                s.page = i;
                s.scroll.set(0);
                if (i == 1 && s.releases.empty())
                    loadReleases();
                if (i == 2 && !s.repo.empty() && s.updateStatus == "配置项目仓库后检查更新")
                    checkUpdate();
            },
            s.page == i);
        ui.image("nav.icon." + std::to_string(i))
            .position(26, 156 + i * 54.f)
            .size(20, 20)
            .source(std::string("assets/icons/") + navIcons[i] + (s.page == i ? "_active" : "") + ".svg")
            .build();
    }
    side.text("sidebar.theme", 24, screen.height - 126, 172, "外观模式", 11, true);
    const char *themes[] = {"system", "light", "dark"};
    const char *themeLabels[] = {"系统", "亮色", "暗色"};
    for (int i = 0; i < 3; ++i)
        side.button(
            "theme." + std::to_string(i), 16 + i * 64.f, screen.height - 95, 60, themeLabels[i],
            [i] {
                const char *themes[] = {"system", "light", "dark"};
                state().theme = themes[i];
                saveSettings();
            },
            s.theme == themes[i]);
    side.text("sidebar.version", 24, screen.height - 43, 172, "苹果匠  /  v1.0.0-beta.1", 10, true);
    float stageWidth = screen.width - 276;
    float contentHeight = s.page == 0   ? 560
                          : s.page == 1 ? downloadsHeight() + (s.downloading ? 110 : 0)
                                        : (s.updateNotes.empty() ? 780 : 992);
    components::scrollView(ui, "main.scroll")
        .position(248, 25)
        .size(stageWidth, screen.height - 95)
        .theme(t)
        .bind(s.scroll)
        .step(52)
        .contentKey("page." + std::to_string(s.page) + ".height." + std::to_string(contentHeight))
        .content([&](eui::Ui &body, float w, float) {
            body.stack("page.canvas")
                .size(w, contentHeight)
                .content([&] {
                    Painter p{body, t, w};
                    if (s.page == 0)
                        home(p);
                    else if (s.page == 1)
                        downloads(p);
                    else
                        about(p);
                })
                .build();
        })
        .build();
    ui.rect("status.bg")
        .position(220, screen.height - 49)
        .size(screen.width - 220, 49)
        .color(t.surface)
        .build();
    side.text("status.message", 244, screen.height - 36, screen.width - 262, s.message, 12, true, 30);
    if (s.downloadNoticeOpen)
        components::dialog(ui, "download.experimental.notice")
            .open(true)
            .screen(screen.width, screen.height)
            .size(std::min(540.f, screen.width - 48.f), 288)
            .theme(t)
            .title("版本下载 · 测试功能")
            .message("版本下载目前为测试功能，可能出现列表加载或文件下载失败。\n\n"
                     "建议前往启动器官方渠道下载，获取最新版本与发布说明。")
            .primaryText("前往官方下载")
            .secondaryText("继续体验")
            .onOpenChange([](bool value) { state().downloadNoticeOpen = value; })
            .onSecondary([] { state().downloadNoticeOpen = false; })
            .onPrimary([] {
                auto &s = state();
                const char *official[] = {"https://meloong.com/pcl",
                                         "https://github.com/HMCL-dev/HMCL/releases",
                                         "https://github.com/PCL-Community/PCL-CE/releases"};
                eui::platform::openUrl(official[s.downloadTab]);
                s.downloadNoticeOpen = false;
            })
            .build();
    if (s.deleteOpen)
        components::dialog(ui, "delete.confirm")
            .open(true)
            .screen(screen.width, screen.height)
            .size(590, 320)
            .theme(t)
            .title("确认删除受管理的启动器文件？")
            .message("将永久删除以下启动器文件；不会移除游戏目录。\n\n" + s.deletePath)
            .primaryText("确认删除")
            .secondaryText("保留文件")
            .onSecondary([] { state().deleteOpen = false; })
            .onOpenChange([](bool value) { state().deleteOpen = value; })
            .onPrimary([] {
                auto &s = state();
                auto path = s.deletePath, sha = s.deleteSha;
                s.deleteOpen = false;
                s.deletingPath = path;
                invoke("delete", "\"path\":" + q(path) + ",\"expected_sha256\":" + q(sha), [path](V v) {
                    state().deletingPath.clear();
                    if (!v.valid())
                        return;
                    auto &s = state();
                    for (auto &l : s.launchers) {
                        if (savior::canonical(l.path) == savior::canonical(path)) {
                            l.path.clear();
                            l.info = {};
                            l.busy = false;
                            ++l.request;
                        }
                    }
                    saveSettings();
                    s.message = "启动器文件已删除";
                    loadReleases(s.catalogPage);
                });
            })
            .build();
}
} // namespace app
