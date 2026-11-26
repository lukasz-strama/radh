#include "radh/event.hpp"
#include "radh/telemetry.hpp"

#include <array>
#include <chrono>
#include <iostream>
#include <stdexcept>
#include <thread>

#ifdef __linux__
#include <arpa/inet.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

namespace {

using namespace radh;
using namespace std::chrono_literals;

void check(bool result, const char* description)
{
    if (!result) {
        throw std::runtime_error(description);
    }
}

constexpr auto payload = R"({
"schema_version":1,"event_id":148,"timestamp":"2026-11-26T12:32:04.130Z",
"level":"DEBUG","source":"crypto.rsa","event":"rsa.future.completed","request_id":"rsa-0148",
"duration_ns":12400,"data":{"modulus":"184467440737095516170000","scope":"python"}
})";

void parser()
{
    std::vector<std::pair<std::string, std::string>> frames;
    SseParser sse([&](auto data, auto id) { frames.emplace_back(data, id); });
    const std::string input = "\xef\xbb\xbf: heartbeat\r\nid: 14\r\ndata: first\r\ndata:second\r\n\r\n"
                              "event: custom\ndata: next\n\n"
                              "id:\rdata:\r\rdata: pending";
    for (const char byte : input) {
        sse.feed({&byte, 1});
    }
    check(frames.size() == 3, "SSE dispatch and incomplete frame");
    check(frames[0] == std::pair<std::string, std::string>{"first\nsecond", "14"}, "SSE multiline data");
    check(frames[1] == std::pair<std::string, std::string>{"next", "14"}, "SSE multiple frames");
    check(frames[2] == std::pair<std::string, std::string>{"", ""}, "SSE cleared id and empty data");
    sse.feed("\n\n");
    check(frames.back().first == "pending", "SSE partial data");

    sse.feed("data: " + std::string(SseParser::maxFrame + 10, 'x') + "\n\n"
             "data: recovered\n\n");
    check(sse.rejected() == 1 && frames.back().first == "recovered", "oversized SSE recovery");
    sse.feed("data: " + std::string(SseParser::maxFrame / 2, 'x') + "\n"
             "data: " + std::string(SseParser::maxFrame / 2, 'x') + "\n\n");
    check(sse.rejected() == 2, "aggregate SSE size limit");
}

void model()
{
    const auto event = parseEvent(payload);
    check(event.has_value(), "versioned event parses");
    check(event->eventId == 148 && event->durationNs == 12400, "event metadata");
    check(event->name == "rsa.future.completed", "unknown event name supported");
    check(event->field("modulus") == "184467440737095516170000", "decimal string round trips");
    check(event->isOperation() && !event->isError(), "operation classification");
    check(!parseEvent("not JSON") && !parseEvent("[]") && !parseEvent("{}"), "malformed JSON/schema");
    std::string wrong(payload);
    wrong.replace(wrong.find("1,"), 1, "2");
    check(!parseEvent(wrong), "unknown schema version");
    wrong = payload;
    wrong.replace(wrong.find("12400"), 5, "-12400");
    check(!parseEvent(wrong), "invalid duration");
    check(!parseEvent(std::string(30, '[') + std::string(30, ']')), "nested JSON bounded");
    check(matches(*event, "DEBUG", "FuTuRe") && matches(*event, "", "rsa-0148") &&
          matches(*event, "", "1844674") && !matches(*event, "INFO", "future") &&
          !matches(*event, "", "missing"), "level and text filter");

    EventStore store(2);
    for (std::uint64_t i = 1; i <= 3; ++i) {
        auto item = *event;
        item.eventId = i;
        store.push(std::move(item));
    }
    check(store.events().size() == 2 && store.events().front().eventId == 2 && store.evicted() == 1,
          "bounded event storage");
    store.clear();
    store.push(*event);
    check(store.events().size() == 1 && store.events().front().serial == 4 && store.evicted() == 0,
          "clear history and selection identity");

    EventQueue queue(2);
    queue.push(Event{.eventId = 1});
    queue.push(Event{.eventId = 2});
    queue.push(Event{.eventId = 3});
    std::vector<Event> drained;
    queue.drain(drained);
    check(drained.size() == 2 && drained[0].eventId == 2 && drained[1].eventId == 3 &&
          queue.dropped() == 1 && queue.size() == 0, "queue overflow and drain order");

    const auto stat = statistics(std::array{1.0, 2.0, 6.0});
    check(stat.count == 3 && stat.minimum == 1 && stat.maximum == 6 && stat.mean == 3, "sample statistics");
    check(statistics({}).count == 0, "empty sample statistics");
}

#ifdef __linux__
class Socket {
public:
    explicit Socket(int fd) : fd_(fd) { check(fd >= 0, "loopback socket initialization"); }
    ~Socket() { close(fd_); }
    Socket(const Socket&) = delete;
    Socket& operator=(const Socket&) = delete;
    int fd() const { return fd_; }
private:
    int fd_;
};

template <class Predicate>
bool within(Predicate predicate, std::chrono::milliseconds timeout)
{
    const auto until = std::chrono::steady_clock::now() + timeout;
    while (!predicate()) {
        if (std::chrono::steady_clock::now() >= until) {
            return false;
        }
        std::this_thread::sleep_for(10ms);
    }
    return true;
}

void networking()
{
    const Socket listenFd(socket(AF_INET, SOCK_STREAM, 0));
    sockaddr_in address{};
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    check(bind(listenFd.fd(), reinterpret_cast<sockaddr*>(&address), sizeof(address)) == 0, "bind loopback");
    check(listen(listenFd.fd(), 1) == 0, "listen loopback");
    socklen_t length = sizeof(address);
    check(getsockname(listenFd.fd(), reinterpret_cast<sockaddr*>(&address), &length) == 0, "test port");

    const std::string secret(43, 'A');
    std::atomic_bool authorized = false;
    std::atomic_bool closed = false;
    std::jthread server([&](std::stop_token stop) {
        pollfd ready{listenFd.fd(), POLLIN, 0};
        while (!stop.stop_requested() && poll(&ready, 1, 50) == 0) {}
        if (stop.stop_requested()) {
            return;
        }
        const Socket socket(accept(listenFd.fd(), nullptr, nullptr));
        timeval limit{1, 0};
        setsockopt(socket.fd(), SOL_SOCKET, SO_RCVTIMEO, &limit, sizeof(limit));
        std::array<char, 512> input{};
        std::string request;
        while (request.size() < 4096 && !request.ends_with("\r\n\r\n")) {
            const auto count = recv(socket.fd(), input.data(), input.size(), 0);
            if (count <= 0) {
                return;
            }
            request.append(input.data(), count);
        }
        authorized = request.starts_with("GET /api/v1/debug/events HTTP/") &&
                     request.contains("Authorization: Bearer " + secret + "\r\n");

        std::string frame = "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n\r\n"
                            "data: invalid\n\ndata: ";
        for (const char byte : std::string_view(payload)) {
            frame += byte == '\n' ? "\ndata: " : std::string(1, byte);
        }
        frame += "\n\n";
        if (send(socket.fd(), frame.data(), frame.size(), MSG_NOSIGNAL) != static_cast<ssize_t>(frame.size())) {
            return;
        }
        pollfd client{socket.fd(), POLLIN, 0};
        while (!stop.stop_requested()) {
            if (poll(&client, 1, 50) > 0 && recv(socket.fd(), input.data(), input.size(), 0) <= 0) {
                closed = true;
                return;
            }
        }
    });

    CurlRuntime curl;
    TelemetryClient client;
    check(!client.connect("http://example.test", secret), "remote cleartext rejected");
    check(!client.connect("http://user@127.0.0.1", secret), "URL credentials rejected");
    check(client.connect("http://127.0.0.1:" + std::to_string(ntohs(address.sin_port)), secret), "connect to test server");
    check(within([&] { return client.queue().size() == 1; }, 3s), "real SSE delivered by worker");
    check(authorized && client.status().state == ConnectionState::connected && client.status().malformed == 1,
          "authorization and malformed frame accounting");
    client.disconnect();
    check(within([&] { return closed.load(); }, 2s), "cancellation closes active stream");
    check(client.status().state == ConnectionState::disconnected, "connection state on cancellation");
}
#endif

}

int main()
{
    try {
        parser();
        model();
#ifdef __linux__
        networking();
#endif
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
