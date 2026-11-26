#pragma once

#include <cstdint>
#include <deque>
#include <optional>
#include <span>
#include <string>
#include <string_view>

#include <nlohmann/json.hpp>

namespace radh {

inline constexpr std::size_t maxEventBytes = 8192;

struct Event {
    std::uint64_t serial = 0;
    std::uint64_t eventId = 0;
    std::string timestamp;
    std::string level;
    std::string source;
    std::string name;
    std::string requestId;
    std::optional<std::uint64_t> durationNs;
    nlohmann::json data;

    std::string_view field(std::string_view key) const;
    std::uint64_t number(std::string_view key) const;
    bool isOperation() const;
    bool isError() const;
};

std::optional<Event> parseEvent(std::string_view payload);
bool matches(const Event& event, std::string_view level, std::string_view query);

class EventStore {
public:
    explicit EventStore(std::size_t capacity) : capacity_(capacity) {}

    void push(Event event);
    void clear();
    const std::deque<Event>& events() const { return events_; }
    std::size_t capacity() const { return capacity_; }
    std::uint64_t evicted() const { return evicted_; }

private:
    std::size_t capacity_;
    std::deque<Event> events_;
    std::uint64_t serial_ = 0;
    std::uint64_t evicted_ = 0;
};

struct Statistics {
    std::size_t count = 0;
    double minimum = 0;
    double maximum = 0;
    double mean = 0;
};

Statistics statistics(std::span<const double> samples);

}
