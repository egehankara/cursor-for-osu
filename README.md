# Cursor for osu!

osu! skin'lerindeki imleci ve cursor trail'i oyunun dışında, GNOME'un her yerinde kullanır.
Şu an GNOME Shell 51 (Wayland) için çalışır.

## Kurulum

```sh
./install.sh
```

Kurulumdan sonra bir kez oturumu kapatıp aç, GNOME yeni eklentileri sadece girişte tanıyor.
Gerekli paketler: `python-pillow`, `python-gobject`, `libadwaita`.

## Kullanım

Uygulamalardan **Cursor for osu!**'i aç, **Dosya seç** veya **Klasör seç** ile ya da pencereye sürükleyerek `.osk` dosyasını veya skin klasörünü listeye ekle, sonra listeden tıklayıp uygula. **Export skin'lerini ekle** butonu osu!lazer'in exports klasöründeki skin'leri toplu ekler. Bir skine sağ tıklayarak ismini değiştirebilir veya klasörünü açabilirsin. Komut satırından:

```sh
cursor-for-osu apply skin.osk        # skin'i uygula
cursor-for-osu size 1.2              # cursor boyutu, oyundaki gibi 0.1 ile 2.0 arası
cursor-for-osu reset                 # önceki imlece dön
cursor-for-osu status
```

## Nasıl çalışır

- İmleç, skin'den üretilen bir Xcursor teması olur, böylece gecikmesiz donanım imleci kullanılır.
  Boyut oyundaki değerle aynıdır. Boyut uygulamadaki kaydırıcıdan ayarlanır, ayarlanmadıysa osu!lazer'den okunur. Oyundaki ekran ölçekleme (Screen Scaling) ayarı da hesaba katılır.
- Eklenen her skin `~/.local/share/osu-cursor/skins` altında kendi klasöründe tutulur. Sadece imleç
  dosyaları (`cursor`, `cursormiddle`, `cursortrail`, `@2x` sürümleriyle) ve `skin.ini` kopyalanır.
- Trail'i `extension/` altındaki GNOME Shell eklentisi çizer. Solma süreleri, parça aralığı ve
  karışım modu osu!lazer'in `CursorTrail` ve `LegacyCursorTrail` kodundan alınmıştır.
- Tam ekran pencerelerde ve bir uygulama imleci gizlediğinde trail kapanır.

Tıklayınca imlecin büyümesi (`CursorExpand`) desteklenmiyor, çünkü imleç teması tıklamaya tepki veremez.
Dönen skinler (`CursorRotate`) de sabit gösterilir, çünkü GNOME'da animasyonlu imleçler skin değişiminde takılıyor ve imleç şekli değişince açısı atlıyor.

## Lisans notu

Trail davranışı MIT lisanslı [osu!](https://github.com/ppy/osu) kodundan uyarlanmıştır
(Copyright (c) ppy Pty Ltd). Skin görselleri bu repoya konmamalıdır, hakları yapımcılarına aittir.

## Test

```sh
python3 -m pytest
```
