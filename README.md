# osu-cursor

osu! skin'lerindeki imleci ve cursor trail'i oyunun dışında, GNOME'un her yerinde kullanır.
Şu an GNOME Shell 51 (Wayland) için çalışır.

## Kurulum

```sh
./install.sh
```

Kurulumdan sonra bir kez oturumu kapatıp aç, GNOME yeni eklentileri sadece girişte tanıyor.
Gerekli paketler: `python-pillow`, `python-gobject`, `libadwaita`.

## Kullanım

Uygulamalardan **osu! Cursor**'u aç ve `.osk` dosyasını pencereye sürükle. Komut satırından:

```sh
osu-cursor apply skin.osk        # skin'i uygula
osu-cursor size 1.2              # cursor boyutu, oyundaki gibi 0.1 ile 2.0 arası
osu-cursor reset                 # önceki imlece dön
osu-cursor status
```

## Nasıl çalışır

- İmleç, skin'den üretilen bir Xcursor teması olur, böylece gecikmesiz donanım imleci kullanılır.
  Boyut ve dönme hızı oyundaki değerlerle aynıdır. Boyut uygulamadaki kaydırıcıdan ayarlanır, ayarlanmadıysa osu!lazer'den okunur. Oyundaki ekran ölçekleme (Screen Scaling) ayarı da hesaba katılır.
- Trail'i `extension/` altındaki GNOME Shell eklentisi çizer. Solma süreleri, parça aralığı ve
  karışım modu osu!lazer'in `CursorTrail` ve `LegacyCursorTrail` kodundan alınmıştır.
- Tam ekran pencerelerde ve bir uygulama imleci gizlediğinde trail kapanır.

Tıklayınca imlecin büyümesi (`CursorExpand`) desteklenmiyor, çünkü imleç teması tıklamaya tepki veremez.

## Lisans notu

Trail davranışı MIT lisanslı [osu!](https://github.com/ppy/osu) kodundan uyarlanmıştır
(Copyright (c) ppy Pty Ltd). Skin görselleri bu repoya konmamalıdır, hakları yapımcılarına aittir.

## Test

```sh
python3 -m pytest
```
