#include "radh/telemetry.hpp"

#include <algorithm>
#include <chrono>
#include <memory>
#include <stdexcept>
#include <utility>

#include <curl/curl.h>

namespace radh {
namespace {

using namespace std::chrono_literals;
using Clock = std::chrono::steady_clock;
constexpr auto pollMs = 200L;
constexpr std::string_view path = "/api/v1/debug/events";

bool tokenCharacter(unsigned char c)
{
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
           (c >= '0' && c <= '9') || c == '_' || c == '-';
}

bool cursorValid(std::string_view cursor)
{
    return cursor.size() >= 34 && cursor.size() <= 53 && cursor[32] == ':' &&
           std::ranges::all_of(cursor.substr(0, 32), [](char c) {
               return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f');
           }) &&
           std::ranges::all_of(cursor.substr(33), [](char c) { return c >= '0' && c <= '9'; });
}

std::string urlPart(CURLU* url, CURLUPart part)
{
    char* value = nullptr;
    if (curl_url_get(url, part, &value, 0) != CURLUE_OK) {
        return {};
    }
    std::unique_ptr<char, decltype(&curl_free)> owned(value, curl_free);
    return value;
}

std::string endpointFor(const std::string& base)
{
    if (base.size() > 512 || base.find_first_of("?#") != std::string::npos ||
        (base.find("://") == std::string::npos)) {
        return {};
    }
    std::unique_ptr<CURLU, decltype(&curl_url_cleanup)> url(curl_url(), curl_url_cleanup);
    if (!url || curl_url_set(url.get(), CURLUPART_URL, base.c_str(), CURLU_DISALLOW_USER) != CURLUE_OK ||
        urlPart(url.get(), CURLUPART_PATH) != "/") {
        return {};
    }
    const auto scheme = urlPart(url.get(), CURLUPART_SCHEME);
    const auto host = urlPart(url.get(), CURLUPART_HOST);
    if (scheme != "https" &&
        (scheme != "http" || (host != "127.0.0.1" && host != "[::1]" && host != "localhost"))) {
        return {};
    }
    if (curl_url_set(url.get(), CURLUPART_PATH, path.data(), 0) != CURLUE_OK) {
        return {};
    }
    return urlPart(url.get(), CURLUPART_URL);
}

struct Transfer {
    CURL* easy;
    SseParser parser;
    Clock::time_point lastByte = Clock::now();
    bool checked = false;
    bool isEventStream = false;
    bool callbackFailed = false;

    static std::size_t write(char* data, std::size_t size, std::size_t count, void* user) noexcept
    {
        auto& transfer = *static_cast<Transfer*>(user);
        try {
            if (!transfer.checked) {
                transfer.checked = true;
                long code = 0;
                char* rawType = nullptr;
                curl_easy_getinfo(transfer.easy, CURLINFO_RESPONSE_CODE, &code);
                curl_easy_getinfo(transfer.easy, CURLINFO_CONTENT_TYPE, &rawType);
                const std::string_view type = rawType ? rawType : "";
                transfer.isEventStream = code == 200 && type.substr(0, type.find(';')) == "text/event-stream";
            }
            if (!transfer.isEventStream) {
                return 0;
            }
            transfer.lastByte = Clock::now();
            transfer.parser.feed({data, size * count});
            return size * count;
        } catch (...) {
            transfer.callbackFailed = true;
            return 0;
        }
    }
};

std::string connectionError(long http, CURLcode result, bool eventStream, bool idle, bool callbackFailed)
{
    switch (http) {
    case 401: return "HTTP 401 — sprawdź token diagnostyczny";
    case 403: return "HTTP 403 — połączenie diagnostyczne jest niedozwolone";
    case 404: return "HTTP 404 — podaj adres nasłuchu diagnostycznego";
    case 503: return "HTTP 503 — serwer zajęty, trwa ponawianie";
    default: break;
    }
    if (http >= 300) {
        return "Odpowiedź HTTP " + std::to_string(http);
    }
    if (callbackFailed) {
        return "Błąd przetwarzania strumienia";
    }
    if (http == 200 && !eventStream) {
        return "Brak strumienia text/event-stream pod tym adresem";
    }
    if (idle) {
        return "Upłynął czas oczekiwania na dane SSE";
    }
    if (result == CURLE_COULDNT_CONNECT) {
        return "Nie można połączyć się z nasłuchem SSE";
    }
    if (result != CURLE_OK) {
        return curl_easy_strerror(result);
    }
    return "Serwer zamknął strumień SSE";
}

}

void SseParser::feed(std::string_view bytes)
{
    for (const char byte : bytes) {
        if (std::exchange(skipLf_, false) && byte == '\n') {
            continue;
        }
        if (byte == '\r' || byte == '\n') {
            endLine();
            skipLf_ = byte == '\r';
        } else if (line_.size() < maxFrame + 1) {
            line_.push_back(byte);
        } else {
            discard_ = true;
        }
    }
}

void SseParser::endLine()
{
    std::string_view line(line_);
    if (std::exchange(firstLine_, false) && line.starts_with("\xef\xbb\xbf")) {
        line.remove_prefix(3);
    }

    if (line.empty()) {
        if (discard_) {
            ++rejected_;
        } else if (hasData_) {
            data_.pop_back();
            handler_(data_, id_);
        }
        data_.clear();
        hasData_ = false;
        discard_ = false;
    } else if (!discard_) {
        const auto colon = line.find(':');
        const auto key = line.substr(0, colon);
        auto value = colon == line.npos ? std::string_view{} : line.substr(colon + 1);
        if (value.starts_with(' ')) {
            value.remove_prefix(1);
        }
        if (key == "data") {
            if (data_.size() + value.size() + 1 > maxFrame) {
                discard_ = true;
            } else {
                data_.append(value).push_back('\n');
                hasData_ = true;
            }
        } else if (key == "id" && value.size() <= 128 && value.find('\0') == value.npos) {
            id_ = value;
        }
    }
    line_.clear();
}

void EventQueue::push(Event event)
{
    std::lock_guard lock(mutex_);
    if (capacity_ == 0) {
        ++dropped_;
        return;
    }
    if (queue_.size() == capacity_) {
        queue_.pop_front();
        ++dropped_;
    }
    queue_.push_back(std::move(event));
}

void EventQueue::drain(std::vector<Event>& output)
{
    std::lock_guard lock(mutex_);
    output.clear();
    while (!queue_.empty()) {
        output.push_back(std::move(queue_.front()));
        queue_.pop_front();
    }
}

void EventQueue::reset()
{
    std::lock_guard lock(mutex_);
    queue_.clear();
    dropped_ = 0;
}

std::uint64_t EventQueue::dropped() const
{
    std::lock_guard lock(mutex_);
    return dropped_;
}

std::size_t EventQueue::size() const
{
    std::lock_guard lock(mutex_);
    return queue_.size();
}

CurlRuntime::CurlRuntime()
{
    if (curl_global_init(CURL_GLOBAL_DEFAULT) != CURLE_OK) {
        throw std::runtime_error("libcurl initialization failed");
    }
}

CurlRuntime::~CurlRuntime()
{
    curl_global_cleanup();
}

TelemetryClient::TelemetryClient(std::size_t queueCapacity)
    : queue_(queueCapacity), worker_([this](std::stop_token stop) { worker(stop); })
{
}

TelemetryClient::~TelemetryClient()
{
    worker_.request_stop();
    changed_.notify_all();
}

bool TelemetryClient::connect(std::string url, std::string token)
{
    auto endpoint = endpointFor(url);
    const bool valid = !endpoint.empty() && token.size() == 43 &&
                       std::ranges::all_of(token, tokenCharacter);
    {
        std::lock_guard lock(mutex_);
        ++generation_;
        queue_.reset();
        if (valid) {
            command_ = {std::move(endpoint), std::move(token)};
            status_ = {ConnectionState::connecting, {}, 0};
        } else {
            command_ = {};
            status_ = {ConnectionState::failed,
                       endpoint.empty() ? "Podaj lokalny adres HTTP lub adres HTTPS bez ścieżki"
                                        : "Token musi zawierać 43 znaki base64url",
                       0};
        }
    }
    changed_.notify_all();
    return valid;
}

void TelemetryClient::disconnect()
{
    {
        std::lock_guard lock(mutex_);
        ++generation_;
        command_ = {};
        status_.state = ConnectionState::disconnected;
        status_.message.clear();
    }
    changed_.notify_all();
}

ConnectionStatus TelemetryClient::status() const
{
    std::lock_guard lock(mutex_);
    return status_;
}

void TelemetryClient::worker(std::stop_token stop)
{
    std::uint64_t seen = 0;
    while (!stop.stop_requested()) {
        Command command;
        {
            std::unique_lock lock(mutex_);
            changed_.wait(lock, stop, [&] { return generation_.load() != seen; });
            if (stop.stop_requested()) {
                return;
            }
            seen = generation_.load();
            command = command_;
        }
        if (command.endpoint.empty()) {
            continue;
        }
        try {
            stream(stop, command, seen);
        } catch (const std::exception&) {
            std::lock_guard lock(mutex_);
            if (generation_.load() == seen) {
                status_.state = ConnectionState::failed;
                status_.message = "Błąd klienta sieciowego";
                command_ = {};
            }
        }
    }
}

void TelemetryClient::stream(std::stop_token stop, const Command& command, std::uint64_t generation)
{
    std::string cursor;
    auto delay = 1s;
    const auto cancelled = [&] { return stop.stop_requested() || generation_.load() != generation; };
    while (!cancelled()) {
        std::unique_ptr<CURL, decltype(&curl_easy_cleanup)> easy(curl_easy_init(), curl_easy_cleanup);
        std::unique_ptr<CURLM, decltype(&curl_multi_cleanup)> multi(curl_multi_init(), curl_multi_cleanup);
        if (!easy || !multi) {
            throw std::runtime_error("curl handle allocation failed");
        }

        std::uint64_t rejectedFrames = 0;
        bool received = false;
        Transfer transfer{easy.get(), SseParser([&](std::string_view payload, std::string_view id) {
            auto event = parseEvent(payload);
            std::lock_guard lock(mutex_);
            if (cancelled()) {
                return;
            }
            if (!event) {
                ++status_.malformed;
                return;
            }
            if ((event->eventId > 0 || event->name == "system.started") && cursorValid(id)) {
                cursor = id;
            }
            if (event->name == "telemetry.gap") {
                status_.serverDropped += event->number("dropped");
            } else if (event->name == "telemetry.reset") {
                ++status_.serverResets;
            }
            received = true;
            status_.state = ConnectionState::connected;
            status_.message.clear();
            queue_.push(std::move(*event));
        })};

        std::unique_ptr<curl_slist, decltype(&curl_slist_free_all)> headers(nullptr, curl_slist_free_all);
        const auto addHeader = [&](const std::string& value) {
            auto* appended = curl_slist_append(headers.get(), value.c_str());
            if (appended == nullptr) {
                throw std::runtime_error("curl header allocation failed");
            }
            headers.release();
            headers.reset(appended);
        };
        addHeader("Accept: text/event-stream");
        addHeader("Authorization: Bearer " + command.token);
        if (!cursor.empty()) {
            addHeader("Last-Event-ID: " + cursor);
        }

        curl_easy_setopt(easy.get(), CURLOPT_URL, command.endpoint.c_str());
        curl_easy_setopt(easy.get(), CURLOPT_HTTPHEADER, headers.get());
        curl_easy_setopt(easy.get(), CURLOPT_PROTOCOLS_STR, "HTTP,HTTPS");
        curl_easy_setopt(easy.get(), CURLOPT_PROXY, "");
        curl_easy_setopt(easy.get(), CURLOPT_FOLLOWLOCATION, 0L);
        curl_easy_setopt(easy.get(), CURLOPT_NOSIGNAL, 1L);
        curl_easy_setopt(easy.get(), CURLOPT_CONNECTTIMEOUT_MS, 3500L);
        curl_easy_setopt(easy.get(), CURLOPT_WRITEFUNCTION, Transfer::write);
        curl_easy_setopt(easy.get(), CURLOPT_WRITEDATA, &transfer);
        if (curl_multi_add_handle(multi.get(), easy.get()) != CURLM_OK) {
            throw std::runtime_error("curl transfer initialization failed");
        }

        int running = 1;
        bool idle = false;
        auto multiResult = CURLM_OK;
        while (!cancelled() && running) {
            multiResult = curl_multi_perform(multi.get(), &running);
            const auto rejected = transfer.parser.rejected();
            if (rejected > rejectedFrames) {
                std::lock_guard lock(mutex_);
                if (!cancelled()) {
                    status_.malformed += rejected - rejectedFrames;
                }
                rejectedFrames = rejected;
            }
            idle = Clock::now() - transfer.lastByte >= 20s;
            if (idle || multiResult != CURLM_OK || !running) {
                break;
            }
            multiResult = curl_multi_poll(multi.get(), nullptr, 0, pollMs, nullptr);
            if (multiResult != CURLM_OK) {
                break;
            }
        }

        int pending = 0;
        const auto* completion = curl_multi_info_read(multi.get(), &pending);
        const CURLcode result = completion && completion->msg == CURLMSG_DONE
                                    ? completion->data.result : CURLE_OK;
        long http = 0;
        curl_easy_getinfo(easy.get(), CURLINFO_RESPONSE_CODE, &http);
        curl_multi_remove_handle(multi.get(), easy.get());

        std::unique_lock lock(mutex_);
        if (cancelled()) {
            return;
        }
        const bool permanent = http == 401 || http == 403 || http == 404;
        status_.state = permanent ? ConnectionState::failed : ConnectionState::reconnecting;
        status_.message = multiResult == CURLM_OK
            ? connectionError(http, result, transfer.isEventStream, idle, transfer.callbackFailed)
            : curl_multi_strerror(multiResult);
        if (permanent) {
            command_ = {};
            return;
        }
        if (received) {
            delay = 1s;
        }
        changed_.wait_for(lock, stop, delay, cancelled);
        delay = std::min(16s, delay * 2);
    }
}

}
