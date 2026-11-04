"""Оригинальный интерфейс GTA5RP: достаём его из официального установщика пользователя.

Файлы интерфейса (app.asar: HTML/JS/шрифты/картинки) принадлежат GTA5RP и в репозиторий
не кладутся. Лаунчер берёт их из launcher_setup_*.exe, который пользователь скачал сам
с gta5rp.com, и складывает в ~/.local/share/gta5rp-launcher/official/.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import struct
import subprocess
from pathlib import Path

import gta5rp_core as core

if core.IS_WIN:
    DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "gta5rp-launcher"
else:
    DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "gta5rp-launcher"
OFFICIAL_DIR = DATA_DIR / "official"
UI_DIR = OFFICIAL_DIR / "ui"
INFO_FILE = OFFICIAL_DIR / "info.json"
INDEX_REL = ".vite/renderer/main_window/index.html"


OFFICIAL_UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{41E23FD2-639F-44A6-B8A2-DF4026702DA7}_is1"


def find_installed_asar() -> Path | None:
    """Windows: app.asar установленного официального лаунчера."""
    if not core.IS_WIN:
        return None
    import winreg
    dirs = []
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (0, getattr(winreg, "KEY_WOW64_64KEY", 0), getattr(winreg, "KEY_WOW64_32KEY", 0)):
            try:
                with winreg.OpenKey(root, OFFICIAL_UNINSTALL_KEY, 0, winreg.KEY_READ | view) as k:
                    dirs.append(Path(winreg.QueryValueEx(k, "InstallLocation")[0]))
            except OSError:
                pass
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    dirs += [DATA_DIR / "official-install", local / "Programs" / "GTA5RP Launcher", Path(r"C:\GTA5RP Launcher")]
    for d in dirs:
        a = d / "gui" / "resources" / "app.asar"
        if a.is_file():
            return a
    return None


def install_official_windows(installer: Path) -> Path:
    """Windows: тихо ставит официальный лаунчер в нашу папку (это и есть их обычная установка)."""
    target = DATA_DIR / "official-install"
    subprocess.run([str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER",
                    "/NOICONS", f"/DIR={target}"], timeout=900)
    # установщик в конце запускает официальный лаунчер — закрываем его
    for im in ("ecef_process.exe", "GTA5RPLauncher.exe"):
        subprocess.run(["taskkill", "/F", "/IM", im], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    a = target / "gui" / "resources" / "app.asar"
    if not a.is_file():
        raise RuntimeError("Официальный лаунчер установился без интерфейса (gui/resources/app.asar)")
    return a


INSTALLER_URL = "https://files.gta5rp.com/builds/launcher_setup_{v}.exe"


def download_installer(progress=None) -> Path:
    """Скачивает официальный установщик с files.gta5rp.com (версию сообщает API лаунчера)."""
    v = str(core.Api().launcher_update().get("v") or core.OFFICIAL_VERSION)
    if not re.fullmatch(r"\d+(\.\d+){1,3}", v):
        v = core.OFFICIAL_VERSION
    dest = core.CACHE_DIR / f"launcher_setup_{v}.exe"
    if dest.is_file() and dest.stat().st_size > 50_000_000:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    import urllib.request
    req = urllib.request.Request(INSTALLER_URL.format(v=v), headers={"User-Agent": core.UA})
    tmp = dest.with_suffix(".part")
    with urllib.request.urlopen(req, timeout=60, context=core._ctx()) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        while chunk := r.read(1 << 20):
            f.write(chunk)
            got += len(chunk)
            if progress and total:
                progress(f"Скачиваю официальный установщик GTA5RP… {got * 100 // total}%")
    with open(tmp, "rb") as f:
        if f.read(2) != b"MZ" or tmp.stat().st_size < 50_000_000:
            tmp.unlink(missing_ok=True)
            raise RuntimeError("Скачанный установщик повреждён")
    tmp.replace(dest)
    return dest


def find_installer() -> Path | None:
    found = []
    for d in (Path.home() / "Загрузки", Path.home() / "Downloads", Path.home(), core.CACHE_DIR):
        if d.is_dir():
            found += [f for f in d.glob("launcher_setup*.exe") if f.is_file()]
    return max(found, key=lambda f: f.stat().st_mtime) if found else None


def installed_info() -> dict:
    try:
        info = json.loads(INFO_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return info if (UI_DIR / INDEX_REL).is_file() else {}


def index_html() -> Path | None:
    p = UI_DIR / INDEX_REL
    return p if p.is_file() else None


# ---------------------------------------------------------------- asar

def extract_asar(asar: Path, dest: Path) -> int:
    """Минимальный распаковщик Electron asar. Возвращает число файлов."""
    with open(asar, "rb") as f:
        head = f.read(16)
        _, header_size, _, json_len = struct.unpack("<4I", head)
        header = json.loads(f.read(json_len).decode("utf-8"))
        base = 8 + header_size
        count = 0
        unpacked = Path(str(asar) + ".unpacked")
        root = dest.resolve()

        def walk(node: dict, rel: Path):
            nonlocal count
            for name, item in node.get("files", {}).items():
                if name in ("", ".", "..") or "/" in name or "\\" in name:
                    raise ValueError(f"плохое имя в asar: {name!r}")
                path = rel / name
                out = (dest / path).resolve()
                if root not in out.parents:
                    raise ValueError(f"путь вне папки: {path}")
                if "files" in item:
                    out.mkdir(parents=True, exist_ok=True)
                    walk(item, path)
                elif "link" in item:
                    continue  # симлинки не нужны
                else:
                    out.parent.mkdir(parents=True, exist_ok=True)
                    if item.get("unpacked"):
                        src = unpacked / path
                        if src.is_file():
                            shutil.copyfile(src, out)
                    else:
                        f.seek(base + int(item["offset"]))
                        out.write_bytes(f.read(int(item["size"])))
                    count += 1
        walk(header, Path())
    return count


# ---------------------------------------------------------------- установщик

def _wine() -> tuple[list[str], Path | None]:
    if shutil.which("wine"):
        return ["wine"], Path(shutil.which("wineserver") or "wineserver")
    s = core.detect(core.load_config())
    if s.proton:
        for b in ("files/bin", "dist/bin"):
            w = s.proton / b / "wine"
            if w.is_file():
                return [str(w)], s.proton / b / "wineserver"
    raise RuntimeError("Для распаковки установщика нужен Wine (пакет wine) или Proton из Steam.")


def unpack_asar(asar: Path, source_name: str, size: int, mtime: float) -> dict:
    new = OFFICIAL_DIR.with_name("official.new")
    shutil.rmtree(new, ignore_errors=True)
    (new / "ui").mkdir(parents=True)
    n = extract_asar(asar, new / "ui")
    if not (new / "ui" / INDEX_REL).is_file():
        raise RuntimeError("Неизвестная структура интерфейса — нужна новая версия этого лаунчера")
    m = re.search(r"(\d+(?:\.\d+){2,3})", source_name)
    info = {"installer": source_name, "version": m.group(1) if m else "", "size": size, "mtime": mtime, "files": n}
    (new / "info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.rmtree(OFFICIAL_DIR, ignore_errors=True)
    new.rename(OFFICIAL_DIR)
    return info


def prepare_windows(progress=None) -> dict | None:
    """Windows: интерфейс из установленного официального лаунчера (или ставим его из «Загрузок»)."""
    asar = find_installed_asar()
    if asar is None:
        inst = find_installer() or download_installer(progress)
        if progress:
            progress("Устанавливаю официальный лаунчер GTA5RP (нужен его интерфейс)…")
        asar = install_official_windows(inst)
    st = asar.stat()
    info = installed_info()
    if info.get("size") == st.st_size and info.get("mtime") == st.st_mtime:
        return info
    return unpack_asar(asar, f"app.asar {core.OFFICIAL_VERSION}", st.st_size, st.st_mtime)


def extract_from_installer(installer: Path, progress=None) -> dict:
    """Ставит официальный лаунчер во временный Wine-префикс (без ярлыков в меню),
    забирает оттуда app.asar и удаляет префикс."""
    wine, wineserver = _wine()
    tmp = core.CACHE_DIR / "extract-pfx"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    env = dict(os.environ, WINEPREFIX=str(tmp), WINEDEBUG="-all",
               WINEDLLOVERRIDES="winemenubuilder.exe=d;mscoree=;mshtml=")
    try:
        if progress:
            progress("Распаковываю официальный установщик (это один раз, ~1 мин)…")
        subprocess.run([*wine, str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                        "/CURRENTUSER", "/NOICONS", r"/DIR=C:\5rp"],
                       env=env, timeout=900, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # установщик в конце сам запускает лаунчер — гасим всё в префиксе
        subprocess.run([str(wineserver), "-k"], env=env, timeout=60, capture_output=True)
        asar = tmp / "drive_c" / "5rp" / "gui" / "resources" / "app.asar"
        if not asar.is_file():
            raise RuntimeError("В установщике не нашёлся интерфейс (gui/resources/app.asar)")
        if progress:
            progress("Распаковываю интерфейс…")
        new = OFFICIAL_DIR.with_name("official.new")
        shutil.rmtree(new, ignore_errors=True)
        (new / "ui").mkdir(parents=True)
        n = extract_asar(asar, new / "ui")
        if not (new / "ui" / INDEX_REL).is_file():
            raise RuntimeError("Неизвестная структура интерфейса — нужна новая версия этого лаунчера")
        m = re.search(r"(\d+(?:\.\d+){2,3})", installer.name)
        info = {"installer": installer.name, "version": m.group(1) if m else "",
                "size": installer.stat().st_size, "mtime": installer.stat().st_mtime, "files": n}
        (new / "info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        shutil.rmtree(OFFICIAL_DIR, ignore_errors=True)
        new.rename(OFFICIAL_DIR)
        return info
    finally:
        subprocess.run([str(wineserver), "-k"], env=env, timeout=60, capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)


def needs_update(installer: Path | None) -> bool:
    if not installer:
        return False
    info = installed_info()
    return not info or info.get("size") != installer.stat().st_size or info.get("installer") != installer.name
