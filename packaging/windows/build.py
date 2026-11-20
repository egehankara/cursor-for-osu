"""Build the portable Windows archive from an environment with requirements.txt installed."""
import io
import os
from importlib.metadata import distribution
from pathlib import Path
import shutil
import struct
import subprocess
import sys
from urllib.request import urlretrieve

from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
import PySide6


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build" / "windows"
NAME = "CursorForOsu"
SOURCE_ICON = ROOT / "data/icons/hicolor/scalable/apps/io.github.egehankara.CursorForOsu.svg"
QT_LICENSES = "https://raw.githubusercontent.com/qt/qtbase/v6.12.0/LICENSES/"


def make_icon(destination):
    image = QImage(256, 256, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    QSvgRenderer(str(SOURCE_ICON)).render(painter)
    painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    Image.open(io.BytesIO(bytes(buffer.data()))).save(destination)


def build():
    if sys.platform != "win32" or struct.calcsize("P") != 8:
        raise SystemExit("Build on Windows with 64-bit Python.")
    BUILD.mkdir(parents=True, exist_ok=True)
    icon = BUILD / "app.ico"
    make_icon(icon)
    qt = Path(PySide6.__file__).parent
    binary_args = []
    for file in qt.glob("vcruntime140*.dll"):
        binary_args.extend(("--add-binary", f"{file};."))
    # Keep unrelated DLLs from the development machine out of the dependency scan.
    system = Path(os.environ["SystemRoot"])
    build_env = {**os.environ, "PATH": os.pathsep.join(map(str, (
        Path(sys.executable).parent, Path(sys.base_prefix), qt, system / "System32", system,
    )))}
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir", "--windowed",
        "--name", NAME, "--paths", str(ROOT), "--icon", str(icon),
        "--add-data", f"{icon};osu_cursor",
        "--add-data", f"{ROOT / 'osu_cursor/locale'};osu_cursor/locale",
        *binary_args,
        "--exclude-module", "gi", "--exclude-module", "tkinter",
        "--specpath", str(BUILD), "--workpath", str(BUILD / "work"),
        "--distpath", str(BUILD / "dist"), str(Path(__file__).with_name("launcher.py")),
    ], check=True, cwd=ROOT, env=build_env)
    app = BUILD / "dist" / NAME
    notices = app / "licenses"
    notices.mkdir(exist_ok=True)
    for name in ("LICENSE", "THIRD-PARTY-NOTICES"):
        shutil.copy2(ROOT / name, app / name)
    shutil.copy2(Path(__file__).with_name("README.txt"), app / "README.txt")
    for name in ("Pillow", "PyInstaller"):
        dist = distribution(name)
        for file in dist.files or ():
            if "licenses" in file.parts:
                shutil.copy2(dist.locate_file(file), notices / f"{name}-{file.name}")
    for name in ("LGPL-3.0-only.txt", "GPL-3.0-only.txt"):
        cached = BUILD / name
        if not cached.is_file():
            urlretrieve(QT_LICENSES + name, cached)
        shutil.copy2(cached, notices / name)
    for name in ("LICENSE.txt", "LICENSE"):
        license_path = Path(sys.base_prefix) / name
        if license_path.is_file():
            shutil.copy2(license_path, notices / "Python-LICENSE.txt")
            break
    else:
        raise FileNotFoundError("Python license was not found next to the interpreter.")
    print(shutil.make_archive(str(BUILD / "CursorForOsu-windows-x64"), "zip", app.parent, app.name))


if __name__ == "__main__":
    build()
