#!/usr/bin/env bash
# Builds, updates and removes the KWin trail effect, so Plasma needs no commands of its own.
#   install   build from the sources next to this script and turn the effect on (install.sh)
#   login     rebuild after a Plasma or Qt update, run at every Plasma login
#   remove    turn the effect off and delete everything this script made (uninstall.sh)
# The effect goes into the user's own Qt plugin folder, so no sudo is needed. KWin finds
# it there through QT_PLUGIN_PATH, which is set for the session below.
set -euo pipefail

kwin_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
data_dir="$data_home/osu-cursor"
app_dir="$data_dir/app"
build_dir="${XDG_CACHE_HOME:-$HOME/.cache}/osu-cursor/kwin-build"
log="$build_dir/build.log"
plugin_root="$HOME/.local/lib/qt6/plugins"
plugin="$plugin_root/kwin/effects/plugins/osu-cursor-trail.so"
built_for="$data_dir/kwin-built-for"
environment_file="$config_home/environment.d/cursor-for-osu.conf"
plasma_env_file="$config_home/plasma-workspace/env/cursor-for-osu.sh"
autostart_file="$config_home/autostart/cursor-for-osu-trail.desktop"
effect=osu-cursor-trail

# Prints a message in the user's language, see osu_cursor/i18n.py.
say() {
    local code_dir="$app_dir"
    [ -d "$kwin_dir/../osu_cursor" ] && code_dir="$kwin_dir/.."
    if command -v python3 >/dev/null 2>&1 &&
        PYTHONPATH="$code_dir" python3 -m osu_cursor.i18n "$@" 2>/dev/null; then
        return
    fi
    local message="$1" pair
    shift
    for pair in "$@"; do
        message="${message//\{${pair%%=*}\}/${pair#*=}}"
    done
    printf '%s\n' "$message"
}

# A desktop notification, for the login check that has no terminal.
notify() {
    gdbus call --session --dest org.freedesktop.Notifications --object-path /org/freedesktop/Notifications \
        --method org.freedesktop.Notifications.Notify "Cursor for osu!" 0 io.github.egehankara.CursorForOsu \
        "Cursor for osu!" "$1" '[]' '{}' -1 >/dev/null 2>&1 || true
}

kwin_call() {
    gdbus call --session --dest org.kde.KWin --object-path /Effects \
        --method "org.kde.kwin.Effects.$1" "$effect" 2>/dev/null || true
}

qtpaths_command() {
    command -v qtpaths6 || echo /usr/lib/qt6/bin/qtpaths6
}

# The KWin and Qt the effect was built against. A new one of either needs a new build.
fingerprint() {
    echo "$(kwin_wayland --version 2>/dev/null) qt $("$(qtpaths_command)" --query QT_VERSION 2>/dev/null)"
}

# The packages the effect is built with, on the distributions we know.
build_packages() {
    local id="" id_like=""
    if [ -r /etc/os-release ]; then
        id="$(. /etc/os-release && echo "${ID:-}")"
        id_like="$(. /etc/os-release && echo "${ID_LIKE:-}")"
    fi
    case " $id $id_like " in
        *" arch "*) echo "sudo pacman -S --needed kwin extra-cmake-modules cmake base-devel vulkan-headers" ;;
        *" debian "* | *" ubuntu "*) echo "sudo apt install kwin-dev extra-cmake-modules cmake g++ pkgconf libwayland-dev libdrm-dev" ;;
        *) echo "cmake, extra-cmake-modules, a C++ compiler, KWin 6.6+ development files" ;;
    esac
}

# Builds the effect into the build folder. The output goes to the log, it is long.
build() {
    local version
    version="$(kwin_wayland --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | head -n 1 || true)"
    if [ -n "$version" ] && [ "$(printf '%s\n' 6.6 "$version" | sort -V | head -n 1)" != 6.6 ]; then
        say "KWin {version} is too old for the trail, it needs Plasma 6.6 or newer. The cursor works without it." \
            version="$version" >&2
        return 1
    fi
    if ! command -v cmake >/dev/null 2>&1 || ! command -v c++ >/dev/null 2>&1; then
        say "The trail effect could not be built. Install these packages and run install.sh again: {command}" \
            command="$(build_packages)" >&2
        return 1
    fi
    mkdir -p "$build_dir"
    if ! { cmake -S "$kwin_dir" -B "$build_dir" -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF &&
        cmake --build "$build_dir"; } >"$log" 2>&1; then
        tail -n 20 "$log" >&2
        say "The trail effect could not be built. Install these packages and run install.sh again: {command}" \
            command="$(build_packages)" >&2
        say "The full build output is in {file}." file="$log" >&2
        return 1
    fi
}

# Puts the plugin folder on KWin's QT_PLUGIN_PATH. Plasma runs the env script at every login
# and hands its variables to the systemd session before KWin starts. Set that way, and not with
# environment.d, uninstalling can take the variable away again without a reboot.
# This session gets it right away, for a KWin that starts again.
add_plugin_path() {
    rm -f "$environment_file"  # used by a build before this one
    mkdir -p "$(dirname "$plasma_env_file")"
    printf '%s\n' "# Lets KWin find the Cursor for osu! trail, made by its install.sh." \
        "case \":\${QT_PLUGIN_PATH:-}:\" in *\":$plugin_root:\"*) ;; *) export QT_PLUGIN_PATH=\"$plugin_root\${QT_PLUGIN_PATH:+:\$QT_PLUGIN_PATH}\" ;; esac" \
        >"$plasma_env_file"
    local current
    current="$(systemctl --user show-environment 2>/dev/null | sed -n 's/^QT_PLUGIN_PATH=//p' || true)"
    case ":$current:" in
        *":$plugin_root:"*) ;;
        *) systemctl --user set-environment "QT_PLUGIN_PATH=$plugin_root${current:+:$current}" 2>/dev/null || true ;;
    esac
}

remove_plugin_path() {
    rm -f "$environment_file" "$plasma_env_file"
    # The folders too, when nothing else is in them. They were usually made for these files.
    rmdir -p "$(dirname "$environment_file")" "$(dirname "$plasma_env_file")" 2>/dev/null || true
    local current rest
    current="$(systemctl --user show-environment 2>/dev/null | sed -n 's/^QT_PLUGIN_PATH=//p' || true)"
    case ":$current:" in
        *":$plugin_root:"*)
            rest="$(printf '%s' "$current" | tr ':' '\n' | grep -vxF "$plugin_root" | paste -sd: || true)"
            if [ -n "$rest" ]; then
                systemctl --user set-environment "QT_PLUGIN_PATH=$rest" 2>/dev/null || true
            else
                systemctl --user unset-environment QT_PLUGIN_PATH 2>/dev/null || true
            fi
            ;;
    esac
}

# Earlier versions installed the effect for everyone with sudo. Two copies would leave it to
# chance which one KWin loads, so that one goes.
remove_system_copy() {
    local system_plugin
    system_plugin="$("$(qtpaths_command)" --query QT_INSTALL_PLUGINS 2>/dev/null)/kwin/effects/plugins/osu-cursor-trail.so"
    if [ -e "$system_plugin" ]; then
        say "An older copy of the trail is in the system folder. Removing it needs your password."
        sudo rm -f -- "$system_plugin" || say "Remove it yourself: {command}" command="sudo rm $system_plugin" >&2
    fi
}

write_autostart() {
    mkdir -p "$(dirname "$autostart_file")"
    cat >"$autostart_file" <<EOF
[Desktop Entry]
Type=Application
Name=Cursor for osu! trail check
Comment=Rebuilds the cursor trail after a Plasma update
Exec=bash "$data_dir/kwin/trail.sh" login
OnlyShowIn=KDE;
NoDisplay=true
EOF
}

case "${1:-}" in
    install)
        status_before="$(kwin_call isEffectLoaded)"
        build || exit 1
        remove_system_copy
        mkdir -p "$(dirname "$plugin")"
        cmp -s "$build_dir/osu-cursor-trail.so" "$plugin" && unchanged=true
        # A new file, not a write into the one KWin may have open.
        cp "$build_dir/osu-cursor-trail.so" "$plugin.new" && mv -f "$plugin.new" "$plugin"
        fingerprint >"$built_for"
        add_plugin_path
        write_autostart
        # Turned on like in System Settings, the way the GNOME install turns its extension on.
        kwriteconfig6 --file kwinrc --group Plugins --key "${effect}Enabled" true 2>/dev/null || true
        gdbus call --session --dest org.kde.KWin --object-path /KWin \
            --method org.kde.KWin.reconfigure >/dev/null 2>&1 || true

        # KWin keeps running the effect it loaded. Another one is loaded right away, if this
        # KWin already looks in the user's plugin folder.
        if [ "$status_before" = "(true,)" ]; then
            [ "${unchanged:-}" = true ] && exit 0
            exit 10
        fi
        kwin_call loadEffect >/dev/null
        [ "$(kwin_call isEffectLoaded)" = "(true,)" ] && exit 0
        exit 10
        ;;
    login)
        [ -e "$plugin" ] || exit 0
        [ "$(fingerprint)" = "$(cat "$built_for" 2>/dev/null)" ] && exit 0
        if ! build 2>/dev/null; then
            notify "$(say "Plasma was updated and the trail could not be rebuilt. Run install.sh again to see why.")"
            exit 1
        fi
        loaded="$(kwin_call isEffectLoaded)"
        cp "$build_dir/osu-cursor-trail.so" "$plugin.new" && mv -f "$plugin.new" "$plugin"
        fingerprint >"$built_for"
        if [ "$loaded" != "(true,)" ]; then
            kwin_call loadEffect >/dev/null
            [ "$(kwin_call isEffectLoaded)" = "(true,)" ] && exit 0
        fi
        notify "$(say "The trail was rebuilt for the new Plasma. Log out and back in once to load it.")"
        ;;
    remove)
        # Unloading it stops it right away, like turning the GNOME extension off.
        kwin_call unloadEffect >/dev/null
        kwriteconfig6 --file kwinrc --group Plugins --key "${effect}Enabled" --delete 2>/dev/null || true
        rm -f "$plugin" "$autostart_file" "$built_for"
        rm -rf "$build_dir"
        rmdir "$(dirname "$build_dir")" 2>/dev/null || true
        rmdir -p "$(dirname "$plugin")" 2>/dev/null || true
        remove_plugin_path
        remove_system_copy
        ;;
    *)
        echo "usage: trail.sh install | login | remove" >&2
        exit 2
        ;;
esac
