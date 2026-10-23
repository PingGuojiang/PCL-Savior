#include "pages.h"
namespace savior_ui {
float downloadsHeight() {
    float h = 310;
    if (state().releases.empty())
        h += 145;
    for (auto &r : state().releases)
        h += 120 + r.assets.size() * 84 + (r.expanded ? 190 : 0);
    return h + 70;
}
void downloads(Painter &p) {
    auto &s = state();
    p.text("dl.kicker", 0, 0, p.w, "OFFICIAL RELEASES  /  官方版本库", 12, true);
    p.text("dl.title", 0, 27, p.w, "版本下载 · 官方版本库", 22, false, 36);
    p.text("dl.sub", 0, 68, p.w, "官方 GitHub 发布记录 · 下载校验 · 本地文件管理", 13, true);
    for (int i = 0; i < 3; ++i)
        p.button(
            "dl.tab" + std::to_string(i), i * 112.f, 110, 102, s.launchers[i].name,
            [i] {
                state().downloadTab = i;
                loadReleases();
            },
            s.downloadTab == i, s.downloading);
    p.button(
        "dl.refresh", p.w - 96, 110, 96, s.loading ? "加载中…" : "刷新列表", [] { loadReleases(); },
        false, s.loading || s.downloading);
    const char *labels[] = {"全部", "正式版", "预览版", "本地已下载"};
    for (int i = 0; i < 4; ++i)
        p.button(
            "dl.filter" + std::to_string(i), i * 101.f, 158, 93, labels[i],
            [i] {
                state().filter = i;
                loadReleases();
            },
            s.filter == i, s.downloading);
    components::input(p.ui, "dl.directory")
        .position(0, 207)
        .size(p.w - 114, 36)
        .fontSize(12)
        .theme(p.t)
        .value(s.directory)
        .placeholder("保存目录（留空使用默认下载目录）")
        .onChange([](const std::string &value) { state().directory = value; })
        .onEnter([] { saveSettings(); })
        .build();
    p.button("dl.save", p.w - 104, 207, 104, "保存目录", [] {
        saveSettings();
        state().message = "已请求保存下载目录";
    });
    p.button(
        "dl.import", 0, 254, 140, "导入本地启动器",
        [] {
            int tab = state().downloadTab;
            browse(tab);
            state().selected = tab;
            state().page = 0;
        },
        false, s.downloading);
    p.button(
        "dl.official", 152, 254, 140, "打开官方发布页",
        [] {
            auto &s = state();
            if (!s.officialUrl.empty())
                eui::platform::openUrl(s.officialUrl);
        },
        false, s.officialUrl.empty());
    float y = 310;
    if (s.downloading) {
        p.card("dl.progress.bg", y, 92);
        p.text("dl.progress.label", 16, y + 9, p.w - 132, "正在下载 " + s.downloadLabel, 12, true);
        p.ui.rect("dl.progress.track")
            .position(16, y + 48)
            .size(p.w - 142, 7)
            .color(p.t.border)
            .radius(4)
            .build();
        p.ui.rect("dl.progress.fill")
            .position(16, y + 48)
            .size((p.w - 142) * s.percent / 100.f, 7)
            .color(p.t.primary)
            .radius(4)
            .build();
        p.text("dl.progress.value", 16, y + 63, 180, std::to_string(s.percent) + "%", 11, true);
        p.button("dl.cancel", p.w - 112, y + 28, 96, "取消下载", [] {
            auto path = std::filesystem::path(savior::wide(state().cancelFile));
            std::ofstream f(path);
            f << "cancel";
            state().message = f ? "已请求取消，正在安全清理临时文件" : "取消请求写入失败";
        });
        y += 110;
    }
    if (s.releases.empty()) {
        p.card("dl.empty", y, 125);
        p.text("dl.empty.title", 20, y + 16, p.w - 40,
               s.loading ? "正在获取官方版本…" : "暂无可显示的发布文件", 16);
        p.text("dl.empty.detail", 20, y + 51, p.w - 40,
               "PCL 未公开的二进制文件请从官方渠道获取，或导入本地文件。", 12, true, 55);
        y += 145;
    }
    for (size_t ri = 0; ri < s.releases.size(); ++ri) {
        auto &r = s.releases[ri];
        std::string id = "release." + std::to_string(ri);
        float height = 104 + r.assets.size() * 84 + (r.expanded ? 190 : 0);
        p.card(id + ".card", y, height);
        p.text(id + ".title", 16, y + 12, p.w - 130,
               r.tag + (r.latest ? "  · 最新" : "") + (r.preview ? "  · 预览版" : "  · 正式版"), 16);
        p.text(id + ".date", 16, y + 43, p.w - 130, r.date, 12, true);
        p.button(id + ".notes", p.w - 104, y + 16, 88, r.expanded ? "收起日志" : "更新日志",
                 [ri] { state().releases[ri].expanded = !state().releases[ri].expanded; });
        float ay = y + 78;
        for (size_t ai = 0; ai < r.assets.size(); ++ai) {
            auto a = r.assets[ai];
            auto aid = id + ".asset." + std::to_string(ai);
            p.text(aid + ".name", 16, ay, p.w - 32, a.name + "  ·  " + sizeText(a.size), 12, false);
            if (a.local.empty())
                p.button(
                    aid + ".download", 16, ay + 28, 112, "下载并校验",
                    [ri, ai] { download((int)ri, (int)ai); }, true, s.downloading);
            else {
                p.button(
                    aid + ".target", 16, ay + 28, 126, "设为修补目标",
                    [a] {
                        auto &s = state();
                        s.selected = s.downloadTab;
                        setPath(s.selected, a.local);
                        s.page = 0;
                    },
                    true, s.downloading);
                p.button(aid + ".folder", 152, ay + 28, 88, "查看文件", [a] {
                    eui::platform::openUrl(
                        "file:///" +
                        savior::utf8(
                            std::filesystem::path(savior::wide(a.local)).parent_path().wstring()));
                });
                bool fileBusy = !s.deletingPath.empty();
                for (const auto &launcher : s.launchers) {
                    fileBusy = fileBusy || (launcher.busy && savior::canonical(launcher.path) ==
                                                                 savior::canonical(a.local));
                }
                p.dangerButton(
                    aid + ".delete", 250, ay + 28, 88, "删除文件",
                    [a] {
                        auto &s = state();
                        for (const auto &launcher : s.launchers) {
                            if (launcher.busy &&
                                savior::canonical(launcher.path) == savior::canonical(a.local)) {
                                s.message = "此启动器正在处理，请完成后再删除。";
                                return;
                            }
                        }
                        s.deletePath = a.local;
                        s.deleteSha = a.sha;
                        s.deleteOpen = true;
                    },
                    s.downloading || fileBusy);
            }
            ay += 84;
        }
        if (r.assets.empty())
            p.text(id + ".noassets", 16, ay, p.w - 32,
                   "此发布未提供可下载的启动器文件，请访问官方发布页。", 12, true);
        if (r.expanded) {
            components::scrollView(p.ui, id + ".notes.scroll")
                .position(16, ay)
                .size(p.w - 32, 172)
                .theme(p.t)
                .contentKey(r.tag)
                .content([&](eui::Ui &notes, float width, float) {
                    components::markdown(notes, id + ".notes.text")
                        .width(width)
                        .wrapContentHeight()
                        .theme(p.t)
                        .markdown(r.notes.empty() ? "此版本暂无更新说明。" : r.notes)
                        .build();
                })
                .build();
        }
        y += height + 16;
    }
    p.button(
        "dl.prev", 0, y + 8, 100, "上一页", [] { loadReleases(std::max(1, state().catalogPage - 1)); },
        false, s.loading || s.catalogPage <= 1 || s.downloading);
    p.text("dl.page", 114, y + 14, 140, "第 " + std::to_string(s.catalogPage) + " 页", 12, true);
    p.button(
        "dl.next", p.w - 100, y + 8, 100, "下一页", [] { loadReleases(state().nextPage); }, false,
        s.loading || s.nextPage == 0 || s.downloading);
}
} // namespace savior_ui
