#pragma once
#include "../actions.h"
namespace savior_ui {
inline std::string sizeText(double bytes) {
    std::ostringstream o;
    o << std::fixed << std::setprecision(1) << bytes / 1048576.0 << " MB";
    return o.str();
}
inline eui::Color color(unsigned hex) {
    return {((hex >> 16) & 255) / 255.f, ((hex >> 8) & 255) / 255.f, (hex & 255) / 255.f, 1};
}
struct Painter {
    eui::Ui &ui;
    components::theme::ThemeColorTokens t;
    float w;
    void text(std::string id, float x, float y, float width, const std::string &value, float font = 14,
              bool muted = false, float h = 24) {
        ui.text(id)
            .position(x, y)
            .size(width, h)
            .maxWidth(width)
            .wrap(true)
            .text(value)
            .fontSize(font)
            .lineHeight(font * 1.45f)
            .color(muted ? components::theme::withOpacity(t.text, .65f) : t.text)
            .build();
    }
    void card(std::string id, float y, float height) {
        ui.rect(id)
            .position(0, y)
            .size(w, height)
            .color(t.surface)
            .radius(14)
            .border(1, t.border)
            .build();
    }
    void button(std::string id, float x, float y, float width, const std::string &label,
                std::function<void()> click, bool primary = false, bool disabled = false) {
        components::button(ui, id)
            .position(x, y)
            .size(width, 36)
            .text(label)
            .fontSize(13)
            .theme(t, primary)
            .radius(8)
            .disabled(disabled)
            .onClick(std::move(click))
            .build();
    }
    void dangerButton(std::string id, float x, float y, float width, const std::string &label,
                      std::function<void()> click, bool disabled = false) {
        const auto danger = color(t.dark ? 0xef4444 : 0xdc2626);
        components::button(ui, id)
            .position(x, y)
            .size(width, 36)
            .text(label)
            .fontSize(13)
            .theme(t, false)
            .radius(8)
            .border(1, danger)
            .textColor(danger)
            .disabled(disabled)
            .onClick(std::move(click))
            .build();
    }
};

void home(Painter &p);
void downloads(Painter &p);
void about(Painter &p);
float downloadsHeight();
} // namespace savior_ui
