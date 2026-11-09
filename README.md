# Cursor for osu!

[English](#english) · [Türkçe](#türkçe)

## English

Use the cursor and cursor trail of your osu! skins everywhere on GNOME, outside the game.
Currently works on GNOME Shell 51 (Wayland).

### Installation

```sh
bash install.sh
```

Log out and back in once after the first install, because GNOME only finds new extensions at login.
Required packages: `python-pillow`, `python-gobject`, `libadwaita`.

### Usage

Open **Cursor for osu!** from your applications and add a skin to the list with **Dosya seç** (choose a file) or **Klasör seç** (choose a folder), or drop `.osk` files and skin folders on the window. Click a skin in the list to apply it.

**Export skin'lerini ekle** adds everything in osu!lazer's exports folder at once. Right-click a skin to rename it or open its folder. Removing the skin in use goes back to your previous cursor.

From the command line:

```sh
cursor-for-osu apply skin.osk        # apply a skin
cursor-for-osu size 1.2              # cursor size, 0.1 to 2.0 like in the game
cursor-for-osu reset                 # go back to the previous cursor
cursor-for-osu status
```

### How it works

- The cursor becomes an Xcursor theme generated from the skin, so the low-latency hardware cursor is used.
  Its size matches the game. It is set with the slider in the app, or read from osu!lazer if you haven't set it. The game's Screen Scaling setting is taken into account too.
- Each added skin is kept in its own folder under `~/.local/share/osu-cursor/skins`. Only the cursor files (`cursor`, `cursormiddle`, `cursortrail`, with their `@2x` versions) and `skin.ini` are copied.
- The trail is drawn by the GNOME Shell extension in `extension/`. Fade times, part spacing and blending come from osu!lazer's `CursorTrail` and `LegacyCursorTrail`.
- The trail turns off over fullscreen windows and while an application hides the cursor.

Growing the cursor on click (`CursorExpand`) is not supported, because a cursor theme can't react to clicks.
Spinning skins (`CursorRotate`) are shown still, because animated cursors on GNOME stall when switching skins and jump when the cursor shape changes.

### License note

The trail behaviour is adapted from the MIT licensed [osu!](https://github.com/ppy/osu) code
(Copyright (c) ppy Pty Ltd). Skin images must not be added to this repository, they belong to their creators.

### Tests

```sh
python3 -m pytest
```

## Türkçe

osu! skin'lerindeki imleci ve cursor trail'i oyunun dışında, GNOME'un her yerinde kullanır.
Şu an GNOME Shell 51 (Wayland) için çalışır.

### Kurulum

```sh
bash install.sh
```

İlk kurulumdan sonra bir kez oturumu kapatıp aç, GNOME yeni eklentileri sadece girişte tanıyor.
Gerekli paketler: `python-pillow`, `python-gobject`, `libadwaita`.

### Kullanım

Uygulamalardan **Cursor for osu!**'i aç, **Dosya seç** veya **Klasör seç** ile ya da pencereye sürükleyerek `.osk` dosyalarını ve skin klasörlerini listeye ekle. Uygulamak için listeden bir skine tıkla.

**Export skin'lerini ekle** butonu osu!lazer'in exports klasöründeki skin'leri toplu ekler. Bir skine sağ tıklayarak ismini değiştirebilir veya klasörünü açabilirsin. Kullandığın skini kaldırınca önceki imlecine dönersin.

Komut satırından:

```sh
cursor-for-osu apply skin.osk        # skin'i uygula
cursor-for-osu size 1.2              # cursor boyutu, oyundaki gibi 0.1 ile 2.0 arası
cursor-for-osu reset                 # önceki imlece dön
cursor-for-osu status
```

### Nasıl çalışır

- İmleç, skin'den üretilen bir Xcursor teması olur, böylece gecikmesiz donanım imleci kullanılır.
  Boyutu oyundakiyle aynıdır. Uygulamadaki kaydırıcıdan ayarlanır, ayarlanmadıysa osu!lazer'den okunur. Oyundaki ekran ölçekleme (Screen Scaling) ayarı da hesaba katılır.
- Eklenen her skin `~/.local/share/osu-cursor/skins` altında kendi klasöründe tutulur. Sadece imleç dosyaları (`cursor`, `cursormiddle`, `cursortrail`, `@2x` sürümleriyle) ve `skin.ini` kopyalanır.
- Trail'i `extension/` altındaki GNOME Shell eklentisi çizer. Solma süreleri, parça aralığı ve karışım modu osu!lazer'in `CursorTrail` ve `LegacyCursorTrail` kodundan alınmıştır.
- Tam ekran pencerelerde ve bir uygulama imleci gizlediğinde trail kapanır.

Tıklayınca imlecin büyümesi (`CursorExpand`) desteklenmiyor, çünkü imleç teması tıklamaya tepki veremez.
Dönen skinler (`CursorRotate`) sabit gösterilir, çünkü GNOME'da animasyonlu imleçler skin değişiminde takılıyor ve imleç şekli değişince açısı atlıyor.

### Lisans notu

Trail davranışı MIT lisanslı [osu!](https://github.com/ppy/osu) kodundan uyarlanmıştır
(Copyright (c) ppy Pty Ltd). Skin görselleri bu repoya konmamalıdır, hakları yapımcılarına aittir.

### Test

```sh
python3 -m pytest
```
