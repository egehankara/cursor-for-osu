#!/usr/bin/env bash
# Removes Cursor for osu!: puts the previous cursor back, then deletes the app,
# the trail extension and the cursor themes it made.
# With --keep-data the skin list and settings stay, for a later install.
# install.sh copies this script next to the app, "cursor-for-osu uninstall" runs that copy.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
data_dir="$data_home/osu-cursor"
app_dir="$data_dir/app"
uuid="cursor-for-osu-trail@egehankara.github.io"
old_uuid="osu-cursor-trail@xrayzack1010.github.io"  # the extension's earlier name
extension_dir="$data_home/gnome-shell/extensions/$uuid"
bin_dir="$HOME/.local/bin"

# Run from the source folder or from the copy next to the installed app.
if [ -d "$script_dir/osu_cursor" ]; then
    code_dir="$script_dir"
else
    code_dir="$app_dir"
fi

# Prints a message in the user's language, see osu_cursor/i18n.py.
say() {
    if command -v python3 >/dev/null 2>&1; then
        PYTHONPATH="$code_dir" python3 -m osu_cursor.i18n "$@" 2>/dev/null
    else
        # Without Python there are no translations, the English text is filled in here.
        local message="$1" pair
        shift
        for pair in "$@"; do
            message="${message//\{${pair%%=*}\}/${pair#*=}}"
        done
        printf '%s\n' "$message"
    fi
}

keep_data=false
for argument in "$@"; do
    case "$argument" in
        --keep-data) keep_data=true ;;
        *)
            say "Unknown option: {option}" option="$argument" >&2
            exit 2
            ;;
    esac
done

# The app is deleted below, so its messages are made first.
removed_message="$(say "Cursor for osu! was removed.")"
kept_message="$(say "The skin list and settings were kept in {folder}." folder="$data_dir")"

# Put the previous cursor back while the app is still here.
if [ -d "$app_dir/osu_cursor" ]; then
    PYTHONPATH="$app_dir" python3 -m osu_cursor reset >/dev/null 2>&1 || true
fi
current_theme="$(gsettings get org.gnome.desktop.interface cursor-theme 2>/dev/null || true)"
if [[ "$current_theme" == "'osu-cursor-"* ]]; then
    gsettings reset org.gnome.desktop.interface cursor-theme 2>/dev/null || true
fi

# Taking it out of the enabled list makes GNOME Shell stop it right away.
gnome-extensions disable "$uuid" >/dev/null 2>&1 || true
gnome-extensions disable "$old_uuid" >/dev/null 2>&1 || true
python3 - "$uuid" "$old_uuid" <<'EOF' 2>/dev/null || true
import ast, subprocess, sys

uuids = sys.argv[1:]
key = ["org.gnome.shell", "enabled-extensions"]
current = subprocess.run(["gsettings", "get", *key], check=True, capture_output=True, text=True).stdout
enabled = ast.literal_eval(current.strip().removeprefix("@as "))
remaining = [uuid for uuid in enabled if uuid not in uuids]
if remaining != enabled:
    subprocess.run(["gsettings", "set", *key, str(remaining)], check=True)
EOF

rm -rf "$extension_dir" "$data_home/gnome-shell/extensions/$old_uuid"
rm -f "$bin_dir/cursor-for-osu" "$data_home/applications/cursor-for-osu.desktop"
update-desktop-database "$data_home/applications" 2>/dev/null || true

# Only the themes this app made, they carry a marker file.
for theme in "$data_home/icons"/osu-cursor-*; do
    if [ -e "$theme/.osu-cursor" ]; then
        rm -rf "$theme"
    fi
done

if $keep_data; then
    rm -rf "$app_dir" "$data_dir/source" "$data_dir/uninstall.sh"
    rm -f "$data_dir/state.json" "$data_dir/previous.json" "$data_dir"/trail-*.rgba
    echo "$removed_message"
    echo "$kept_message"
else
    rm -rf "$data_dir"
    echo "$removed_message"
fi
