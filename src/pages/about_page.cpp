#include "pages.h"
namespace savior_ui {
void about(Painter &p) {
    auto &s = state();
    p.text("about.kicker", 0, 0, p.w, "ABOUT  /  关于项目", 12, true);
    p.text("about.title", 0, 27, p.w, "关于 · 项目信息与更新", 22, false, 36);
    p.text("about.sub", 0, 68, p.w, "PCL Savior · 透明、安全、可还原", 13, true);
    p.card("about.brand", 111, 155);
    p.ui.image("about.logo").position(20, 132).size(55, 55).source("assets/icons/shield.svg").build();
    p.text("about.name", 91, 130, p.w - 110, "PCL Savior", 23);
    p.text("about.author", 91, 168, p.w - 110, "作者：苹果匠   ·   1.0.0-beta.1", 13, true);
    p.button("about.eui", 20, 211, 166, "EUI-NEO 开源框架",
             [] { eui::platform::openUrl("https://github.com/sudoevolve/EUI-NEO"); });
    p.button("about.licenses", 198, 211, 132, "第三方许可", [] {
        eui::platform::openUrl("file:///" + savior::executableDirectory() + "/THIRD_PARTY_NOTICES.md");
    });
    p.card("about.disclaimer", 286, 132);
    p.ui.rect("about.warning").position(0, 301).size(4, 100).color(color(0xd97706)).radius(2).build();
    p.text("about.disclaimer.title", 20, 302, p.w - 40, "免责声明", 16);
    p.text("about.disclaimer.text", 20, 336, p.w - 40,
           "此程序皆在修复启动器下载功能，请遵守当地法律，此程序与原启动器作者无关。", 13, false, 64);
    p.card("about.update", 438, 251);
    p.text("about.update.title", 20, 456, p.w - 40, "版本与更新", 16);
    p.text("about.update.status", 20, 488, p.w - 40,
           s.checking ? "正在检查 GitHub 发布…" : s.updateStatus, 13, true);
    components::input(p.ui, "about.repo")
        .position(20, 527)
        .size(p.w - 40, 37)
        .fontSize(12)
        .theme(p.t)
        .value(s.repo)
        .placeholder("更新仓库：owner/repository（由项目发布者提供）")
        .onChange([](const std::string &value) {
            state().repo = value;
            state().hasUpdate = false;
            state().updateUrl.clear();
            state().updateStatus = "仓库已更改，请重新检查";
        })
        .build();
    p.button(
        "about.check", 20, 582, 146, "保存并检查更新",
        [] {
            saveSettings();
            checkUpdate();
        },
        true, s.checking);
    p.button(
        "about.open", 180, 582, 150, "前往新版发布页",
        [] {
            if (!state().updateUrl.empty())
                eui::platform::openUrl(state().updateUrl);
        },
        false, !s.hasUpdate || s.updateUrl.empty());
    p.text("about.update.notes", 20, 637, p.w - 40, "更新仅打开官方发布页，由你确认下载与替换。", 12,
           true);
    p.text("about.attribution", 0, 715, p.w, "PCL、HMCL、PCL CE 的名称与图标归属各自项目及维护者。", 12,
           true, 42);
    if (!s.updateNotes.empty()) {
        p.card("about.update.notes.card", 770, 202);
        p.text("about.update.notes.label", 20, 784, p.w - 40, "远端版本说明", 14);
        components::scrollView(p.ui, "about.notes.scroll")
            .position(20, 816)
            .size(p.w - 40, 140)
            .theme(p.t)
            .contentKey(s.updateVersion + s.updateNotes)
            .content([&](eui::Ui &notes, float width, float) {
                components::markdown(notes, "about.notes.markdown")
                    .width(width)
                    .wrapContentHeight()
                    .theme(p.t)
                    .markdown(s.updateNotes)
                    .build();
            })
            .build();
    }
}
} // namespace savior_ui
