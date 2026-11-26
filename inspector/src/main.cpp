#include "radh/inspector.hpp"

#include <algorithm>
#include <array>
#include <cstdio>
#include <stdexcept>

namespace {

class Window {
public:
    Window()
    {
        SetConfigFlags(FLAG_WINDOW_RESIZABLE | FLAG_WINDOW_HIGHDPI);
        InitWindow(1260, 800, "RADH Inspector");
        if (!IsWindowReady()) {
            throw std::runtime_error("Nie można otworzyć okna RADH Inspector.");
        }
        SetWindowMinSize(970, 635);
        SetTargetFPS(60);
        SetExitKey(KEY_NULL);
    }

    ~Window() { CloseWindow(); }
    Window(const Window&) = delete;
    Window& operator=(const Window&) = delete;
};

class DesktopFont {
public:
    explicit DesktopFont(std::initializer_list<const char*> paths)
    {
        constexpr std::array extra{0x00b5, 0x0104, 0x0105, 0x0106, 0x0107, 0x0118, 0x0119,
            0x0141, 0x0142, 0x0143, 0x0144, 0x00d3, 0x00f3, 0x015a, 0x015b, 0x0179, 0x017a,
            0x017b, 0x017c, 0x2013, 0x2014, 0x2026, 0x2192};
        std::array<int, 95 + extra.size()> codepoints{};
        for (int c = 32; c < 127; ++c) {
            codepoints[c - 32] = c;
        }
        std::ranges::copy(extra, codepoints.begin() + 95);
        for (const auto* path : paths) {
            if (FileExists(path)) {
                font_ = LoadFontEx(path, 32, codepoints.data(), static_cast<int>(codepoints.size()));
                if (font_.texture.id != GetFontDefault().texture.id && IsFontValid(font_)) {
                    SetTextureFilter(font_.texture, TEXTURE_FILTER_BILINEAR);
                    owned_ = true;
                    return;
                }
            }
        }
        font_ = GetFontDefault();
    }

    ~DesktopFont()
    {
        if (owned_) {
            UnloadFont(font_);
        }
    }

    DesktopFont(const DesktopFont&) = delete;
    DesktopFont& operator=(const DesktopFont&) = delete;
    Font get() const { return font_; }

private:
    Font font_{};
    bool owned_ = false;
};

}

int main()
{
    try {
        radh::CurlRuntime curl;
        Window window;
        DesktopFont sans{
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
            "/usr/share/fonts/TTF/DejaVuSans.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
        };
        DesktopFont mono{
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono.ttf",
            "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
            "/usr/share/fonts/adwaita-mono-fonts/AdwaitaMono-Regular.ttf",
            "/usr/share/fonts/liberation-mono-fonts/LiberationMono-Regular.ttf",
            "C:/Windows/Fonts/consola.ttf",
        };
        radh::Inspector inspector({sans.get(), mono.get()});
        inspector.run();
        return 0;
    } catch (const std::exception& error) {
        std::fprintf(stderr, "RADH Inspector: %s\n", error.what());
        return 1;
    }
}
