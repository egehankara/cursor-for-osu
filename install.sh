#!/usr/bin/env bash
# Installs Cursor for osu! for the current user. Run it again to update.
# uninstall.sh, or "cursor-for-osu uninstall", removes it again.
set -euo pipefail

source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
app_dir="$data_home/osu-cursor/app"
uuid="osu-cursor-trail@xrayzack1010.github.io"
extension_dir="$data_home/gnome-shell/extensions/$uuid"
bin_dir="$HOME/.local/bin"

# Prints a message in the user's language, see osu_cursor/i18n.py.
say() {
    PYTHONPATH="$source_dir" python3 -m osu_cursor.i18n "$@"
}

python3 -c 'import PIL, gi' 2>/dev/null || {
    say "Missing packages: {command}" command="sudo pacman -S python-pillow python-gobject libadwaita" >&2
    exit 1
}

rm -rf "$app_dir"
mkdir -p "$app_dir" "$bin_dir" "$data_home/applications"
cp -r "$source_dir/osu_cursor" "$app_dir/"
find "$app_dir" -name __pycache__ -type d -prune -exec rm -rf {} +
cp "$source_dir/uninstall.sh" "$data_home/osu-cursor/uninstall.sh"

rm -rf "$extension_dir"
mkdir -p "$extension_dir"
cp "$source_dir/extension/$uuid/"* "$extension_dir/"

rm -f "$bin_dir/osu-cursor" "$data_home/applications/osu-cursor.desktop"  # the old name
cat > "$bin_dir/cursor-for-osu" <<EOF
#!/bin/sh
PYTHONPATH="$app_dir" exec python3 -m osu_cursor "\$@"
EOF
chmod +x "$bin_dir/cursor-for-osu"

cp "$source_dir/data/cursor-for-osu.desktop" "$data_home/applications/"
update-desktop-database "$data_home/applications" 2>/dev/null || true

# GNOME only discovers new extensions at login, so turn it on for the next one.
PYTHONPATH="$app_dir" python3 -c 'from osu_cursor.gnome import enable_extension; enable_extension()'

say "Installed. Log out and back in once so the trail extension is loaded."
