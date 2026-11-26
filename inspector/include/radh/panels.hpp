#pragma once

#include "radh/event.hpp"

#include <raylib.h>

#include <array>
#include <vector>

namespace radh::ui {

inline constexpr Color background{16, 20, 27, 255};
inline constexpr Color surface{22, 28, 37, 255};
inline constexpr Color raised{31, 40, 52, 255};
inline constexpr Color line{53, 65, 81, 255};
inline constexpr Color ink{230, 237, 246, 255};
inline constexpr Color muted{163, 179, 199, 255};
inline constexpr Color cyan{101, 218, 230, 255};
inline constexpr Color green{125, 219, 171, 255};
inline constexpr Color amber{244, 186, 105, 255};
inline constexpr Color red{250, 132, 145, 255};

enum class View { overview, logs, api, rsa, dh, crypto, performance, system, settings };
inline constexpr std::array<const char*, 8> viewNames{
    "Przegląd", "Dziennik", "Monitor API", "RSA", "Diffie–Hellman", "Ślad operacji",
    "Wydajność", "System"
};

struct Type {
    Font sans;
    Font mono;
    void draw(std::string_view value, float x, float y, float width,
              float size = 14, Color color = ink, bool fixed = false) const;
};

struct TableState {
    int offset = 0;
    bool follow = true;
    std::uint64_t selected = 0;
};

Color severity(std::string_view level);
const Event* table(const Type& type, Rectangle area, View view, bool sessionList,
                   const std::vector<const Event*>& events, TableState& state);

class Details {
public:
    void select(const Event* event, const std::deque<Event>& history);
    void draw(const Type& type, Rectangle area);

private:
    std::string title_;
    std::vector<std::pair<std::string, std::string>> fields_;
    std::vector<std::string> related_;
    int scroll_ = 0;
    std::uint64_t serial_ = 0;
};

struct Series {
    std::vector<double> values;
    Statistics sample;
};

void chart(const Type& type, Rectangle area, const char* title, const Series& series, Color color);

}
