#pragma once

#include "radh/panels.hpp"
#include "radh/telemetry.hpp"

#include <CPPFX/CPPFX.hpp>

namespace radh {

class Inspector {
public:
    explicit Inspector(ui::Type type);
    void run();

private:
    void show(ui::View view);
    void connect();
    void clearHistory();
    void consume();
    void refresh();
    void draw();
    void drawOverview(Rectangle area);
    void drawEvents(Rectangle area);
    void drawPerformance(Rectangle area);
    void drawSystem(Rectangle area);
    void drawSettings(Rectangle area);
    void layout();
    void paste();

    CPPFX::Button* button(const char* label, int width, std::function<void()> click);
    void styleField(CPPFX::TextField* field, const char* prompt);

    ui::Type type_;
    CPPFX::GUI gui_;
    TelemetryClient client_;
    EventStore history_{3000};
    std::optional<EventStore> paused_;
    std::vector<Event> batch_;
    std::vector<const Event*> rows_;
    std::vector<const Event*> sessions_;
    std::array<ui::Series, 4> timing_;
    ui::Details details_;
    ui::TableState table_;
    ui::TableState sessionTable_;
    std::optional<Event> backend_;
    std::string session_;
    std::string address_;
    std::string filter_;
    std::size_t severity_ = 0;
    std::size_t terminalSessions_ = 0;
    std::uint64_t requests_ = 0;
    std::uint64_t operations_ = 0;
    std::uint64_t errors_ = 0;
    std::uint64_t received_ = 0;
    std::uint64_t serverUsed_ = 0;
    bool dirty_ = true;
    ui::View view_ = ui::View::overview;
    ConnectionStatus connection_;

    std::array<CPPFX::Button*, ui::viewNames.size()> navigation_{};
    CPPFX::Button* settings_ = nullptr;
    CPPFX::Button* severityButton_ = nullptr;
    CPPFX::Button* pauseButton_ = nullptr;
    CPPFX::Button* followButton_ = nullptr;
    CPPFX::Button* clearButton_ = nullptr;
    CPPFX::Button* connectButton_ = nullptr;
    CPPFX::Button* disconnectButton_ = nullptr;
    CPPFX::Button* allSessionsButton_ = nullptr;
    CPPFX::TextField* search_ = nullptr;
    CPPFX::TextField* url_ = nullptr;
    CPPFX::PasswordField* token_ = nullptr;
};

}
