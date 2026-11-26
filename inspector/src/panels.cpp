#include "radh/panels.hpp"

#include <algorithm>
#include <array>
#include <cstdio>
#include <cstring>

namespace radh::ui {
namespace {

constexpr float rowHeight = 25;
constexpr float tableHeader = 29;

void scissor(Rectangle area)
{
    BeginScissorMode(static_cast<int>(area.x), static_cast<int>(area.y),
                     static_cast<int>(area.width), static_cast<int>(area.height));
}

void scrollbar(Rectangle area, int offset, int visible, int count)
{
    if (count <= visible || visible <= 0) {
        return;
    }
    const float thumb = std::max(18.0f, area.height * visible / count);
    const float y = area.y + (area.height - thumb) * offset / (count - visible);
    DrawRectangleRec({area.x + area.width - 4, y, 3, thumb}, line);
}

int scrollDelta(Rectangle area)
{
    return CheckCollisionPointRec(GetMousePosition(), area)
               ? static_cast<int>(GetMouseWheelMove() * 3) : 0;
}

std::string_view timeOf(const Event& event)
{
    return std::string_view(event.timestamp).substr(11);
}

std::string_view stage(const Event& event)
{
    if (event.name.ends_with(".completed")) {
        return "ukończono";
    }
    if (event.name.ends_with(".failed")) {
        return "błąd";
    }
    if (event.name.ends_with(".started")) {
        return "początek";
    }
    return event.field("state");
}

struct Row {
    std::array<std::string_view, 6> values{};
    std::array<char, 32> duration{};
    std::array<char, 24> status{};
};

std::array<std::string_view, 6> rowValues(Row& row, const Event& e, View view, bool sessionList)
{
    if (e.durationNs) {
        std::snprintf(row.duration.data(), row.duration.size(), "%.3f", *e.durationNs / 1e3);
    }
    const auto status = e.number("status");
    if (status) {
        std::snprintf(row.status.data(), row.status.size(), "%llu", static_cast<unsigned long long>(status));
    }
    if (sessionList) {
        return {e.field("session"), e.field("protocol"),
                e.name == "dh.session.deleted" ? "usunięta" : e.field("state"), "", "", ""};
    }
    if (view == View::api) {
        return {timeOf(e), e.field("method"), e.field("route"), row.status.data(),
                row.duration.data(), e.requestId};
    }
    if (view == View::rsa) {
        return {timeOf(e), e.name, stage(e), e.field("modulus"),
                e.field("public_exponent"), row.duration.data()};
    }
    if (view == View::dh) {
        return {timeOf(e), e.name, e.field("state"), e.field("sender"),
                e.field("public_value"), row.duration.data()};
    }
    if (view == View::crypto) {
        return {timeOf(e), e.field("scope"), e.name, stage(e), row.duration.data(), e.requestId};
    }
    return {timeOf(e), e.level, e.source, e.name, e.field("route"), row.duration.data()};
}

struct Columns {
    std::array<const char*, 6> labels;
    std::array<float, 6> shares;
};

Columns columns(View view, bool sessionList)
{
    if (sessionList) {
        return {{"Id. sesji", "API", "Stan"}, {0.55f, 0.12f, 0.33f}};
    }
    switch (view) {
    case View::api:
        return {{"UTC", "Metoda", "Trasa", "HTTP", "Czas [µs]", "ID żądania"},
                {0.15f, 0.08f, 0.38f, 0.07f, 0.12f, 0.20f}};
    case View::rsa:
        return {{"UTC", "Operacja", "Etap", "Moduł n", "Wykładnik e", "Czas [µs]"},
                {0.15f, 0.32f, 0.11f, 0.15f, 0.15f, 0.12f}};
    case View::dh:
        return {{"UTC", "Zdarzenie", "Stan", "Nadawca", "Wartość", "Czas [µs]"},
                {0.19f, 0.38f, 0.13f, 0.10f, 0.10f, 0.10f}};
    case View::crypto:
        return {{"UTC", "Zakres", "Operacja", "Etap", "Czas [µs]", "ID żądania"},
                {0.15f, 0.09f, 0.35f, 0.11f, 0.12f, 0.18f}};
    default:
        return {{"UTC", "Poziom", "Źródło", "Zdarzenie", "Trasa", "Czas [µs]"},
                {0.15f, 0.08f, 0.15f, 0.30f, 0.22f, 0.10f}};
    }
}

}

void Type::draw(std::string_view value, float x, float y, float width, float size, Color color, bool fixed) const
{
    if (value.empty() || width < 10) {
        return;
    }
    const Font font = fixed ? mono : sans;
    std::array<char, 768> buffer{};
    const auto length = std::min(value.size(), buffer.size() - 1);
    std::memcpy(buffer.data(), value.data(), length);
    if (MeasureTextEx(font, buffer.data(), size, 0).x <= width && length == value.size()) {
        DrawTextEx(font, buffer.data(), {x, y}, size, 0, color);
        return;
    }

    const float ellipsis = MeasureTextEx(font, "...", size, 0).x;
    float used = 0;
    std::size_t end = 0;
    while (end < length && end + 4 < buffer.size()) {
        int count = 0;
        const int codepoint = GetCodepointNext(buffer.data() + end, &count);
        const auto glyph = GetGlyphInfo(font, codepoint);
        const auto rec = GetGlyphAtlasRec(font, codepoint);
        used += (glyph.advanceX ? glyph.advanceX : rec.width + glyph.offsetX) * size / font.baseSize;
        if (used + ellipsis > width) {
            break;
        }
        end += count;
    }
    std::memcpy(buffer.data() + end, "...", 4);
    DrawTextEx(font, buffer.data(), {x, y}, size, 0, color);
}

Color severity(std::string_view level)
{
    if (level == "ERROR") {
        return red;
    }
    if (level == "WARN") {
        return amber;
    }
    if (level == "INFO") {
        return cyan;
    }
    return muted;
}

const Event* table(const Type& type, Rectangle area, View view, bool sessionList,
                   const std::vector<const Event*>& events, TableState& state)
{
    DrawRectangleRec(area, surface);
    DrawRectangleRec({area.x, area.y, area.width, tableHeader}, raised);
    const auto cols = columns(view, sessionList);
    float x = area.x;
    for (std::size_t i = 0; i < cols.labels.size() && cols.labels[i]; ++i) {
        const float width = area.width * cols.shares[i];
        type.draw(cols.labels[i], x + 8, area.y + 7, width - 12, 13, muted);
        x += width;
    }

    const Rectangle body{area.x, area.y + tableHeader, area.width, area.height - tableHeader};
    const int visible = std::max(1, static_cast<int>(body.height / rowHeight));
    const int count = static_cast<int>(events.size());
    const int maxOffset = std::max(0, count - visible);
    if (state.follow) {
        state.offset = maxOffset;
    }
    if (const int wheel = scrollDelta(body)) {
        state.follow = false;
        state.offset -= wheel;
    }
    state.offset = std::clamp(state.offset, 0, maxOffset);
    const auto mouse = GetMousePosition();
    const Event* selected = nullptr;
    scissor(body);
    for (int i = state.offset; i < std::min(count, state.offset + visible); ++i) {
        const auto& event = *events[i];
        const float y = body.y + (i - state.offset) * rowHeight;
        const bool hover = CheckCollisionPointRec(mouse, {body.x, y, body.width, rowHeight});
        if (hover && IsMouseButtonPressed(MOUSE_BUTTON_LEFT)) {
            state.selected = event.serial;
            selected = &event;
        }
        if (state.selected == event.serial || hover || i % 2) {
            DrawRectangleRec({body.x, y, body.width, rowHeight},
                             state.selected == event.serial ? Color{29, 61, 75, 255} : Color{26, 34, 45, 255});
        }
        Row row;
        const auto values = rowValues(row, event, view, sessionList);
        x = body.x;
        for (std::size_t col = 0; col < values.size(); ++col) {
            const float width = body.width * cols.shares[col];
            const Color color = col == 1 && (view == View::logs || view == View::overview)
                                    ? severity(event.level) : col == 0 ? muted : ink;
            type.draw(values[col], x + 8, y + 5, width - 12, 13, color, true);
            x += width;
        }
    }
    if (events.empty()) {
        type.draw(sessionList ? "Brak zaobserwowanych sesji" : "Brak pasujących zdarzeń",
                  body.x + 12, body.y + 14, body.width - 24, 14, muted);
    }
    scrollbar(body, state.offset, visible, count);
    EndScissorMode();
    DrawRectangleLinesEx(area, 1, line);
    return selected;
}

void Details::select(const Event* event, const std::deque<Event>& history)
{
    const auto serial = event ? event->serial : 0;
    if (serial != serial_) {
        scroll_ = 0;
        serial_ = serial;
    }
    fields_.clear();
    related_.clear();
    if (!event) {
        title_.clear();
        return;
    }
    title_ = event->name;
    fields_.emplace_back("Czas UTC", event->timestamp);
    fields_.emplace_back("Poziom / źródło", event->level + " / " + event->source);
    if (!event->requestId.empty()) {
        fields_.emplace_back("ID żądania", event->requestId);
    }
    if (event->durationNs) {
        fields_.emplace_back("Czas [ns]", std::to_string(*event->durationNs));
    }
    for (auto i = event->data.begin(); i != event->data.end(); ++i) {
        fields_.emplace_back(i.key(), i->is_string() ? i->get<std::string>() : i->dump());
    }
    for (const auto& item : history) {
        if (item.serial != event->serial && !event->requestId.empty() &&
            item.requestId == event->requestId) {
            related_.push_back(std::string(timeOf(item)) + "  " + item.name);
        }
    }
}

void Details::draw(const Type& type, Rectangle area)
{
    DrawRectangleRec(area, surface);
    DrawRectangleLinesEx(area, 1, line);
    if (title_.empty()) {
        type.draw("Wybierz zdarzenie, aby zobaczyć szczegóły i powiązane operacje.",
                  area.x + 12, area.y + 12, area.width - 24, 14, muted);
        return;
    }

    const float width = area.width * 0.55f;
    DrawRectangleRec({area.x, area.y, area.width, tableHeader}, raised);
    type.draw(title_, area.x + 12, area.y + 7, width - 20, 14, cyan, true);
    type.draw("Powiązane zdarzenia żądania", area.x + width + 12, area.y + 7, area.width - width - 24, 14);
    DrawLineV({area.x + width, area.y + tableHeader}, {area.x + width, area.y + area.height}, line);

    const int visible = static_cast<int>((area.height - tableHeader - 8) / 19);
    const int count = static_cast<int>(std::max(fields_.size(), related_.size()));
    scroll_ = std::clamp(scroll_ - scrollDelta(area), 0, std::max(0, count - visible));
    const Rectangle body{area.x, area.y + tableHeader, area.width, area.height - tableHeader};
    scissor(body);
    for (int i = scroll_; i < std::min(count, scroll_ + visible); ++i) {
        const float y = body.y + 5 + (i - scroll_) * 19.0f;
        if (i < static_cast<int>(fields_.size())) {
            const auto& [key, value] = fields_[i];
            type.draw(key, body.x + 12, y, 133, 13, muted);
            type.draw(value, body.x + 151, y, width - 158, 13, ink, true);
        }
        if (i < static_cast<int>(related_.size())) {
            type.draw(related_[i], body.x + width + 12, y, body.width - width - 23, 13, ink, true);
        }
    }
    if (related_.empty()) {
        type.draw("Brak w historii lokalnej", body.x + width + 12, body.y + 5, body.width - width - 23, 13, muted);
    }
    scrollbar(body, scroll_, visible, count);
    EndScissorMode();
}

void chart(const Type& type, Rectangle area, const char* title, const Series& series, Color color)
{
    DrawRectangleRec(area, surface);
    DrawRectangleLinesEx(area, 1, line);
    type.draw(title, area.x + 13, area.y + 12, area.width - 26, 16, ink);
    const auto& [count, min, max, mean] = series.sample;
    char label[150]{};
    if (!count) {
        type.draw("Oczekiwanie na próbki", area.x + 13, area.y + 43, area.width - 26, 14, muted);
        return;
    }

    std::snprintf(label, sizeof(label), "n=%zu  min %.2f  śr. %.2f  max %.2f µs", count, min, mean, max);
    type.draw(label, area.x + 13, area.y + 37, area.width - 26, 13, muted, true);
    const Rectangle plot{area.x + 60, area.y + 63, area.width - 77, area.height - 89};
    const double scale = std::max(max, 0.01);
    for (int i = 0; i <= 2; ++i) {
        const float y = plot.y + plot.height * i / 2;
        DrawLineV({plot.x, y}, {plot.x + plot.width, y}, line);
        std::snprintf(label, sizeof(label), "%.2f", scale * (2 - i) / 2);
        type.draw(label, area.x + 9, y - 7, 48, 11, muted, true);
    }
    const auto point = [&](std::size_t index) -> Vector2 {
        return {plot.x + plot.width * index / std::max<std::size_t>(1, count - 1),
                plot.y + plot.height * static_cast<float>(1 - series.values[index] / scale)};
    };
    if (count == 1) {
        DrawCircleV(point(0), 3, color);
    }
    for (std::size_t i = 1; i < count; ++i) {
        DrawLineEx(point(i - 1), point(i), 1.5f, color);
    }
    type.draw("próbki →", plot.x + plot.width - 62, plot.y + plot.height + 8, 64, 11, muted);
}

}
