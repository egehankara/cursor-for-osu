#!/usr/bin/env bash
# Installs Cursor for osu! for the current user. Run it again to update.
# uninstall.sh, or "cursor-for-osu uninstall", removes it again.
set -euo pipefail

source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
app_dir="$data_home/osu-cursor/app"
uuid="cursor-for-osu-trail@egehankara.github.io"
old_uuid="osu-cursor-trail@xrayzack1010.github.io"  # the extension's earlier name
extension_dir="$data_home/gnome-shell/extensions/$uuid"
bin_dir="$HOME/.local/bin"
icon_dir="$data_home/icons/hicolor"

# Prints a message in the user's language, see osu_cursor/i18n.py.
say() {
    if command -v python3 >/dev/null 2>&1; then
        PYTHONPATH="$source_dir" python3 -m osu_cursor.i18n "$@"
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

# The install command for the packages the app needs, on the distributions we know.
package_command() {
    local id="" id_like=""
    if [ -r /etc/os-release ]; then
        id="$(. /etc/os-release && echo "${ID:-}")"
        id_like="$(. /etc/os-release && echo "${ID_LIKE:-}")"
    fi
    case " $id $id_like " in
        *" arch "*) echo "sudo pacman -S --needed python python-pillow python-gobject libadwaita" ;;
        *" debian "* | *" ubuntu "*) echo "sudo apt install python3 python3-pil python3-gi gir1.2-adw-1" ;;
        *" fedora "*) echo "sudo dnf install python3 python3-pillow python3-gobject libadwaita" ;;
        *" suse "* | *" opensuse "*) echo "sudo zypper install python3 python3-Pillow python3-gobject typelib-1_0-Adw-1" ;;
        *) echo "Python 3.10+, Pillow, PyGObject, libadwaita 1.5+" ;;
    esac
}

# Pillow, PyGObject and the GTK 4 and libadwaita bindings, with a libadwaita new enough for the window.
adw_version="$(command -v python3 >/dev/null && python3 - 2>/dev/null <<'EOF'
import PIL, gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw
print(f"{Adw.get_major_version()}.{Adw.get_minor_version()}")
EOF
)" || {
    say "Missing packages: {command}" command="$(package_command)" >&2
    exit 1
}
if [ "${adw_version#1.}" -lt 5 ] 2>/dev/null; then
    say "libadwaita {version} is too old, Cursor for osu! needs 1.5 or newer." version="$adw_version" >&2
    exit 1
fi

rm -rf "$app_dir"
mkdir -p "$app_dir" "$bin_dir" "$data_home/applications"
cp -r "$source_dir/osu_cursor" "$app_dir/"
rm -rf "$app_dir/osu_cursor/__pycache__"
cp "$source_dir/uninstall.sh" "$data_home/osu-cursor/uninstall.sh"

rm -rf "$extension_dir" "$data_home/gnome-shell/extensions/$old_uuid"
mkdir -p "$extension_dir"
cp "$source_dir/extension/$uuid/"* "$extension_dir/"

rm -f "$bin_dir/osu-cursor" "$data_home/applications/osu-cursor.desktop"  # the old name
cat > "$bin_dir/cursor-for-osu" <<EOF
#!/bin/sh
PYTHONPATH="$app_dir" exec python3 -m osu_cursor "\$@"
EOF
chmod +x "$bin_dir/cursor-for-osu"

# The full path, because ~/.local/bin is not on the launcher's PATH everywhere.
sed "s|^Exec=cursor-for-osu\$|Exec=\"$bin_dir/cursor-for-osu\"|" \
    "$source_dir/data/cursor-for-osu.desktop" > "$data_home/applications/cursor-for-osu.desktop"
update-desktop-database "$data_home/applications" 2>/dev/null || true

# The app icon and its one-colour version for small sizes.
for icon in "$source_dir"/data/icons/hicolor/*/apps/*.svg; do
    target="$icon_dir/${icon#"$source_dir/data/icons/hicolor/"}"
    mkdir -p "$(dirname "$target")"
    cp "$icon" "$target"
done

# GNOME only discovers new extensions at login, so turn it on for the next one.
PYTHONPATH="$app_dir" python3 -c 'from osu_cursor.gnome import enable_extension; enable_extension()' 2>/dev/null ||
    extension_off=true

say "Installed. Log out and back in once so the trail extension is loaded."
if [ "${extension_off:-}" = true ]; then
    say "The trail extension is turned off. Turn it on in the Extensions app."
fi

# The extension says which GNOME Shell versions it was made for.
shell_version="$(gnome-shell --version 2>/dev/null | grep -oE '[0-9]+' | head -n 1 || true)"
supported="$(python3 -c 'import json, sys; print(", ".join(json.load(open(sys.argv[1]))["shell-version"]))' \
    "$source_dir/extension/$uuid/metadata.json")"
if [ -n "$shell_version" ] && ! grep -q "\"$shell_version\"" "$source_dir/extension/$uuid/metadata.json"; then
    say "The trail extension is made for GNOME Shell {supported} and this computer has {version}. The cursor works, the trail may not." \
        supported="$supported" version="$shell_version"
fi
