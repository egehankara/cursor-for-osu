"""Command line entry point. Without arguments it opens the window."""

from __future__ import annotations

import argparse
import os
import sys

if sys.platform == "win32":
    from . import windows as desktop
else:
    from . import gnome as desktop

from .library import Result
from .i18n import _
from .skin import SkinError


def _report(result: Result) -> None:
    print(_("Applied: {name} ({size} px)").format(name=result.skin_name, size=result.size_px))
    problem = desktop.trail_problem() if sys.platform != "win32" else None
    if problem:
        print(problem)


def _uninstall(keep_data: bool) -> int:
    """Run the uninstall script that install.sh put next to the app."""
    script = desktop.data_dir() / "uninstall.sh"
    if not script.is_file():
        print(_("The uninstall script was not found. Run uninstall.sh from the source folder."), file=sys.stderr)
        return 1
    os.execvp("bash", ["bash", str(script), *(["--keep-data"] if keep_data else [])])


def main() -> int:
    is_windows = sys.platform == "win32"
    if is_windows:
        # A packaged process may already have its DPI context set by the manifest.
        desktop.win32.set_dpi_context(-4)  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
    parser = argparse.ArgumentParser(prog="cursor-for-osu")
    # effect-off and effect-on are run by the KWin effect, not by people, so they aren't listed.
    commands = parser.add_subparsers(dest="command", metavar=(
        "{apply,size,reset,status}" if is_windows else "{apply,size,reset,status,uninstall}"
    ))
    apply_parser = commands.add_parser("apply", help=_("apply a skin"))
    apply_parser.add_argument("skin", help=_(".osk file or skin folder"))
    apply_parser.add_argument(
        "--size",
        type=float,
        help=_("cursor size from 0.1 to 2.0 (default: the last one set, or your osu!lazer setting)"),
    )
    size_parser = commands.add_parser("size", help=_("change the cursor size"))
    size_parser.add_argument("value", type=float, help=_("from 0.1 to 2.0, like in the game"))
    commands.add_parser("reset", help=_("go back to the previous cursor"))
    commands.add_parser("status", help=_("show the applied skin"))
    if not is_windows:
        uninstall_parser = commands.add_parser("uninstall", help=_("remove Cursor for osu! from this computer"))
        uninstall_parser.add_argument(
            "--keep-data", action="store_true", help=_("keep the skin list and settings")
        )
        commands.add_parser("effect-off")
        commands.add_parser("effect-on")
    arguments = parser.parse_args()

    if arguments.command is None:
        if is_windows:
            from .windows_gui import run
        else:
            from .gui import run

        return run()
    if arguments.command == "uninstall":
        return _uninstall(arguments.keep_data)
    if arguments.command in ("effect-off", "effect-on"):
        try:
            if arguments.command == "effect-off":
                desktop.plasma_effect_turned_off()
            else:
                desktop.plasma_effect_turned_on()
        except SkinError as error:
            print(error, file=sys.stderr)
            return 1
        return 0

    try:
        if arguments.command == "apply":
            _report(desktop.apply_skin(arguments.skin, arguments.size))
        elif arguments.command == "size":
            result = desktop.set_cursor_size(arguments.value)
            if result:
                _report(result)
            else:
                print(_("Size saved: {size}").format(size=f"{arguments.value:.2f}"))
        elif arguments.command == "reset":
            restored = desktop.reset()
            if is_windows:
                print(_("Back to the previous cursor"))
            else:
                print(_("Back to: {theme}").format(theme=restored) if restored else _("Nothing to go back to."))
        elif is_windows:
            print(_("Skin: {name}").format(name=desktop.active().get("name") or _("none")))
            print(_("Size: {size}").format(size=f"{desktop.cursor_size():.2f}"))
        else:
            print(_("Skin: {name}").format(name=desktop.current_skin() or _("none")))
            print(_("Size: {size}").format(size=f"{desktop.cursor_size():.2f}"))
            print(
                _("Trail extension: {state}").format(
                    state=_("on") if desktop.extension_active() else _("off")
                )
            )
            if problem := desktop.trail_problem():
                print(problem)
        if not is_windows and (notice := desktop.desktop_notice()):
            print(notice)
    except (SkinError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
