# Cursor for osu!

<p align="center">
  <img src="data/icons/hicolor/scalable/apps/io.github.egehankara.CursorForOsu.svg" width="128" alt="Cursor for osu! icon">
</p>

[English](#english) · [Türkçe](#türkçe)

## English

Use the cursor and cursor trail of your osu! skins on GNOME or KDE Plasma, outside the game.

KDE Plasma support by [@MehmetAkifUgur](https://github.com/MehmetAkifUgur).

Cursor for osu! is a fan-made tool. It is not made by or affiliated with ppy or osu!.

### Requirements

- GNOME Shell 51 (Wayland) for the trail. The cursor itself works on any GNOME, the trail extension
  is only marked for the GNOME Shell version it was tested on.
- KDE Plasma 6.6 on Wayland for the Plasma integration. See [Plasma installation](#plasma-installation).
- Python 3.10 or newer, Pillow, PyGObject and libadwaita 1.5 or newer.

Install the packages for your distribution:

| Distribution | Command |
| --- | --- |
| Arch, CachyOS, Manjaro | `sudo pacman -S --needed python python-pillow python-gobject libadwaita` |
| Ubuntu, Debian | `sudo apt install python3 python3-pil python3-gi gir1.2-adw-1` |
| Fedora | `sudo dnf install python3 python3-pillow python3-gobject libadwaita` |
| openSUSE | `sudo zypper install python3 python3-Pillow python3-gobject typelib-1_0-Adw-1` |

`install.sh` checks for them and prints the command for your distribution if something is missing.

### Installation

```sh
git clone https://github.com/egehankara/cursor-for-osu.git
cd cursor-for-osu
bash install.sh
```

On GNOME, log out and back in once after the first install, because GNOME only finds new extensions at login.
Then open **Cursor for osu!** from your applications.

To update, get the new version and install again:

```sh
cd cursor-for-osu
git pull
bash install.sh
```

### Plasma installation

Run `bash install.sh` from a Plasma Wayland session with the Python and GTK dependencies above.
Theme changes use `plasma-apply-cursortheme`, `kreadconfig6`, `kwriteconfig6`, `gdbus` and `kscreen-doctor`.
Use these commands to install the extra packages and build the KWin effect.

On Kubuntu 26.04:

```sh
sudo apt install plasma-workspace libkscreen-bin kwin-dev extra-cmake-modules cmake g++ pkgconf libwayland-dev libdrm-dev
build_dir="${XDG_CACHE_HOME:-$HOME/.cache}/cursor-for-osu/kwin"
cmake -S kwin -B "$build_dir" -DKDE_INSTALL_PLUGINDIR="$(qtpaths6 --query QT_INSTALL_PLUGINS)"
cmake --build "$build_dir"
ctest --test-dir "$build_dir" --output-on-failure
sudo cmake --install "$build_dir"
```

On Arch, CachyOS and Manjaro, where `qtpaths6` is not on the PATH:

```sh
sudo pacman -S --needed plasma-workspace libkscreen kwin extra-cmake-modules cmake base-devel
build_dir="${XDG_CACHE_HOME:-$HOME/.cache}/cursor-for-osu/kwin"
cmake -S kwin -B "$build_dir" -DKDE_INSTALL_PLUGINDIR="$(/usr/lib/qt6/bin/qtpaths6 --query QT_INSTALL_PLUGINS)"
cmake --build "$build_dir"
ctest --test-dir "$build_dir" --output-on-failure
sudo cmake --install "$build_dir"
```

Enable **Cursor for osu! Trail** in Plasma System Settings under Desktop Effects. If the effect does
not appear after installation, log out and back in. The app's trail switch controls drawing after
the effect is enabled. The theme also works while the effect is disabled.

The effect builds against KWin 6.6 and newer, including 6.8. It was tested on CachyOS with
Plasma 6 on Wayland, and on KWin 6.6.7 in a nested Wayland session. Build it against the
installed KWin version and rebuild it after a KWin update.

### Uninstalling

```sh
cursor-for-osu uninstall               # or: bash uninstall.sh
cursor-for-osu uninstall --keep-data   # keep the skin list and settings for a later install
```

This puts your previous cursor back, turns the trail extension off and removes the app,
the extension and the cursor themes it made. The skin files you added from are never touched.

On Plasma, run the uninstall command from the Plasma Wayland session. To remove the separately
installed module, disable **Cursor for osu! Trail** in Desktop Effects and remove the module.

```sh
sudo rm -- "$(qtpaths6 --query QT_INSTALL_PLUGINS)/kwin/effects/plugins/osu-cursor-trail.so"
# Arch, CachyOS, Manjaro:
sudo rm -- "$(/usr/lib/qt6/bin/qtpaths6 --query QT_INSTALL_PLUGINS)/kwin/effects/plugins/osu-cursor-trail.so"
```

### Languages

The app follows your desktop language. It is translated into English, Türkçe, Español,
Português (Brasil), Deutsch, Français, Русский, Polski, 日本語 and 简体中文.
To start it in another language: `LANGUAGE=de cursor-for-osu`.
The translations are in `osu_cursor/locale/`, one JSON file per language that maps the English text
to the translated one. `python3 -m pytest` checks that every text has a translation.

### Usage

Open **Cursor for osu!** from your applications and add a skin to the list with **Choose .osk** or **Choose folder** (for an unpacked skin folder), or drop `.osk` files and skin folders on the window. Click a skin in the list to apply it.

Skins you export from osu!lazer are added on their own, the app watches the game's exports folder while it is open and catches up on new exports when it starts. A skin you remove from the list doesn't come back unless you export it again. This can be turned off with the **Watch osu! exports** switch. The **+** button next to it adds every export at once, removed skins included. Right-click a skin to rename it or open its folder. Removing the skin in use goes back to your previous cursor.

From the command line:

```sh
cursor-for-osu apply skin.osk        # apply a skin
cursor-for-osu size 1.2              # cursor size, 0.1 to 2.0 like in the game
cursor-for-osu reset                 # go back to the previous cursor
cursor-for-osu status
cursor-for-osu uninstall
```

### How it works

- The cursor becomes an Xcursor theme generated from the skin, so the low-latency hardware cursor is used.
  Its size matches the game. It is set with the slider in the app, or read from osu!lazer if you haven't set it. The game's Screen Scaling setting is taken into account too.
- Every cursor shape shows the skin cursor. With **Keep system cursors** on, the text, resize, move, not-allowed and crosshair cursors come from the cursor theme you used before, coloured like the skin cursor: their dark parts take a dark shade of its colour and their light parts a light shade, so they stay visible on any background. The trail is not drawn behind them.
- Each added skin is kept in its own folder under `~/.local/share/osu-cursor/skins`. Only the cursor files (`cursor`, `cursormiddle`, `cursortrail`, with their `@2x` versions) and `skin.ini` are copied.
- The GNOME Shell extension in `extension/` and the KWin effect in `kwin/` draw the trail. Fade times, part spacing and blending come from osu!lazer's `CursorTrail` and `LegacyCursorTrail`.
- The trail turns off over fullscreen windows and while an application hides the cursor.

Growing the cursor on click (`CursorExpand`) is not supported, because a cursor theme can't react to clicks.
Spinning skins (`CursorRotate`) are shown still, because animated cursors on GNOME stall when switching skins and jump when the cursor shape changes.

### License

Cursor for osu! is released under the [MIT License](LICENSE). The trail behaviour is adapted from the MIT licensed [osu!](https://github.com/ppy/osu) code
(Copyright (c) ppy Pty Ltd), its notice is in [THIRD-PARTY-NOTICES](THIRD-PARTY-NOTICES). Skin images must not be added to this repository, they belong to their creators.

### Tests

```sh
python3 -m pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to work on the app.

## Türkçe

osu! skin'lerindeki imleci ve cursor trail'i oyun dışında GNOME ve KDE Plasma'da kullanır.

KDE Plasma desteği: [@MehmetAkifUgur](https://github.com/MehmetAkifUgur).

Cursor for osu! hayran yapımı bir araçtır. ppy veya osu! tarafından yapılmamıştır ve onlarla bağlantılı değildir.

### Gereksinimler

- Trail için GNOME Shell 51 (Wayland). İmlecin kendisi her GNOME'da çalışır, trail eklentisi sadece
  test edildiği GNOME Shell sürümü için işaretlidir.
- Plasma entegrasyonu için KDE Plasma 6.6 ve Wayland oturumu. Bkz. [Plasma kurulumu](#plasma-kurulumu).
- Python 3.10 veya üstü, Pillow, PyGObject ve libadwaita 1.5 veya üstü.

Paketleri dağıtımına göre kur:

| Dağıtım | Komut |
| --- | --- |
| Arch, CachyOS, Manjaro | `sudo pacman -S --needed python python-pillow python-gobject libadwaita` |
| Ubuntu, Debian | `sudo apt install python3 python3-pil python3-gi gir1.2-adw-1` |
| Fedora | `sudo dnf install python3 python3-pillow python3-gobject libadwaita` |
| openSUSE | `sudo zypper install python3 python3-Pillow python3-gobject typelib-1_0-Adw-1` |

`install.sh` bunları kontrol eder, eksik bir şey varsa senin dağıtımının komutunu gösterir.

### Kurulum

```sh
git clone https://github.com/egehankara/cursor-for-osu.git
cd cursor-for-osu
bash install.sh
```

GNOME'da ilk kurulumdan sonra bir kez oturumu kapatıp aç, GNOME yeni eklentileri sadece girişte tanıyor.
Sonra uygulamalardan **Cursor for osu!**'yu aç.

Güncellemek için yeni sürümü indirip tekrar kur:

```sh
cd cursor-for-osu
git pull
bash install.sh
```

### Plasma kurulumu

Yukarıdaki Python ve GTK bağımlılıklarıyla `bash install.sh` komutunu Plasma Wayland oturumunda çalıştır.
Tema değişiklikleri için `plasma-apply-cursortheme`, `kreadconfig6`, `kwriteconfig6`, `gdbus` ve `kscreen-doctor` kullanılır.
Ek paketleri kurmak ve KWin efektini derlemek için şu komutları çalıştır.

Kubuntu 26.04'te:

```sh
sudo apt install plasma-workspace libkscreen-bin kwin-dev extra-cmake-modules cmake g++ pkgconf libwayland-dev libdrm-dev
build_dir="${XDG_CACHE_HOME:-$HOME/.cache}/cursor-for-osu/kwin"
cmake -S kwin -B "$build_dir" -DKDE_INSTALL_PLUGINDIR="$(qtpaths6 --query QT_INSTALL_PLUGINS)"
cmake --build "$build_dir"
ctest --test-dir "$build_dir" --output-on-failure
sudo cmake --install "$build_dir"
```

Arch, CachyOS ve Manjaro'da (`qtpaths6` PATH'te olmadığı için):

```sh
sudo pacman -S --needed plasma-workspace libkscreen kwin extra-cmake-modules cmake base-devel
build_dir="${XDG_CACHE_HOME:-$HOME/.cache}/cursor-for-osu/kwin"
cmake -S kwin -B "$build_dir" -DKDE_INSTALL_PLUGINDIR="$(/usr/lib/qt6/bin/qtpaths6 --query QT_INSTALL_PLUGINS)"
cmake --build "$build_dir"
ctest --test-dir "$build_dir" --output-on-failure
sudo cmake --install "$build_dir"
```

Plasma Sistem Ayarları'nda Masaüstü Efektleri bölümünden **osu! İmleç İzi** efektini etkinleştir.
Kurulumdan sonra efekt listede görünmezse oturumu kapatıp yeniden aç. Efekt etkinleştirildikten sonra
izi uygulamanın trail anahtarından açıp kapatabilirsin. Efekt kapalıyken imleç teması kullanılabilir.

Efekt KWin 6.6 ve sonrasıyla, 6.8 dahil, derlenir. CachyOS'ta Plasma 6 Wayland oturumunda ve
KWin 6.6.7'de iç içe bir Wayland oturumunda test edildi. Efekti makinedeki KWin sürümüne karşı
derle ve KWin güncellendiğinde yeniden derle.

### Kaldırma

```sh
cursor-for-osu uninstall               # veya: bash uninstall.sh
cursor-for-osu uninstall --keep-data   # skin listesini ve ayarları sonraki kurulum için sakla
```

Önceki imlecini geri getirir, trail eklentisini kapatır, uygulamayı, eklentiyi ve oluşturduğu
imleç temalarını siler. Skin eklerken seçtiğin dosyalara hiçbir zaman dokunulmaz.

Plasma'da kaldırma komutunu Plasma Wayland oturumunda çalıştır. Ayrı kurulan KWin modülünü
kaldırmak için Masaüstü Efektleri'nden **osu! İmleç İzi** efektini kapat ve modülü sil.

```sh
sudo rm -- "$(qtpaths6 --query QT_INSTALL_PLUGINS)/kwin/effects/plugins/osu-cursor-trail.so"
# Arch, CachyOS, Manjaro:
sudo rm -- "$(/usr/lib/qt6/bin/qtpaths6 --query QT_INSTALL_PLUGINS)/kwin/effects/plugins/osu-cursor-trail.so"
```

### Diller

Uygulama masaüstünün dilini kullanır. English, Türkçe, Español, Português (Brasil), Deutsch,
Français, Русский, Polski, 日本語 ve 简体中文 dillerine çevrilmiştir.
Başka bir dilde açmak için: `LANGUAGE=de cursor-for-osu`.
Çeviriler `osu_cursor/locale/` altında, her dil için İngilizce metni çevirisiyle eşleyen bir JSON dosyasıdır.
`python3 -m pytest` her metnin çevrildiğini kontrol eder.

### Kullanım

Uygulamalardan **Cursor for osu!**'i aç, **.osk seç** veya **Klasör seç** ile ya da pencereye sürükleyerek `.osk` dosyalarını ve skin klasörlerini listeye ekle. Uygulamak için listeden bir skine tıkla.

osu!lazer'den export ettiğin skin'ler kendiliğinden eklenir: uygulama açıkken oyunun exports klasörünü izler, açılınca da kapalıyken yapılan export'ları ekler. Listeden kaldırdığın bir skin, tekrar export etmedikçe geri gelmez. Bunu **osu! export'larını izle** anahtarıyla kapatabilirsin. Yanındaki **+** butonu, kaldırdıkların dahil bütün export'ları bir kerede ekler. Bir skine sağ tıklayarak ismini değiştirebilir veya klasörünü açabilirsin. Kullandığın skini kaldırınca önceki imlecine dönersin.

Komut satırından:

```sh
cursor-for-osu apply skin.osk        # skin'i uygula
cursor-for-osu size 1.2              # cursor boyutu, oyundaki gibi 0.1 ile 2.0 arası
cursor-for-osu reset                 # önceki imlece dön
cursor-for-osu status
cursor-for-osu uninstall
```

### Nasıl çalışır

- İmleç, skin'den üretilen bir Xcursor teması olur, böylece gecikmesiz donanım imleci kullanılır.
  Boyutu oyundakiyle aynıdır. Uygulamadaki kaydırıcıdan ayarlanır, ayarlanmadıysa osu!lazer'den okunur. Oyundaki ekran ölçekleme (Screen Scaling) ayarı da hesaba katılır.
- Bütün imleç şekilleri skin imlecini gösterir. **Sistem imleçlerini koru** açıksa yazı, boyutlandırma, taşıma, yasak ve artı imleçleri önceden kullandığın imleç temasından alınır ve skin imlecinin rengine boyanır: koyu kısımları o rengin koyu tonunu, açık kısımları açık tonunu alır, böylece her arka planda görünürler. Bunların arkasında trail çizilmez.
- Eklenen her skin `~/.local/share/osu-cursor/skins` altında kendi klasöründe tutulur. Sadece imleç dosyaları (`cursor`, `cursormiddle`, `cursortrail`, `@2x` sürümleriyle) ve `skin.ini` kopyalanır.
- Trail'i `extension/` altındaki GNOME Shell eklentisi ve `kwin/` altındaki KWin efekti çizer. Solma süreleri, parça aralığı ve karışım modu osu!lazer'in `CursorTrail` ve `LegacyCursorTrail` kodundan alınmıştır.
- Tam ekran pencerelerde ve bir uygulama imleci gizlediğinde trail kapanır.

Tıklayınca imlecin büyümesi (`CursorExpand`) desteklenmiyor, çünkü imleç teması tıklamaya tepki veremez.
Dönen skinler (`CursorRotate`) sabit gösterilir, çünkü GNOME'da animasyonlu imleçler skin değişiminde takılıyor ve imleç şekli değişince açısı atlıyor.

### Lisans

Cursor for osu! [MIT Lisansı](LICENSE) ile yayınlanır. Trail davranışı MIT lisanslı [osu!](https://github.com/ppy/osu) kodundan uyarlanmıştır
(Copyright (c) ppy Pty Ltd), lisans notu [THIRD-PARTY-NOTICES](THIRD-PARTY-NOTICES) dosyasındadır. Skin görselleri bu repoya konmamalıdır, hakları yapımcılarına aittir.

### Test

```sh
python3 -m pytest
```

Uygulama üzerinde nasıl çalışılacağı [CONTRIBUTING.md](CONTRIBUTING.md#türkçe) dosyasında.
