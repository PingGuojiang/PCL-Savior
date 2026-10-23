#include "pages.h"
namespace savior_ui {
void home(Painter &p) {
    auto &s = state();
    auto &l = s.launchers[s.selected];
    p.text("home.kicker", 0, 0, p.w, "REPAIR CENTER  /  修补中心", 12, true);
    p.text("home.title", 0, 27, p.w, "主页 · 启动器修补中心", 22, false, 36);
    p.text("home.sub", 0, 68, p.w, "选择启动器、确认文件，再安全修复下载功能。", 13, true);
    float cw = (p.w - 24) / 3;
    for (int i = 0; i < 3; ++i) {
        auto &a = s.launchers[i];
        float x = i * (cw + 12);
        p.ui.rect("launcher.bg" + std::to_string(i))
            .position(x, 100)
            .size(cw, 92)
            .color(p.t.surface)
            .radius(12)
            .border(s.selected == i ? 2 : 1, s.selected == i ? p.t.primary : p.t.border)
            .onClick([i] { state().selected = i; })
            .build();
        p.ui.image("launcher.icon" + std::to_string(i))
            .position(x + 14, 111)
            .size(36, 36)
            .source("assets/icons/" + a.icon)
            .build();
        p.text("launcher.name" + std::to_string(i), x + 62, 117, cw - 72, a.name, 16);
        p.text("launcher.version" + std::to_string(i), x + 14, 151, cw - 28,
               a.info.version.empty() ? "未检测版本" : a.info.version, 12, true);
        p.text("launcher.state" + std::to_string(i), x + 14, 172, cw - 28,
               s.selected == i ? "当前选择" : "点击选择", 11, true);
    }
    p.text("home.step2", 0, 207, p.w, "02  当前文件状态", 13, true);
    p.card("home.status", 237, 125);
    bool patched = l.info.status == "PATCHED", native = l.info.status == "NATIVE";
    std::string headline = l.busy                           ? "正在处理，请稍候…"
                           : l.path.empty()                 ? "等待选择启动器"
                           : patched                        ? "已修补 · 文件验证通过"
                           : native                         ? "原生支持 · 无需修补"
                           : l.info.status == "PATCHABLE"   ? "可修补 · 已匹配受支持规则"
                           : l.info.status == "UNSUPPORTED" ? "不支持修改此文件"
                                                            : "等待检测文件";
    p.ui.image("home.status.icon")
        .position(16, 253)
        .size(46, 46)
        .source(std::string("assets/icons/") +
                (patched || native ? (p.t.dark ? "wifi_on.svg" : "wifi_on_light.svg")
                                   : (p.t.dark ? "wifi_off.svg" : "wifi_off_light.svg")))
        .build();
    p.text("home.status.title", 78, 250, p.w - 96, headline, 18);
    p.text("home.status.detail", 78, 282, p.w - 96,
           l.info.message.empty() ? "仅根据文件规则判断修补状态。" : l.info.message, 11, true, 28);
    p.text("home.status.network", 16, 319, p.w - 36, "网络连通性未独立测试 · 已修补不代表网络畅通", 12,
           true);
    p.text("home.step3", 0, 376, p.w, "03  确认启动器位置", 13, true);
    p.card("home.actions", 403, 132);
    components::input(p.ui, "home.path")
        .position(16, 416)
        .size(p.w - 130, 38)
        .fontSize(12)
        .theme(p.t)
        .value(l.path)
        .placeholder("选择 .exe / .jar 启动器文件")
        .onChange([](const std::string &value) {
            auto &s = state();
            auto &l = s.launchers[s.selected];
            if (l.busy)
                return;
            l.path = value;
            l.info = {};
            ++l.request;
        })
        .onEnter([] {
            saveSettings();
            inspect(state().selected);
        })
        .build();
    p.button(
        "home.browse", p.w - 104, 417, 88, "浏览文件", [] { browse(state().selected); }, false, l.busy);
    p.text("home.backup", 16, 460, p.w - 32, "每次修补前强制备份；仅允许验证通过的备份还原。", 12, true);
    p.button(
        "home.patch", 16, 489, 154,
        patched  ? "已修补"
        : native ? "无需修补"
                 : "立即修补",
        [] { inspect(state().selected, "patch"); }, true, l.busy || l.info.status != "PATCHABLE");
    p.button(
        "home.inspect", 180, 489, 92, "重新检测",
        [] {
            saveSettings();
            inspect(state().selected);
        },
        false, l.busy || l.path.empty());
    p.button(
        "home.launch", 282, 489, 92, "测试启动",
        [] {
            std::string error;
            if (!savior::launch(state().launchers[state().selected].path, error))
                state().message = error;
            else
                state().message = "已请求系统启动；网络连通性未测试";
        },
        false, l.busy || l.path.empty() || !l.info.matches);
    p.button(
        "home.restore", 384, 489, 110, "还原备份", [] { inspect(state().selected, "restore"); }, false,
        l.busy || !l.info.backup);
    p.text("home.inspection.meta", 16, 539, p.w - 32,
           l.info.detectedAt.empty()
               ? "尚未检测"
               : "检测于 " + l.info.detectedAt + " · 程序集 " +
                     (l.info.assemblyVersion.empty() ? "—" : l.info.assemblyVersion),
           10, true, 18);
    p.text("home.sha", 16, 341, p.w - 32, "SHA-256  " + (l.info.sha.empty() ? "—" : l.info.sha), 10,
           true, 18);
}
} // namespace savior_ui
