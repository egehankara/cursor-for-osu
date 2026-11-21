<div align="center">

<img src="data/icons/hicolor/scalable/apps/io.github.egehankara.CursorForOsu.svg" width="112" alt="Cursor for osu! icon">

# Cursor for osu!

**Your osu! skin's cursor and cursor trail, on your whole Linux desktop.**

GNOME and KDE Plasma · Wayland · 10 languages

[English](#english) · [Türkçe](#türkçe)

</div>

---

## English

<p align="center">
  <img src="data/screenshots/window-en.png" width="440" alt="The Cursor for osu! window with a list of skins">
</p>

Drop in an `.osk` file and your desktop gets the skin's **cursor** and its **trail**, sized
and faded like in osu!lazer. Skins you export from osu!lazer show up in the app by themselves.

> [!IMPORTANT]
> **Linux only.** You need **GNOME** or **KDE Plasma 6.6+**, both on **Wayland**.
> Not sure which desktop you have? Run `echo $XDG_CURRENT_DESKTOP` in a terminal. It prints `GNOME` or `KDE`.

KDE Plasma support by [@MehmetAkifUgur](https://github.com/MehmetAkifUgur).
Cursor for osu! is a fan-made tool. It is **not made by or affiliated with ppy or osu!**.

**Contents:** [Install on GNOME](#install-on-gnome) · [Install on KDE Plasma](#install-on-kde-plasma) ·
[Usage](#usage) · [Updating](#updating) · [Uninstalling](#uninstalling) · [How it works](#how-it-works)

### New to the terminal?

The install takes a few commands in a terminal. Open it from your applications: **Terminal** or
**Console** on GNOME, **Konsole** on KDE Plasma.

- Copy a command, paste it with **Ctrl+Shift+V** and press **Enter**.
- Commands that start with `sudo` ask for your password. **Nothing appears while you type it**, that is normal.

### Install on GNOME

The trail is made for **GNOME Shell 51**. The cursor works on any GNOME.

**1. Install the packages.** Pick your distribution:

```sh
# Arch, CachyOS, Manjaro
sudo pacman -S --needed git python python-pillow python-gobject libadwaita
```

<details>
<summary>Ubuntu, Debian · Fedora · openSUSE</summary>

```sh
# Ubuntu, Debian
sudo apt install git python3 python3-pil python3-gi gir1.2-adw-1
```

```sh
# Fedora
sudo dnf install git python3 python3-pillow python3-gobject libadwaita
```

```sh
# openSUSE
sudo zypper install git python3 python3-Pillow python3-gobject typelib-1_0-Adw-1
```

</details>

**2. Download and install the app:**

```sh
git clone https://github.com/egehankara/cursor-for-osu.git
cd cursor-for-osu
bash install.sh
```

**3. Log out and log back in once**, so GNOME loads the trail.

**4. Open Cursor for osu!** from your applications and pick a skin. Done!

### Install on KDE Plasma

On Plasma the trail is a small KWin effect that **you build on your computer** in step 3.
It takes a minute.

**1. Install the packages.** Pick your distribution:

```sh
# Arch, CachyOS, Manjaro
sudo pacman -S --needed git python python-pillow python-gobject libadwaita plasma-workspace libkscreen kwin extra-cmake-modules cmake base-devel vulkan-headers
```

<details>
<summary>Kubuntu</summary>

```sh
sudo apt install git python3 python3-pil python3-gi gir1.2-adw-1 plasma-workspace libkscreen-bin kwin-dev extra-cmake-modules cmake g++ pkgconf libwayland-dev libdrm-dev
```

</details>

**2. Download and install the app:**

```sh
git clone https://github.com/egehankara/cursor-for-osu.git
cd cursor-for-osu
bash install.sh
```

**3. Build and install the trail**, in the same terminal:

```sh
# Arch, CachyOS, Manjaro
cmake -S kwin -B build -DKDE_INSTALL_PLUGINDIR="$(/usr/lib/qt6/bin/qtpaths6 --query QT_INSTALL_PLUGINS)"
cmake --build build
sudo cmake --install build
```

<details>
<summary>Kubuntu</summary>

```sh
cmake -S kwin -B build -DKDE_INSTALL_PLUGINDIR="$(qtpaths6 --query QT_INSTALL_PLUGINS)"
cmake --build build
sudo cmake --install build
```

</details>

**4. Log out and log back in once.**

**5. Turn the trail on:** open **System Settings → Desktop Effects** and enable **Cursor for osu! Trail**.

**6. Open Cursor for osu!** from your applications and pick a skin. Done!

> [!NOTE]
> The cursor works even with the trail turned off. The trail was tested on CachyOS with Plasma 6
> and builds with KWin 6.6 up to 6.8.

### Usage

- **Add skins** with the **.osk** and **Folder** buttons, or **drag `.osk` files and skin folders onto the window**.
- **Click a card to apply the skin.** The one in use has a pink frame.
- **Change the size** with the slider, or click the number next to it and type one.
- **Right-click a card** to rename the skin, open its folder or remove it. Removing the skin in use puts your previous cursor back.

**osu!lazer exports are added automatically.** While the app is open it watches the game's
exports folder, and when it starts it catches up on exports made while it was closed. A skin
you remove stays removed until you export it again.

Under **More settings** (the gear button at the top) you can:

- turn this off with **Watch osu! exports**,
- add every export at once with **Add all**, removed skins included,
- pick where osu!lazer keeps its files with **Change** next to **osu!lazer folder**.

<details>
<summary>Command line</summary>

```sh
cursor-for-osu apply skin.osk        # apply a skin
cursor-for-osu size 1.2              # cursor size, 0.1 to 2.0 like in the game
cursor-for-osu reset                 # go back to the previous cursor
cursor-for-osu status
cursor-for-osu uninstall
```

</details>

### Updating

**The app tells you when a new version is out.** It asks GitHub once a day, and if there is
one, a bar appears at the top of the window. **How to update** shows these commands with your
folder filled in:

```sh
cd cursor-for-osu
git pull
bash install.sh
```

> [!IMPORTANT]
> **On KDE Plasma**, also run the three commands of step 3 again and log out and back in.
> **Do this after every Plasma update too**, or the trail stops loading.

Don't want the reminders? Pick **Not now**, then **No**. You can turn them back on in the About window.

### Uninstalling

```sh
cursor-for-osu uninstall               # or: bash uninstall.sh
cursor-for-osu uninstall --keep-data   # keep the skin list and settings for a later install
```

This **puts your previous cursor back**, turns the trail off and removes the app, the extension
and the cursor themes it made. **The skin files you added from are never touched.**

<details>
<summary>Removing the KWin trail on Plasma</summary>

Run the uninstall command from the Plasma Wayland session. Then disable **Cursor for osu! Trail**
in Desktop Effects and remove the module:

```sh
# Arch, CachyOS, Manjaro
sudo rm -- "$(/usr/lib/qt6/bin/qtpaths6 --query QT_INSTALL_PLUGINS)/kwin/effects/plugins/osu-cursor-trail.so"
# Kubuntu
sudo rm -- "$(qtpaths6 --query QT_INSTALL_PLUGINS)/kwin/effects/plugins/osu-cursor-trail.so"
```

</details>

### Languages

The app follows your desktop language: **English, Türkçe, Español, Português (Brasil), Deutsch,
Français, Русский, Polski, 日本語 and 简体中文**. To start it in another one:
`LANGUAGE=de cursor-for-osu`.

Translations live in `osu_cursor/locale/`, one JSON file per language that maps the English text
to the translated one. `python3 -m pytest` checks that every text has a translation.

### How it works

- **The cursor is a real cursor theme**, an Xcursor theme generated from the skin, so you get the
  low-latency hardware cursor. Its size matches the game: it comes from the slider in the app, or
  from osu!lazer if you haven't set it, and the game's Screen Scaling is taken into account.
- **The trail is drawn by the desktop**: the GNOME Shell extension in `extension/` or the KWin
  effect in `kwin/`. Fade times, part spacing and blending come from osu!lazer's `CursorTrail`
  and `LegacyCursorTrail`. The trail turns off over fullscreen windows and while an app hides the cursor.
- **Every cursor shape shows the skin cursor.** With **Keep system cursors** on, the text, resize,
  move, not-allowed and crosshair cursors come from your previous cursor theme, tinted with the skin
  cursor's colours so they stay visible on any background. The trail is not drawn behind them.
- Each skin is kept in its own folder under `~/.local/share/osu-cursor/skins`. Only the cursor
  files (`cursor`, `cursormiddle`, `cursortrail`, with their `@2x` versions) and `skin.ini` are copied.

**Not supported:** growing the cursor on click (`CursorExpand`), because a cursor theme can't react
to clicks. Spinning skins (`CursorRotate`) are shown still, because animated cursors on GNOME stall
when switching skins and jump when the cursor shape changes.

### Contributing and tests

```sh
python3 -m pytest
ctest --test-dir build --output-on-failure   # KWin trail, after building it
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to work on the app.

### License

[MIT License](LICENSE). The trail behaviour is adapted from the MIT licensed
[osu!](https://github.com/ppy/osu) code (Copyright (c) ppy Pty Ltd), its notice is in
[THIRD-PARTY-NOTICES](THIRD-PARTY-NOTICES). **Skin images must not be added to this repository**,
they belong to their creators.

---

## Türkçe

<p align="center">
  <img src="data/screenshots/window-tr.png" width="440" alt="Skin listesiyle Cursor for osu! penceresi">
</p>

Bir `.osk` dosyası ekle, masaüstün skin'in **imlecini** ve **trail'ini** osu!lazer'deki boyut ve
solmayla kullansın. osu!lazer'dan export ettiğin skin'ler uygulamaya kendiliğinden gelir.

> [!IMPORTANT]
> **Sadece Linux.** **GNOME** veya **KDE Plasma 6.6+** gerekir, ikisi de **Wayland** oturumunda.
> Hangi masaüstünü kullandığından emin değil misin? Terminalde `echo $XDG_CURRENT_DESKTOP` çalıştır. `GNOME` veya `KDE` yazar.

KDE Plasma desteği: [@MehmetAkifUgur](https://github.com/MehmetAkifUgur).
Cursor for osu! hayran yapımı bir araçtır. **ppy veya osu! tarafından yapılmamıştır ve onlarla bağlantılı değildir.**

**İçindekiler:** [GNOME'da kurulum](#gnomeda-kurulum) · [KDE Plasma'da kurulum](#kde-plasmada-kurulum) ·
[Kullanım](#kullanım) · [Güncelleme](#güncelleme) · [Kaldırma](#kaldırma) · [Nasıl çalışır](#nasıl-çalışır)

### Terminale yeni misin?

Kurulum, terminalde birkaç komuttan oluşur. Terminali uygulamalarından aç: GNOME'da **Terminal**
veya **Konsol**, KDE Plasma'da **Konsole**.

- Bir komutu kopyala, **Ctrl+Shift+V** ile yapıştır ve **Enter**'a bas.
- `sudo` ile başlayan komutlar şifreni sorar. **Şifreni yazarken ekranda hiçbir şey görünmez**, bu normal.

### GNOME'da kurulum

Trail **GNOME Shell 51** için yapıldı. İmleç her GNOME'da çalışır.

**1. Paketleri kur.** Dağıtımını seç:

```sh
# Arch, CachyOS, Manjaro
sudo pacman -S --needed git python python-pillow python-gobject libadwaita
```

<details>
<summary>Ubuntu, Debian · Fedora · openSUSE</summary>

```sh
# Ubuntu, Debian
sudo apt install git python3 python3-pil python3-gi gir1.2-adw-1
```

```sh
# Fedora
sudo dnf install git python3 python3-pillow python3-gobject libadwaita
```

```sh
# openSUSE
sudo zypper install git python3 python3-Pillow python3-gobject typelib-1_0-Adw-1
```

</details>

**2. Uygulamayı indir ve kur:**

```sh
git clone https://github.com/egehankara/cursor-for-osu.git
cd cursor-for-osu
bash install.sh
```

**3. Bir kez oturumu kapatıp tekrar aç**, GNOME trail'i böyle yükler.

**4. Uygulamalarından Cursor for osu!'yu aç** ve bir skin seç. Bu kadar!

### KDE Plasma'da kurulum

Plasma'da trail küçük bir KWin efektidir ve 3. adımda **onu kendi bilgisayarında derlersin**.
Bir dakika sürer.

**1. Paketleri kur.** Dağıtımını seç:

```sh
# Arch, CachyOS, Manjaro
sudo pacman -S --needed git python python-pillow python-gobject libadwaita plasma-workspace libkscreen kwin extra-cmake-modules cmake base-devel vulkan-headers
```

<details>
<summary>Kubuntu</summary>

```sh
sudo apt install git python3 python3-pil python3-gi gir1.2-adw-1 plasma-workspace libkscreen-bin kwin-dev extra-cmake-modules cmake g++ pkgconf libwayland-dev libdrm-dev
```

</details>

**2. Uygulamayı indir ve kur:**

```sh
git clone https://github.com/egehankara/cursor-for-osu.git
cd cursor-for-osu
bash install.sh
```

**3. Aynı terminalde trail'i derle ve kur:**

```sh
# Arch, CachyOS, Manjaro
cmake -S kwin -B build -DKDE_INSTALL_PLUGINDIR="$(/usr/lib/qt6/bin/qtpaths6 --query QT_INSTALL_PLUGINS)"
cmake --build build
sudo cmake --install build
```

<details>
<summary>Kubuntu</summary>

```sh
cmake -S kwin -B build -DKDE_INSTALL_PLUGINDIR="$(qtpaths6 --query QT_INSTALL_PLUGINS)"
cmake --build build
sudo cmake --install build
```

</details>

**4. Bir kez oturumu kapatıp tekrar aç.**

**5. Trail'i aç:** **Sistem Ayarları → Masaüstü Efektleri**'ne gir ve **osu! İmleç İzi**'ni etkinleştir.

**6. Uygulamalarından Cursor for osu!'yu aç** ve bir skin seç. Bu kadar!

> [!NOTE]
> Trail kapalıyken de imleç çalışır. Trail CachyOS'ta Plasma 6 ile test edildi ve KWin 6.6'dan
> 6.8'e kadar derlenir.

### Kullanım

- **Skin eklemek için** **.osk** ve **Klasör** düğmelerini kullan ya da **`.osk` dosyalarını ve skin klasörlerini pencereye sürükle**.
- **Uygulamak için bir karta tıkla.** Kullandığın skin pembe çerçeveli olur.
- **Boyutu** kaydırıcıyla ayarla ya da yanındaki sayıya tıklayıp yaz.
- **Bir karta sağ tıklayarak** skin'in adını değiştir, klasörünü aç veya onu kaldır. Kullandığın skin'i kaldırınca önceki imlecine dönersin.

**osu!lazer export'ları kendiliğinden eklenir.** Uygulama açıkken oyunun exports klasörünü
izler, açılınca da kapalıyken yapılan export'ları ekler. Listeden kaldırdığın bir skin, tekrar
export etmedikçe geri gelmez.

Üstteki ⚙ düğmesiyle açılan **Diğer ayarlar** altında:

- **osu! export'larını izle** ile bunu kapatabilir,
- **Tümünü ekle** ile kaldırdıkların dahil bütün export'ları bir kerede ekleyebilir,
- **osu!lazer klasörü** satırındaki **Değiştir** ile oyunun dosyalarının yerini seçebilirsin.

<details>
<summary>Komut satırı</summary>

```sh
cursor-for-osu apply skin.osk        # skin'i uygula
cursor-for-osu size 1.2              # imleç boyutu, oyundaki gibi 0.1 ile 2.0 arası
cursor-for-osu reset                 # önceki imlece dön
cursor-for-osu status
cursor-for-osu uninstall
```

</details>

### Güncelleme

**Yeni sürüm çıkınca uygulama haber verir.** Günde bir kez GitHub'a sorar, yeni sürüm varsa
pencerenin üstünde bir şerit belirir. **Nasıl güncellenir?** düğmesi bu komutları senin
klasörünle birlikte gösterir:

```sh
cd cursor-for-osu
git pull
bash install.sh
```

> [!IMPORTANT]
> **KDE Plasma'da** 3. adımdaki üç komutu da tekrar çalıştır ve bir kez oturumu kapatıp aç.
> **Her Plasma güncellemesinden sonra da bunu yap**, yoksa trail yüklenmez.

Hatırlatma istemiyor musun? **Şimdi değil**, sonra **Hayır** de. Hakkında penceresinden tekrar açabilirsin.

### Kaldırma

```sh
cursor-for-osu uninstall               # veya: bash uninstall.sh
cursor-for-osu uninstall --keep-data   # skin listesini ve ayarları sonraki kurulum için sakla
```

**Önceki imlecini geri getirir**, trail'i kapatır, uygulamayı, eklentiyi ve oluşturduğu imleç
temalarını siler. **Skin eklerken seçtiğin dosyalara hiçbir zaman dokunulmaz.**

<details>
<summary>Plasma'da KWin trail'ini kaldırma</summary>

Kaldırma komutunu Plasma Wayland oturumunda çalıştır. Sonra Masaüstü Efektleri'nden
**osu! İmleç İzi**'ni kapat ve modülü sil:

```sh
# Arch, CachyOS, Manjaro
sudo rm -- "$(/usr/lib/qt6/bin/qtpaths6 --query QT_INSTALL_PLUGINS)/kwin/effects/plugins/osu-cursor-trail.so"
# Kubuntu
sudo rm -- "$(qtpaths6 --query QT_INSTALL_PLUGINS)/kwin/effects/plugins/osu-cursor-trail.so"
```

</details>

### Diller

Uygulama masaüstünün dilini kullanır: **English, Türkçe, Español, Português (Brasil), Deutsch,
Français, Русский, Polski, 日本語 ve 简体中文**. Başka bir dilde açmak için:
`LANGUAGE=de cursor-for-osu`.

Çeviriler `osu_cursor/locale/` altında, her dil için İngilizce metni çevirisiyle eşleyen bir JSON
dosyasıdır. `python3 -m pytest` her metnin çevrildiğini kontrol eder.

### Nasıl çalışır

- **İmleç gerçek bir imleç temasıdır**, skin'den üretilen bir Xcursor teması, böylece gecikmesiz
  donanım imleci kullanılır. Boyutu oyundakiyle aynıdır: uygulamadaki kaydırıcıdan, ayarlanmadıysa
  osu!lazer'den gelir. Oyundaki ekran ölçekleme (Screen Scaling) ayarı da hesaba katılır.
- **Trail'i masaüstü çizer**: `extension/` altındaki GNOME Shell eklentisi ya da `kwin/` altındaki
  KWin efekti. Solma süreleri, parça aralığı ve karışım modu osu!lazer'in `CursorTrail` ve
  `LegacyCursorTrail` kodundan alınmıştır. Tam ekran pencerelerde ve bir uygulama imleci gizlediğinde trail kapanır.
- **Bütün imleç şekilleri skin imlecini gösterir.** **Sistem imleçlerini koru** açıksa yazı,
  boyutlandırma, taşıma, yasak ve artı imleçleri önceki imleç temandan alınır ve skin imlecinin
  renklerine boyanır, böylece her arka planda görünürler. Bunların arkasında trail çizilmez.
- Eklenen her skin `~/.local/share/osu-cursor/skins` altında kendi klasöründe tutulur. Sadece imleç
  dosyaları (`cursor`, `cursormiddle`, `cursortrail`, `@2x` sürümleriyle) ve `skin.ini` kopyalanır.

**Desteklenmeyenler:** tıklayınca imlecin büyümesi (`CursorExpand`), çünkü imleç teması tıklamaya
tepki veremez. Dönen skin'ler (`CursorRotate`) sabit gösterilir, çünkü GNOME'da animasyonlu
imleçler skin değişiminde takılıyor ve imleç şekli değişince açısı atlıyor.

### Katkı ve testler

```sh
python3 -m pytest
ctest --test-dir build --output-on-failure   # KWin trail'i, derledikten sonra
```

Uygulama üzerinde nasıl çalışılacağı [CONTRIBUTING.md](CONTRIBUTING.md#türkçe) dosyasında.

### Lisans

[MIT Lisansı](LICENSE). Trail davranışı MIT lisanslı [osu!](https://github.com/ppy/osu) kodundan
uyarlanmıştır (Copyright (c) ppy Pty Ltd), lisans notu [THIRD-PARTY-NOTICES](THIRD-PARTY-NOTICES)
dosyasındadır. **Skin görselleri bu repoya konmamalıdır**, hakları yapımcılarına aittir.
