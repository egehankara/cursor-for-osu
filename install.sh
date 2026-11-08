#!/usr/bin/env bash
# Installs osu-cursor for the current user. Run it again to update.
set -euo pipefail

source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
app_dir="$data_home/osu-cursor/app"
uuid="osu-cursor-trail@xrayzack1010.github.io"
extension_dir="$data_home/gnome-shell/extensions/$uuid"
bin_dir="$HOME/.local/bin"

python3 -c 'import PIL, gi' || {
    echo "Eksik paket: sudo pacman -S python-pillow python-gobject libadwaita" >&2
    exit 1
}

rm -rf "$app_dir"
mkdir -p "$app_dir" "$bin_dir" "$data_home/applications"
cp -r "$source_dir/osu_cursor" "$app_dir/"
find "$app_dir" -name __pycache__ -type d -prune -exec rm -rf {} +

rm -rf "$extension_dir"
mkdir -p "$extension_dir"
cp "$source_dir/extension/$uuid/"* "$extension_dir/"

cat > "$bin_dir/osu-cursor" <<EOF
#!/bin/sh
PYTHONPATH="$app_dir" exec python3 -m osu_cursor "\$@"
EOF
chmod +x "$bin_dir/osu-cursor"

cp "$source_dir/data/osu-cursor.desktop" "$data_home/applications/"
update-desktop-database "$data_home/applications" 2>/dev/null || true

# GNOME only discovers new extensions at login, so turn it on for the next one.
PYTHONPATH="$app_dir" python3 -c 'from osu_cursor.gnome import enable_extension; enable_extension()'

echo "Kuruldu. Trail eklentisinin yüklenmesi için bir kez oturumu kapatıp aç."
