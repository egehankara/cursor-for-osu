"""Command line entry point. Without arguments it opens the window."""

from __future__ import annotations

import argparse
import sys

from . import gnome
from .skin import SkinError


def _report(result: gnome.Result) -> None:
    print(f"Uygulandı: {result.skin_name} ({result.size_px} px)")
    problem = gnome.trail_problem()
    if problem:
        print(problem)


def main() -> int:
    parser = argparse.ArgumentParser(prog="osu-cursor")
    commands = parser.add_subparsers(dest="command")
    apply_parser = commands.add_parser("apply", help="bir .osk dosyasını uygula")
    apply_parser.add_argument("skin", help=".osk dosyası veya skin klasörü")
    apply_parser.add_argument(
        "--size",
        type=float,
        help="cursor boyutu, 0.1 ile 2.0 arası (varsayılan: son ayar veya osu!lazer ayarın)",
    )
    size_parser = commands.add_parser("size", help="cursor boyutunu değiştir")
    size_parser.add_argument("value", type=float, help="0.1 ile 2.0 arası, oyundaki gibi")
    commands.add_parser("reset", help="önceki imlece dön")
    commands.add_parser("status", help="uygulanan skin'i göster")
    arguments = parser.parse_args()

    if arguments.command is None:
        from .gui import run

        return run()

    try:
        if arguments.command == "apply":
            _report(gnome.apply_skin(arguments.skin, arguments.size))
        elif arguments.command == "size":
            result = gnome.set_cursor_size(arguments.value)
            if result:
                _report(result)
            else:
                print(f"Boyut kaydedildi: {arguments.value:.2f}")
        elif arguments.command == "reset":
            restored = gnome.reset()
            print(f"Geri dönüldü: {restored}" if restored else "Geri dönülecek bir şey yok.")
        else:
            print(f"Skin: {gnome.current_skin() or 'yok'}")
            print(f"Boyut: {gnome.cursor_size():.2f}")
            print(f"Trail eklentisi: {'açık' if gnome.extension_active() else 'kapalı'}")
    except SkinError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
