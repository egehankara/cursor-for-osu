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
Run `bash install.sh` again to update.

### Uninstalling

```sh
cursor-for-osu uninstall               # or: bash uninstall.sh
cursor-for-osu uninstall --keep-data   # keep the skin list and settings for a later install
```

This puts your previous cursor back, turns the trail extension off and removes the app,
the extension and the cursor themes it made. The skin files you added from are never touched.

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
- The trail is drawn by the GNOME Shell extension in `extension/`. Fade times, part spacing and blending come from osu!lazer's `CursorTrail` and `LegacyCursorTrail`.
- The trail turns off over fullscreen windows and while an application hides the cursor.

Growing the cursor on click (`CursorExpand`) is not supported, because a cursor theme can't react to clicks.
Spinning skins (`CursorRotate`) are shown still, because animated cursors on GNOME stall when switching skins and jump when the cursor shape changes.

### License

Cursor for osu! is released under the [MIT License](LICENSE). The trail behaviour is adapted from the MIT licensed [osu!](https://github.com/ppy/osu) code
(Copyright (c) ppy Pty Ltd). Skin images must not be added to this repository, they belong to their creators.

### Tests

```sh
python3 -m pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to work on the app.

## Türkçe

osu! skin'lerindeki imleci ve cursor trail'i oyunun dışında, GNOME'un her yerinde kullanır.
Şu an GNOME Shell 51 (Wayland) için çalışır.

### Kurulum

```sh
bash install.sh
```

İlk kurulumdan sonra bir kez oturumu kapatıp aç, GNOME yeni eklentileri sadece girişte tanıyor.
Gerekli paketler: `python-pillow`, `python-gobject`, `libadwaita`.
Güncellemek için `bash install.sh`'ı tekrar çalıştır.

### Kaldırma

```sh
cursor-for-osu uninstall               # veya: bash uninstall.sh
cursor-for-osu uninstall --keep-data   # skin listesini ve ayarları sonraki kurulum için sakla
```

Önceki imlecini geri getirir, trail eklentisini kapatır, uygulamayı, eklentiyi ve oluşturduğu
imleç temalarını siler. Skin eklerken seçtiğin dosyalara hiçbir zaman dokunulmaz.

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
- Trail'i `extension/` altındaki GNOME Shell eklentisi çizer. Solma süreleri, parça aralığı ve karışım modu osu!lazer'in `CursorTrail` ve `LegacyCursorTrail` kodundan alınmıştır.
- Tam ekran pencerelerde ve bir uygulama imleci gizlediğinde trail kapanır.

Tıklayınca imlecin büyümesi (`CursorExpand`) desteklenmiyor, çünkü imleç teması tıklamaya tepki veremez.
Dönen skinler (`CursorRotate`) sabit gösterilir, çünkü GNOME'da animasyonlu imleçler skin değişiminde takılıyor ve imleç şekli değişince açısı atlıyor.

### Lisans

Cursor for osu! [MIT Lisansı](LICENSE) ile yayınlanır. Trail davranışı MIT lisanslı [osu!](https://github.com/ppy/osu) kodundan uyarlanmıştır
(Copyright (c) ppy Pty Ltd). Skin görselleri bu repoya konmamalıdır, hakları yapımcılarına aittir.

### Test

```sh
python3 -m pytest
```

Uygulama üzerinde nasıl çalışılacağı [CONTRIBUTING.md](CONTRIBUTING.md#türkçe) dosyasında.
