# Contributing

[English](#english) · [Türkçe](#türkçe)

## English

### Setting up

```sh
git clone https://github.com/egehankara/cursor-for-osu.git
cd cursor-for-osu
bash install.sh            # installs the app and the trail extension for your user
python3 -m osu_cursor      # runs the app straight from the source folder
python3 -m pytest          # runs the tests
```

`install.sh` copies the code, so run it again after a change to try it from the app launcher.
GNOME Shell only loads a changed extension (`extension/`) after you log out and back in.

### Where things are

| Path | What it does |
| --- | --- |
| `osu_cursor/gui.py` | The window |
| `osu_cursor/gnome.py` | Skin list, settings, applying a skin on GNOME |
| `osu_cursor/skin.py` | Reading `.osk` files and skin folders |
| `osu_cursor/render.py` | Sizing the cursor like osu!lazer |
| `osu_cursor/system.py` | The kept system cursors, painted in the skin's colour |
| `osu_cursor/xcursor.py` | Reading and writing Xcursor files |
| `osu_cursor/i18n.py`, `osu_cursor/locale/` | Translations |
| `extension/` | GNOME Shell extension that draws the trail |
| `install.sh`, `uninstall.sh` | Install and uninstall |

### Text and translations

Every text the user sees is written in English in the code and wrapped in `_()`:

```python
from .i18n import _

self._toast(_("Skin removed"))
self._toast(_("Skins added: {added}").format(added=count))
```

Then add the same English text with its translation to every file in `osu_cursor/locale/`.
`python3 -m pytest` fails while a text is missing from a language, or when a translation has
different `{placeholders}`. If you can't translate a language, ask in the pull request or issue.

- Write numbers as "Skins added: {added}" rather than "{added} skins added", so that no
  language needs plural forms.
- In the shell scripts, use `say "Text"`, it goes through the same translations.

### Before you push

1. `python3 -m pytest` passes.
2. `git pull --rebase` so your commits go on top of the latest `master`.
3. One change per commit. The first line says what the commit does in English, in the
   imperative ("Add a trail opacity slider"), and the lines below say why.

Never commit skin images or `.osk` files, they belong to their creators.

## Türkçe

### Kurulum

```sh
git clone https://github.com/egehankara/cursor-for-osu.git
cd cursor-for-osu
bash install.sh            # uygulamayı ve trail eklentisini kendi kullanıcın için kurar
python3 -m osu_cursor      # uygulamayı doğrudan kaynak klasörden çalıştırır
python3 -m pytest          # testleri çalıştırır
```

`install.sh` kodu kopyalar, bu yüzden bir değişikliği uygulamalar menüsünden denemek için onu tekrar çalıştır.
GNOME Shell, değişen eklentiyi (`extension/`) ancak oturumu kapatıp açınca yükler.

### Neyin nerede olduğu

| Yol | Ne yapar |
| --- | --- |
| `osu_cursor/gui.py` | Pencere |
| `osu_cursor/gnome.py` | Skin listesi, ayarlar, skin'i GNOME'a uygulama |
| `osu_cursor/skin.py` | `.osk` dosyalarını ve skin klasörlerini okuma |
| `osu_cursor/render.py` | İmleci osu!lazer'deki gibi boyutlandırma |
| `osu_cursor/system.py` | Korunan sistem imleçleri, skinin rengine boyanmış |
| `osu_cursor/xcursor.py` | Xcursor dosyalarını okuma ve yazma |
| `osu_cursor/i18n.py`, `osu_cursor/locale/` | Çeviriler |
| `extension/` | Trail'i çizen GNOME Shell eklentisi |
| `install.sh`, `uninstall.sh` | Kurma ve kaldırma |

### Yazılar ve çeviriler

Kullanıcının gördüğü her yazı kodda İngilizce yazılır ve `_()` içine alınır:

```python
from .i18n import _

self._toast(_("Skin removed"))
self._toast(_("Skins added: {added}").format(added=count))
```

Sonra aynı İngilizce metni çevirisiyle birlikte `osu_cursor/locale/` altındaki her dosyaya ekle.
Bir dilde eksik yazı varsa ya da çevirideki `{yer tutucular}` farklıysa `python3 -m pytest` başarısız olur.
Bir dili çeviremiyorsan pull request'te veya issue'da sor.

- Sayıları "{added} skin eklendi" yerine "Eklenen skin: {added}" kalıbında yaz, böylece hiçbir dilde
  çoğul eki gerekmez.
- Kabuk betiklerinde `say "Metin"` kullan, o da aynı çevirilerden geçer.

### Push etmeden önce

1. `python3 -m pytest` geçiyor olsun.
2. `git pull --rebase` yap ki commit'lerin en güncel `master`'ın üstüne gelsin.
3. Her commit'te tek bir değişiklik olsun. İlk satır commit'in ne yaptığını İngilizce ve emir kipinde
   söylesin ("Add a trail opacity slider"), altındaki satırlar nedenini anlatsın.

Skin görsellerini veya `.osk` dosyalarını asla commit'leme, hakları yapımcılarına ait.
