<div align="center">

<img src="data/icons/hicolor/scalable/apps/io.github.egehankara.CursorForOsu.svg" width="112" alt="Cursor for osu! icon">

# Cursor for osu!

**Your osu! skin's cursor and trail, on your whole Linux desktop.**

GNOME · KDE Plasma · Wayland

**English** · [Türkçe](README.tr.md)

<img src="data/screenshots/window-en.png" width="440" alt="The Cursor for osu! window with a list of skins">

</div>

Cursor for osu! takes the cursor from an osu! skin and makes it your mouse cursor everywhere on
your Linux desktop: in your browser, your file manager, on the desktop itself. The **trail** behind
it comes along too, so moving the mouse feels like it does in the game.

Add a skin's `.osk` file or folder to the app and **click it, that's all**. You don't need to unpack
anything. The cursor has the same size as in osu!lazer and the trail fades the same way. Skins you
export from osu!lazer show up in the app by themselves, so switching between them is one click.
osu! doesn't need to be open, or even installed. When you want your old cursor back, one button
puts it back.

> [!IMPORTANT]
> **Linux only.** You need **GNOME 51** or **KDE Plasma 6.6+**, on **Wayland**.
> On an older GNOME the cursor still works, only the trail doesn't.
>
> Not sure what you have? Run these in a terminal:
> - `echo $XDG_CURRENT_DESKTOP` prints `GNOME` or `KDE`.
> - `echo $XDG_SESSION_TYPE` prints `wayland`. If it says `x11`, pick a Wayland session on the login screen.
> - `gnome-shell --version` or `plasmashell --version` prints your version.

## Install

<details>
<summary><b>New to the terminal?</b></summary>

Open **Terminal** or **Console** on GNOME, **Konsole** on KDE Plasma. Copy a command, paste it
with **Ctrl+Shift+V** and press **Enter**. Commands starting with `sudo` ask for your password,
and nothing appears while you type it. That is normal.

</details>

### 1. Install the packages

Open your distribution and run **only the command for your desktop**.

<details>
<summary><b>Arch, CachyOS, Manjaro</b></summary>

GNOME:

```sh
sudo pacman -S --needed git python python-pillow python-gobject libadwaita
```

KDE Plasma:

```sh
sudo pacman -S --needed git python python-pillow python-gobject libadwaita plasma-workspace libkscreen kwin extra-cmake-modules cmake base-devel vulkan-headers
```

</details>

<details>
<summary><b>Ubuntu, Debian, Kubuntu</b></summary>

GNOME:

```sh
sudo apt install git python3 python3-pil python3-gi gir1.2-adw-1
```

KDE Plasma (Kubuntu):

```sh
sudo apt install git python3 python3-pil python3-gi gir1.2-adw-1 plasma-workspace libkscreen-bin kwin-dev extra-cmake-modules cmake g++ pkgconf libwayland-dev libdrm-dev
```

</details>

<details>
<summary><b>Fedora</b> (GNOME)</summary>

```sh
sudo dnf install git python3 python3-pillow python3-gobject libadwaita
```

</details>

<details>
<summary><b>openSUSE</b> (GNOME)</summary>

```sh
sudo zypper install git python3 python3-Pillow python3-gobject typelib-1_0-Adw-1
```

</details>

<details>
<summary><b>KDE Plasma on Fedora, openSUSE or another distribution</b></summary>

The trail on KDE Plasma was tested on Arch-based distributions and Kubuntu. Elsewhere it should
work too: install the GNOME command of your distribution above (the app needs those on KDE too), plus **cmake**,
**extra-cmake-modules**, a **C++ compiler** and the **KWin development files**. If something is
missing, `install.sh` tells you, and the cursor works even without the trail.

</details>

### 2. Download and install the app

```sh
git clone https://github.com/egehankara/cursor-for-osu.git
cd cursor-for-osu
bash install.sh
```

> [!TIP]
> **Keep the `cursor-for-osu` folder.** Updates are made from it.

### 3. Turn on the trail

**On GNOME:** log out and log back in once. That's it.

<details>
<summary>Can't find the log out option on GNOME? Here is the terminal command. <b><i>GNOME KNOWS BEST.</i></b></summary>

```sh
gnome-session-quit
```

</details>

**On KDE Plasma:** log out and log back in once. That's it. You don't need to build anything:
`install.sh` in step 2 already built the trail for your Plasma and turned it on, that was the
minute it took.

### 4. Pick a skin

Open **Cursor for osu!** from your applications and click a skin. Done!

## Usage

- **Add skins** with the **.osk** and **Folder** buttons, or drag them onto the window.
- **Click a card** to apply it. **Right-click** to rename, open its folder or remove it.
- **Change the size** with the slider, or click the number and type one.
- **Settings** at the top holds the rest: the in-game size, keeping system cursors, watching
  osu!lazer exports and the osu!lazer folder.

### Where do I get skins?

- **From osu!lazer:** open the skin settings in the game and use **Export selected skin**. The
  app picks up the export by itself, you don't need to do anything else.
- **From the internet:** players share their skins as `.osk` files, on the osu! forums and on
  skin sites. Search for "osu! skins". Download the `.osk` and add it with the **.osk** button.

## Troubleshooting

**The trail doesn't show up.**

- Did you log out and back in after installing? The trail only starts after that.
- **GNOME:** open the **Extensions** app and check that **Cursor for osu! Trail** is on. The
  trail needs GNOME 51.
- **KDE Plasma:** open **System Settings → Desktop Effects** and check that **Cursor for osu!
  Trail** is on. If it isn't listed, run `bash install.sh` again in the `cursor-for-osu` folder
  and read what it says.
- **On an X11 session** there is no trail. Pick a Wayland session on the login screen.

**The trail disappears sometimes.** That is on purpose: there is no trail over fullscreen
windows, while an app hides the cursor, and, with **Keep system cursors** on, behind the text
and resize cursors.

## Updating

The app tells you when a new version is out. Then run:

```sh
cd cursor-for-osu
git pull
bash install.sh
```

Log out and back in if it tells you to. On KDE Plasma the trail is rebuilt by itself after
Plasma updates, at your next login, so keep the packages from step 1 installed.
If you installed on KDE Plasma before the trail moved to your home folder, the first update asks
for your password once, to remove the old copy from the system folder.

## Uninstalling

```sh
cursor-for-osu uninstall               # add --keep-data to keep your skins and settings
```

Your previous cursor comes back and the trail is removed, on GNOME and KDE Plasma alike.
The skin files you added from are never touched. After that you can delete the
`cursor-for-osu` folder too.

## More

<details>
<summary>How it works</summary>

- **The cursor is a real cursor theme** generated from the skin, so it is the low-latency
  hardware cursor. Its size matches the game, Screen Scaling included.
- **The trail is drawn by the desktop**: a GNOME Shell extension (`extension/`) or a KWin
  effect (`kwin/`). Fade times, spacing and blending come from osu!lazer's `CursorTrail` and
  `LegacyCursorTrail`. It turns off over fullscreen windows and while an app hides the cursor.
- **Keep system cursors** leaves the text, resize, move, not-allowed and crosshair cursors to
  your previous theme, tinted in the skin's colours.
- **Not supported:** `CursorExpand` (a cursor theme can't react to clicks) and spinning
  `CursorRotate` skins, which are shown still.

</details>

<details>
<summary>Command line</summary>

```sh
cursor-for-osu apply skin.osk   # apply a skin
cursor-for-osu size 1.2         # 0.1 to 2.0, like in the game
cursor-for-osu reset            # back to the previous cursor
cursor-for-osu status
```

</details>

<details>
<summary>Languages</summary>

The app follows your desktop language: English, Türkçe, Español, Português (Brasil), Deutsch,
Français, Русский, Polski, 日本語 and 简体中文. Start it in another one with
`LANGUAGE=de cursor-for-osu`. Translations are in `osu_cursor/locale/`.

</details>

<details>
<summary>Contributing and tests</summary>

```sh
python3 -m pytest
cmake -S kwin -B build && cmake --build build   # KWin trail and its tests
ctest --test-dir build --output-on-failure
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

</details>

---

KDE Plasma support by [@MehmetAkifUgur](https://github.com/MehmetAkifUgur).
A fan-made tool, **not made by or affiliated with ppy or osu!**.
[MIT License](LICENSE). The trail behaviour is adapted from [osu!](https://github.com/ppy/osu)
(MIT, Copyright (c) ppy Pty Ltd), see [THIRD-PARTY-NOTICES](THIRD-PARTY-NOTICES).
Skin images must not be added to this repository, they belong to their creators.
