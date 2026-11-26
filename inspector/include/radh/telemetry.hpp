#pragma once

#include "radh/event.hpp"

#include <atomic>
#include <condition_variable>
#include <functional>
#include <mutex>
#include <stop_token>
#include <thread>
#include <vector>

namespace radh {

class SseParser {
public:
    static constexpr auto maxFrame = maxEventBytes;
    using OnFrame = std::function<void(std::string_view, std::string_view)>;
    explicit SseParser(OnFrame handler) : handler_(std::move(handler)) {}

    void feed(std::string_view bytes);
    std::uint64_t rejected() const { return rejected_; }

private:
    void endLine();
    OnFrame handler_;
    std::string line_;
    std::string data_;
    std::string id_;
    bool hasData_ = false;
    bool skipLf_ = false;
    bool discard_ = false;
    bool firstLine_ = true;
    std::uint64_t rejected_ = 0;
};

class EventQueue {
public:
    explicit EventQueue(std::size_t capacity) : capacity_(capacity) {}

    void push(Event event);
    void drain(std::vector<Event>& output);
    void reset();
    std::uint64_t dropped() const;
    std::size_t size() const;
    std::size_t capacity() const { return capacity_; }

private:
    std::size_t capacity_;
    mutable std::mutex mutex_;
    std::deque<Event> queue_;
    std::uint64_t dropped_ = 0;
};

enum class ConnectionState { disconnected, connecting, connected, reconnecting, failed };

struct ConnectionStatus {
    ConnectionState state = ConnectionState::disconnected;
    std::string message;
    std::uint64_t malformed = 0;
    std::uint64_t serverDropped = 0;
    std::uint64_t serverResets = 0;
};

class CurlRuntime {
public:
    CurlRuntime();
    ~CurlRuntime();
    CurlRuntime(const CurlRuntime&) = delete;
    CurlRuntime& operator=(const CurlRuntime&) = delete;
};

class TelemetryClient {
public:
    explicit TelemetryClient(std::size_t queueCapacity = 1024);
    ~TelemetryClient();

    bool connect(std::string url, std::string token);
    void disconnect();
    ConnectionStatus status() const;
    EventQueue& queue() { return queue_; }

private:
    struct Command {
        std::string endpoint;
        std::string token;
    };

    void worker(std::stop_token stop);
    void stream(std::stop_token stop, const Command& command, std::uint64_t generation);

    EventQueue queue_;
    mutable std::mutex mutex_;
    std::condition_variable_any changed_;
    Command command_;
    ConnectionStatus status_;
    std::atomic<std::uint64_t> generation_ = 0;
    std::jthread worker_;
};

}
