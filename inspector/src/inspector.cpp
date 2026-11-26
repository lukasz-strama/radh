#include "radh/inspector.hpp"

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <unordered_set>

namespace radh {
namespace {

using namespace ui;
constexpr float sidebar = 180;
constexpr float left = sidebar + 22;
constexpr float margin = 22;
constexpr float footer = 29;
constexpr std::string_view defaultAddress = "http://127.0.0.1:8001";
constexpr std::array<const char*, 9> subtitles{
    "Obserwacje od wybrania Połącz w tej instancji Inspectora",
    "Przeszukuj lokalną historię zdarzeń",
    "Zakończone żądania i szablony tras backendu",
    "Operacje nakładki i jawne parametry kluczy",
    "Sesje widoczne w lokalnej historii oraz wymiany jednorazowe",
    "Zarejestrowane etapy Pythona i ABI C. Kroki wewnątrz algorytmów są niedostępne.",
    "Ostatnie 240 próbek w każdej serii, w mikrosekundach (µs)",
    "Wersje, stan połączenia i pojemność buforów",
    "Podaj adres osobnego nasłuchu SSE i token diagnostyczny",
};
constexpr std::array<std::string_view, 5> levels{"", "DEBUG", "INFO", "WARN", "ERROR"};

const char* connectionName(ConnectionState state)
{
    switch (state) {
    case ConnectionState::connecting: return "Łączenie";
    case ConnectionState::connected: return "Połączono";
    case ConnectionState::reconnecting: return "Ponawianie";
    case ConnectionState::failed: return "Błąd połączenia";
    default: return "Rozłączono";
    }
}

Color connectionColor(ConnectionState state)
{
    if (state == ConnectionState::connected) {
        return green;
    }
    if (state == ConnectionState::failed) {
        return red;
    }
    if (state == ConnectionState::disconnected) {
        return muted;
    }
    return amber;
}

std::string_view title(View view)
{
    if (view == View::settings) {
        return "Ustawienia połączenia";
    }
    return view == View::crypto ? "Ślad kryptograficzny" : viewNames[static_cast<std::size_t>(view)];
}

bool belongs(const Event& event, View view, std::string_view session)
{
    switch (view) {
    case View::api: return event.source == "http.api" && event.name.starts_with("http.request.");
    case View::rsa: return event.source == "crypto.rsa" || event.name == "dh.rsa.key.parameters";
    case View::dh:
        return (event.source == "dh.session" || event.source == "crypto.dh") &&
               (session.empty() || event.field("session") == session);
    case View::crypto:
        return event.source.starts_with("crypto.");
    case View::overview:
        return event.field("scope") != "ffi" && event.field("scope") != "ffi_sum";
    default: return true;
    }
}

void place(CPPFX::Item* item, float x, float y, bool visible = true)
{
    item->SetXY(x, y);
    if (visible != item->IsVisible()) {
        if (visible) {
            item->Show();
        } else {
            item->Hide();
            item->Defocus();
        }
    }
}

}

Inspector::Inspector(ui::Type type) : type_(type)
{
    for (std::size_t i = 0; i < navigation_.size(); ++i) {
        navigation_[i] = button(viewNames[i], 152, [this, i] { show(static_cast<View>(i)); });
    }
    settings_ = button("Ustawienia", 111, [this] {
        show(view_ == View::settings ? View::overview : View::settings);
    });

    search_ = gui_.AddTextField();
    styleField(search_, "Szukaj zdarzeń, tras, ID…");
    search_->SetWidth(230);
    search_->onChange.Set([this] {
        filter_ = search_->GetText();
        dirty_ = true;
        table_.offset = 0;
    });
    severityButton_ = button("Poziom: wszystkie", 136, [this] {
        severity_ = (severity_ + 1) % levels.size();
        severityButton_->SetText(severity_ ? "Poziom: " + std::string(levels[severity_]) : "Poziom: wszystkie");
        dirty_ = true;
        table_.offset = 0;
    });
    pauseButton_ = button("Wstrzymaj", 100, [this] {
        if (paused_) {
            paused_.reset();
        } else {
            paused_ = history_;
        }
        pauseButton_->SetText(paused_ ? "Wznów" : "Wstrzymaj");
        dirty_ = true;
    });
    followButton_ = button("Przewijanie: wł.", 135, [this] { table_.follow = !table_.follow; });
    clearButton_ = button("Wyczyść", 89, [this] { clearHistory(); });
    allSessionsButton_ = button("Pokaż wszystkie", 140, [this] {
        session_.clear();
        sessionTable_.selected = 0;
        table_ = {};
        dirty_ = true;
    });

    url_ = gui_.AddTextField();
    styleField(url_, "http://127.0.0.1:8001");
    const char* envUrl = std::getenv("RADH_INSPECTOR_URL");
    url_->SetText(envUrl ? std::string(envUrl, std::min(std::string_view(envUrl).size(), std::size_t{512}))
                         : std::string(defaultAddress));
    url_->onSubmit.Set([this] { if (!token_->IsTextEmpty()) connect(); });
    token_ = gui_.AddPasswordField();
    styleField(token_, "Wklej token diagnostyczny");
    token_->SetMask('*');
    token_->onSubmit.Set([this] { connect(); });
    connectButton_ = button("Połącz", 100, [this] { connect(); });
    disconnectButton_ = button("Rozłącz", 100, [this] {
        client_.disconnect();
        token_->ClearText();
    });

    batch_.reserve(client_.queue().capacity());
    rows_.reserve(history_.capacity());
    if (const char* envToken = std::getenv("RADH_DEBUG_TOKEN");
        envToken && std::string_view(envToken).size() == 43) {
        token_->SetText(envToken);
        connect();
    }
    layout();
}

CPPFX::Button* Inspector::button(const char* label, int width, std::function<void()> click)
{
    auto* item = gui_.AddButton();
    item->DoNotExpandToTextAutomatically();
    item->font.SetFont(type_.sans);
    item->font.SetFontSize(14);
    item->font.colour.SetColour(ink);
    item->colour.SetColour(raised);
    item->pressedColour.SetColour(Color{37, 79, 95, 255});
    item->SetTextMargin(4);
    item->SetWidth(width);
    item->SetHeight(32);
    item->SetText(label);
    item->onClick.Set(std::move(click));
    return item;
}

void Inspector::styleField(CPPFX::TextField* field, const char* prompt)
{
    field->DoNotExpandToTextAutomatically();
    field->font.SetFont(type_.mono);
    field->font.SetFontSize(14);
    field->font.colour.SetColour(ink);
    field->promptFont.SetFont(type_.sans);
    field->promptFont.SetFontSize(14);
    field->promptFont.colour.SetColour(muted);
    field->colour.SetColour(surface);
    field->border.SetThickness(1);
    field->border.colour.SetColour(line);
    field->SetPromptText(prompt);
    field->SetTextMargin(8);
    field->SetHeight(32);
    field->SetWidth(512);
}

void Inspector::show(View view)
{
    if (view_ == view) {
        return;
    }
    view_ = view;
    table_ = {};
    sessionTable_ = {};
    session_.clear();
    dirty_ = true;
    layout();
}

void Inspector::connect()
{
    const auto address = url_->GetText();
    if (client_.connect(address, token_->GetText())) {
        address_ = address;
        clearHistory();
        backend_.reset();
        requests_ = operations_ = errors_ = received_ = serverUsed_ = 0;
        token_->ClearText();
        show(View::overview);
    } else {
        show(View::settings);
    }
}

void Inspector::clearHistory()
{
    rows_.clear();
    sessions_.clear();
    history_.clear();
    paused_.reset();
    pauseButton_->SetText("Wstrzymaj");
    table_ = {};
    sessionTable_ = {};
    session_.clear();
    details_.select(nullptr, history_.events());
    dirty_ = true;
}

void Inspector::consume()
{
    connection_ = client_.status();
    client_.queue().drain(batch_);
    for (auto& event : batch_) {
        if (event.name == "telemetry.status") {
            serverUsed_ = event.number("buffer_used");
            continue;
        }
        if (event.name == "system.started") {
            serverUsed_ = event.number("buffer_used");
            if (backend_ && backend_->field("instance") == event.field("instance")) {
                continue;
            }
            backend_ = event;
        }
        ++received_;
        if (event.source == "http.api" && event.name.starts_with("http.request.")) {
            ++requests_;
        }
        operations_ += event.isOperation();
        errors_ += event.isError();
        history_.push(std::move(event));
        dirty_ = true;
    }
}

void Inspector::refresh()
{
    rows_.clear();
    sessions_.clear();
    if (view_ == View::performance) {
        for (auto& series : timing_) {
            series.values.clear();
        }
        for (auto it = history_.events().rbegin(); it != history_.events().rend(); ++it) {
            if (!it->durationNs) {
                continue;
            }
            const auto scope = it->field("scope");
            const int index = scope == "http" ? 0 : scope == "python" ? 1 : scope == "ffi" ? 2 :
                              scope == "ffi_sum" ? 3 : -1;
            if (index >= 0 && timing_[index].values.size() < 240) {
                timing_[index].values.push_back(*it->durationNs / 1e3);
            }
        }
        for (auto& series : timing_) {
            std::ranges::reverse(series.values);
            series.sample = statistics(series.values);
        }
    }
    if (view_ == View::dh || view_ == View::overview) {
        std::unordered_set<std::string_view> unique;
        terminalSessions_ = 0;
        for (auto it = history_.events().rbegin(); it != history_.events().rend(); ++it) {
            const auto id = it->field("session");
            if (id.empty() || !unique.insert(id).second) {
                continue;
            }
            sessions_.push_back(&*it);
            const auto state = it->field("state");
            terminalSessions_ += it->name == "dh.session.deleted" || state == "completed" ||
                                 state == "cancelled" || state == "failed" || state == "expired";
            if (id == session_) {
                sessionTable_.selected = it->serial;
            }
        }
        if (!session_.empty() && !unique.contains(session_)) {
            session_.clear();
            sessionTable_.selected = 0;
        }
    }

    const auto& source = view_ == View::logs && paused_ ? paused_->events() : history_.events();
    const Event* selected = nullptr;
    if (view_ != View::performance && view_ != View::system && view_ != View::settings) {
        for (const auto& event : source) {
            if (belongs(event, view_, session_) &&
                (view_ != View::logs || matches(event, levels[severity_], filter_))) {
                rows_.push_back(&event);
                if (event.serial == table_.selected) {
                    selected = &event;
                }
            }
        }
    }
    details_.select(selected, source);
    dirty_ = false;
}

void Inspector::layout()
{
    const float w = static_cast<float>(GetScreenWidth());
    for (std::size_t i = 0; i < navigation_.size(); ++i) {
        place(navigation_[i], 14, 80 + 40 * i);
        const bool active = static_cast<std::size_t>(view_) == i;
        navigation_[i]->colour.SetColour(active ? Color{29, 61, 75, 255} : surface);
        navigation_[i]->font.colour.SetColour(active ? cyan : muted);
    }
    place(settings_, w - 133, 12);
    const bool logs = view_ == View::logs;
    place(search_, left, 136, logs);
    place(severityButton_, left + 240, 136, logs);
    place(pauseButton_, left + 386, 136, logs);
    place(followButton_, left + 496, 136, logs);
    place(clearButton_, left + 641, 136, logs);
    const bool settings = view_ == View::settings;
    place(url_, left + 17, 179, settings);
    place(token_, left + 17, 251, settings);
    place(connectButton_, left + 17, 310, settings);
    place(disconnectButton_, left + 127, 310, settings);
    place(allSessionsButton_, w - margin - 140, 109, view_ == View::dh && !session_.empty());
}

void Inspector::paste()
{
    if (!(IsKeyDown(KEY_LEFT_CONTROL) || IsKeyDown(KEY_RIGHT_CONTROL)) || !IsKeyPressed(KEY_V)) {
        return;
    }
    CPPFX::TextField* field = nullptr;
    if (token_->IsFocused()) {
        field = token_;
    } else if (url_->IsFocused()) {
        field = url_;
    } else if (search_->IsFocused()) {
        field = search_;
    }
    if (field) {
        if (const char* clipboard = GetClipboardText()) {
            auto value = std::string_view(clipboard).substr(0, field == token_ ? 64 : 512);
            while (!value.empty() && (value.back() == '\n' || value.back() == '\r')) {
                value.remove_suffix(1);
            }
            field->SetText(std::string(value));
        }
    }
}

void Inspector::run()
{
    const Camera2D camera{{0, 0}, {0, 0}, 0, 1};
    while (!WindowShouldClose()) {
        consume();
        if (dirty_) {
            refresh();
        }
        layout();
        paste();
        BeginDrawing();
        ClearBackground(background);
        draw();
        BeginMode2D(camera);
        gui_.DoUI(camera);
        EndMode2D();
        EndDrawing();
    }
}

void Inspector::draw()
{
    const auto w = static_cast<float>(GetScreenWidth());
    const auto h = static_cast<float>(GetScreenHeight());
    DrawRectangleRec({0, 0, w, 57}, surface);
    DrawRectangleRec({0, 57, sidebar, h - 57 - footer}, surface);
    DrawLineV({0, 57}, {w, 57}, line);
    DrawLineV({sidebar, 57}, {sidebar, h - footer}, line);

    type_.draw("RADH Inspector", 20, 15, 280, 24);
    DrawCircleV({w - 320, 28}, 4, connectionColor(connection_.state));
    type_.draw(connectionName(connection_.state), w - 306, 19, 160, 16, connectionColor(connection_.state));

    const Rectangle area{left, 136, w - left - margin, h - 136 - footer - 17};
    type_.draw(title(view_), left, 74, area.width, 25);
    type_.draw(subtitles[static_cast<std::size_t>(view_)], left, 107, area.width, 14, muted);

    switch (view_) {
    case View::overview: drawOverview(area); break;
    case View::performance: drawPerformance(area); break;
    case View::system: drawSystem(area); break;
    case View::settings: drawSettings(area); break;
    default: drawEvents(area); break;
    }

    DrawRectangleRec({0, h - footer, w, footer}, surface);
    DrawLineV({0, h - footer}, {w, h - footer}, line);
    type_.draw(connectionName(connection_.state), 14, h - 22, 161, 13, connectionColor(connection_.state));

    char counts[160]{};
    std::snprintf(counts, sizeof(counts), "Zdarzenia %llu  |  Utracone %llu  |  Historia %zu / %zu",
                  static_cast<unsigned long long>(received_),
                  static_cast<unsigned long long>(connection_.serverDropped + client_.queue().dropped()),
                  history_.events().size(), history_.capacity());
    type_.draw(counts, sidebar + 14, h - 21, w - sidebar - 32, 13, muted, true);
    if (!connection_.message.empty() && view_ != View::settings && view_ != View::system) {
        type_.draw(connection_.message, left, h - footer - 16, area.width, 12, amber);
    }
}

void Inspector::drawOverview(Rectangle area)
{
    const float width = (area.width - 30) / 4;
    constexpr std::array labels{"Żądania HTTP", "Operacje kryptograficzne", "Błędy żądań / operacji", "Sesje w historii"};
    const std::array values{requests_, operations_, errors_, static_cast<std::uint64_t>(sessions_.size())};
    for (std::size_t i = 0; i < labels.size(); ++i) {
        const float x = area.x + (width + 10) * i;
        const Rectangle card{x, area.y, width, 87};
        DrawRectangleRec(card, surface);
        DrawRectangleLinesEx(card, 1, line);
        type_.draw(labels[i], x + 12, area.y + 11, width - 24, 14, muted);
        char count[48]{};
        std::snprintf(count, sizeof(count), "%llu", static_cast<unsigned long long>(values[i]));
        type_.draw(count, x + 12, area.y + 34, width - 24, 26, i == 2 && errors_ ? amber : ink, true);
        if (i == 3) {
            std::snprintf(count, sizeof(count), "Zakończone: %zu", terminalSessions_);
            type_.draw(count, x + 12, area.y + 66, width - 24, 12, muted);
        }
    }
    type_.draw("Ostatnia aktywność", area.x, area.y + 101, area.width, 16);
    const Rectangle recent{area.x, area.y + 127, area.width, area.height - 127};
    drawEvents(recent);
}

void Inspector::drawEvents(Rectangle area)
{
    if (view_ == View::logs) {
        const char* label = table_.follow ? "Przewijanie: wł." : "Przewijanie: wył.";
        if (followButton_->GetText() != label) {
            followButton_->SetText(label);
        }
        area.y += 45;
        area.height -= 45;
    }
    const float detailsHeight = view_ == View::overview ? 124 : 190;
    Rectangle eventArea{area.x, area.y, area.width, area.height - detailsHeight - 10};
    const Rectangle detailArea{area.x, area.y + area.height - detailsHeight, area.width, detailsHeight};

    if (view_ == View::dh) {
        constexpr float sessionsWidth = 278;
        const Rectangle group{area.x, area.y, sessionsWidth, eventArea.height};
        if (const auto* picked = table(type_, group, view_, true, sessions_, sessionTable_)) {
            session_ = picked->field("session");
            table_ = {};
            table_.selected = picked->serial;
            refresh();
        }
        eventArea.x += sessionsWidth + 12;
        eventArea.width -= sessionsWidth + 12;
    }
    if (const auto* selected = table(type_, eventArea, view_, false, rows_, table_)) {
        const auto& source = view_ == View::logs && paused_ ? paused_->events() : history_.events();
        details_.select(selected, source);
    }
    details_.draw(type_, detailArea);
}

void Inspector::drawPerformance(Rectangle area)
{
    constexpr std::array labels{"Żądanie HTTP", "Nakładka Pythona", "Pojedyncze wywołanie ABI C",
                               "Suma wywołań ABI C dla tekstu RSA"};
    constexpr std::array colors{cyan, green, amber, Color{190, 169, 248, 255}};
    const float width = (area.width - 12) / 2;
    const float height = (area.height - 12) / 2;
    for (std::size_t i = 0; i < timing_.size(); ++i) {
        chart(type_, {area.x + (i % 2) * (width + 12), area.y + (i / 2) * (height + 12), width, height},
              labels[i], timing_[i], colors[i]);
    }
}

void Inspector::drawSystem(Rectangle area)
{
    area.height = 440;
    DrawRectangleRec(area, surface);
    DrawRectangleLinesEx(area, 1, line);
    float y = area.y + 13;
    const auto entry = [&](std::string_view key, std::string_view value) {
        type_.draw(key, area.x + 15, y, 236, 14, muted);
        type_.draw(value.empty() ? "—" : value, area.x + 260, y, area.width - 276, 14, ink, true);
        DrawLineV({area.x + 13, y + 22}, {area.x + area.width - 13, y + 22}, line);
        y += 30;
    };
    entry("Adres nasłuchu", address_.empty() ? defaultAddress : std::string_view(address_));
    entry("Stan połączenia", connectionName(connection_.state));
    char versions[64]{};
    std::snprintf(versions, sizeof(versions), "%s / %d.%d.%d", RADH_INSPECTOR_VERSION,
                  CPPFX_VERSION_MAJOR, CPPFX_VERSION_MINOR, CPPFX_VERSION_PATCH);
    entry("RADH Inspector / CPPFX", versions);
    entry("Backend / schemat zdarzeń", backend_ ? std::string(backend_->field("backend_version")) + " / 1" : "—");
    entry("Python / platforma", backend_ ? std::string(backend_->field("python_version")) + " / " +
                                          std::string(backend_->field("platform")) : "—");
    entry("Start backendu (UTC)", backend_ ? backend_->field("started_at") : std::string_view{});
    entry("Bufor backendu", backend_ ? std::to_string(serverUsed_) + " / " +
                                       std::to_string(backend_->number("buffer_capacity")) : "—");
    entry("Kolejka sieciowa", std::to_string(client_.queue().size()) + " / " + std::to_string(client_.queue().capacity()));
    entry("Historia lokalna", std::to_string(history_.events().size()) + " / " + std::to_string(history_.capacity()));
    entry("Utracone w backendzie / kolejce", std::to_string(connection_.serverDropped) + " / " +
                                                  std::to_string(client_.queue().dropped()));
    entry("Usunięte z pełnej historii", std::to_string(history_.evicted()));
    entry("Odrzucone ramki / reset strumienia", std::to_string(connection_.malformed) + " / " + std::to_string(connection_.serverResets));
    entry("Komunikat połączenia", connection_.message);
}

void Inspector::drawSettings(Rectangle area)
{
    area.height = 291;
    DrawRectangleRec(area, surface);
    DrawRectangleLinesEx(area, 1, line);
    type_.draw("Adres backendu", area.x + 17, 153, area.width - 35, 14, muted);
    type_.draw("Token diagnostyczny", area.x + 17, 225, area.width - 35, 14, muted);
    type_.draw(connectionName(connection_.state), area.x + 17, 357, area.width - 35,
               16, connectionColor(connection_.state));
    type_.draw(connection_.message, area.x + 17, 381, area.width - 35, 14, muted);
}

}
