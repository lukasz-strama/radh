#include "radh/event.hpp"

#include <algorithm>
#include <cctype>
#include <numeric>
#include <stdexcept>

namespace radh {
namespace {

std::string readString(const nlohmann::json& doc, const char* key, std::size_t limit)
{
    const auto& value = doc.at(key).get_ref<const std::string&>();
    if (value.empty() || value.size() > limit ||
        std::ranges::any_of(value, [](unsigned char c) { return c < 32 || c == 127; })) {
        throw std::invalid_argument("invalid string");
    }
    return value;
}

bool containsInsensitive(std::string_view text, std::string_view query)
{
    return std::search(text.begin(), text.end(), query.begin(), query.end(),
                       [](unsigned char a, unsigned char b) {
                           return std::tolower(a) == std::tolower(b);
                       }) != text.end();
}

}

std::string_view Event::field(std::string_view key) const
{
    const auto item = data.find(key);
    if (item != data.end() && item->is_string()) {
        return item->get_ref<const std::string&>();
    }
    return {};
}

std::uint64_t Event::number(std::string_view key) const
{
    const auto item = data.find(key);
    return item != data.end() && item->is_number_unsigned() ? item->get<std::uint64_t>() : 0;
}

bool Event::isOperation() const
{
    return field("scope") == "python" && durationNs.has_value();
}

bool Event::isError() const
{
    return (source == "http.api" && name.starts_with("http.request") &&
            (number("status") >= 400 || level == "WARN" || level == "ERROR")) ||
           (isOperation() && name.ends_with(".failed"));
}

std::optional<Event> parseEvent(std::string_view payload)
{
    if (payload.size() > maxEventBytes) {
        return std::nullopt;
    }
    try {
        const auto doc = nlohmann::json::parse(payload, [](int depth, auto, const auto&) {
            if (depth > 4) {
                throw std::invalid_argument("event nesting");
            }
            return true;
        });
        if (!doc.is_object() || !doc.at("schema_version").is_number_unsigned() ||
            doc.at("schema_version") != 1 || !doc.at("event_id").is_number_unsigned()) {
            return std::nullopt;
        }

        Event event;
        event.eventId = doc.at("event_id").get<std::uint64_t>();
        event.timestamp = readString(doc, "timestamp", 40);
        if (event.timestamp.size() < 20 || event.timestamp[10] != 'T' ||
            !event.timestamp.ends_with('Z')) {
            return std::nullopt;
        }
        event.level = readString(doc, "level", 16);
        event.source = readString(doc, "source", 64);
        event.name = readString(doc, "event", 128);
        if (!doc.at("request_id").is_null()) {
            event.requestId = readString(doc, "request_id", 64);
        }
        const auto& duration = doc.at("duration_ns");
        if (duration.is_number_unsigned()) {
            event.durationNs = duration.get<std::uint64_t>();
        } else if (!duration.is_null()) {
            return std::nullopt;
        }
        event.data = doc.at("data");
        if (!event.data.is_object()) {
            return std::nullopt;
        }
        return event;
    } catch (const std::exception&) {
        return std::nullopt;
    }
}

bool matches(const Event& event, std::string_view level, std::string_view query)
{
    if (!level.empty() && event.level != level) {
        return false;
    }
    if (query.empty() || containsInsensitive(event.name, query) ||
        containsInsensitive(event.level, query) || containsInsensitive(event.source, query) ||
        containsInsensitive(event.requestId, query) || containsInsensitive(event.timestamp, query)) {
        return true;
    }
    for (auto item = event.data.begin(); item != event.data.end(); ++item) {
        if (containsInsensitive(item.key(), query)) {
            return true;
        }
        if (item->is_string()) {
            if (containsInsensitive(item->get_ref<const std::string&>(), query)) {
                return true;
            }
        } else if (containsInsensitive(item->dump(), query)) {
            return true;
        }
    }
    return false;
}

void EventStore::push(Event event)
{
    if (capacity_ == 0) {
        ++evicted_;
        return;
    }
    if (events_.size() == capacity_) {
        events_.pop_front();
        ++evicted_;
    }
    event.serial = ++serial_;
    events_.push_back(std::move(event));
}

void EventStore::clear()
{
    events_.clear();
    evicted_ = 0;
}

Statistics statistics(std::span<const double> samples)
{
    if (samples.empty()) {
        return {};
    }
    const auto [minimum, maximum] = std::ranges::minmax_element(samples);
    return {samples.size(), *minimum, *maximum,
            std::accumulate(samples.begin(), samples.end(), 0.0) / samples.size()};
}

}
