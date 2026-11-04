"""GTA5RP Launcher for Linux — ядро без интерфейса.

Как устроен официальный лаунчер (v1.0.0.11):
  * UI на Electron ходит в https://api.gta5rp.com/api/V2 (вход, сервера, новости);
  * перед входом в игру берёт одноразовый токен GET users/auth/rage/token;
  * ядро (GTA5RPLauncher.exe) кладёт RAGE:MP updater.exe в папку RageMP,
    пишет в HKCU\\Software\\RAGE-MP значения launch2.ip / launch2.port /
    launch2.params (= токен) и запускает updater.exe без аргументов.
    Дальше RAGE:MP сам обновляется, подключается к серверу и стартует GTA V.

Здесь то же самое делается напрямую, а RAGE:MP запускается через Proton
в префиксе GTA V из Steam (compatdata/271590), чтобы игра видела Steam.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import ssl
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

VERSION = "1.0.0"
OFFICIAL_VERSION = "1.0.0.11"  # версия официального лаунчера, с которой сверялся протокол

API = "https://api.gta5rp.com/api/V2/"
SITE = "https://gta5rp.com"
UPDATER_URLS = (
    "https://cdn.rgsvc.io/updater/prerelease/updater.exe",
    "https://static.gta5rp.com/RAGEMP_FILES/updater.exe",
    "https://via2.gta5rp.com/updater.exe",
)
GTA_APPID = "271590"
EAC_RUNTIME_APPID = "1826330"  # Proton EasyAntiCheat Runtime
RAGE_WIN_DIR = r"C:\Games\GTA5RP\RageMP"  # папка по умолчанию у официального лаунчера
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) " \
     "Chrome/140.0.0.0 Electron/38.2.1 Safari/537.36"

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "gta5rp-launcher"
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "gta5rp-launcher"
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "gta5rp-launcher"
CONFIG_FILE = CONFIG_DIR / "config.json"

# адрес сервера попадает в .reg-файл — пропускаем только обычные символы хоста
_SAFE_HOST = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
# ключ капчи подставляется в JS — только простые символы
_SAFE_KEY = re.compile(r"^[A-Za-z0-9._~+/=-]{1,512}$")


# ---------------------------------------------------------------- config

DEFAULTS = {
    "session_token": "",
    "login": "",
    "last_server": 0,
    "proton": "",          # путь к папке Proton; пусто = автоматически
    "steam_root": "",      # пусто = автоматически
    "gta_path": "",        # пусто = из Steam
    "close_on_play": False,
}


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # в файле токен сессии
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_FILE)


# ---------------------------------------------------------------- HTTP API

class ApiError(Exception):
    def __init__(self, status: int, data: dict | None, message: str):
        super().__init__(message)
        self.status = status
        self.data = data or {}

    @property
    def need_captcha(self) -> bool:
        return self.data.get("error_message") == "need_captcha" and bool(self.data.get("key"))

    @property
    def twofa_rid(self) -> str:
        return str(self.data.get("2fa_rid") or "")


def _ctx() -> ssl.SSLContext:
    return ssl.create_default_context()


def http_get(url: str, timeout: float = 20, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as r:
        return r.read()


def _error_text(data: dict | None, fallback: str) -> str:
    if not isinstance(data, dict):
        return fallback
    parts = []
    errs = data.get("errors")
    if isinstance(errs, dict):
        for v in errs.values():
            parts.extend(v if isinstance(v, list) else [v])
    for k in ("error", "message", "error_message"):
        if isinstance(data.get(k), str) and data[k] not in parts and data[k] != "need_captcha":
            parts.insert(0, data[k])
    return "\n".join(str(p) for p in parts if p) or fallback


class Api:
    def __init__(self, token: str = ""):
        self.token = token

    def request(self, path: str, method: str = "GET", body: dict | None = None,
                query: dict | None = None, timeout: float = 20):
        url = API + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = {"User-Agent": UA, "Accept": "application/json", "X-Lang": "ru"}
        if self.token:
            headers["X-Access-Token"] = self.token
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = None
            raise ApiError(e.code, payload, _error_text(payload, f"HTTP {e.code}")) from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ApiError(0, None, f"Нет связи с сервером 5RP: {getattr(e, 'reason', e)}") from None
        try:
            return json.loads(raw) if raw else {}
        except ValueError:
            raise ApiError(0, None, "Сервер вернул не JSON") from None

    # публичные
    def servers(self) -> list[dict]:
        return self.request("servers/stats")

    def news(self) -> list[dict]:
        r = self.request("news")
        return r.get("data", []) if isinstance(r, dict) else r

    def launcher_update(self) -> dict:
        return self.request("launcher/updates", query={"v": OFFICIAL_VERSION})

    # аккаунт
    def login(self, login: str, password: str, remember: bool = True,
              captcha: str = "", twofa_rid: str = "", twofa_code: str = "") -> str:
        body: dict = {"login": login, "password": password, "remember": remember}
        if captcha:
            body["_recaptcha_token"] = captcha
        if twofa_rid:
            body["2fa_rid"] = twofa_rid
            body["2fa_code"] = twofa_code
        r = self.request("users/auth/login", "POST", body)
        tok = r.get("token") if isinstance(r, dict) else None
        if not tok:
            # ответ без токена = нужен второй шаг (2FA / подтверждение)
            raise ApiError(200, r if isinstance(r, dict) else None,
                           _error_text(r if isinstance(r, dict) else None, "Нужно подтверждение входа"))
        self.token = tok
        return tok

    def logout(self) -> None:
        try:
            self.request("users/auth/logout", "POST", {})
        finally:
            self.token = ""

    def profile(self) -> dict:
        r = self.request("users")
        return r.get("result", r) if isinstance(r, dict) else {}

    def rage_token(self) -> str:
        r = self.request("users/auth/rage/token", timeout=10)
        tok = r.get("token") if isinstance(r, dict) else None
        if not tok:
            raise ApiError(0, r if isinstance(r, dict) else None, "Сервер не выдал игровой токен")
        return tok


# ---------------------------------------------------------------- Steam / Proton

def _vdf_paths(text: str) -> list[str]:
    return [m.replace("\\\\", "\\") for m in re.findall(r'"path"\s+"([^"]+)"', text)]


def steam_roots(cfg: dict | None = None) -> list[Path]:
    home = Path.home()
    cands = []
    if cfg and cfg.get("steam_root"):
        cands.append(Path(cfg["steam_root"]).expanduser())
    cands += [home / ".local/share/Steam", home / ".steam/steam", home / ".steam/root",
              home / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
              home / "snap/steam/common/.local/share/Steam"]
    seen, out = set(), []
    for c in cands:
        try:
            r = c.resolve()
        except OSError:
            continue
        if r not in seen and (r / "steamapps").is_dir():
            seen.add(r)
            out.append(r)
    return out


def steam_libraries(root: Path) -> list[Path]:
    libs = [root / "steamapps"]
    vdf = root / "steamapps" / "libraryfolders.vdf"
    try:
        for p in _vdf_paths(vdf.read_text(encoding="utf-8", errors="ignore")):
            libs.append(Path(p) / "steamapps")
    except OSError:
        pass
    seen, out = set(), []
    for lib in libs:
        try:
            r = lib.resolve()
        except OSError:
            continue
        if r not in seen and r.is_dir():
            seen.add(r)
            out.append(r)
    return out


@dataclass
class Setup:
    steam_root: Path | None = None
    steamapps: Path | None = None       # библиотека, где стоит GTA V
    gta_path: Path | None = None
    compatdata: Path | None = None       # .../compatdata/271590
    proton: Path | None = None           # папка Proton (с файлом "proton")
    protons: list[Path] = field(default_factory=list)
    runtime_entry: Path | None = None    # SteamLinuxRuntime_*/_v2-entry-point
    eac_runtime: Path | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def pfx(self) -> Path | None:
        return self.compatdata / "pfx" if self.compatdata else None

    @property
    def rage_dir(self) -> Path | None:
        return self.pfx / "drive_c" / "Games" / "GTA5RP" / "RageMP" if self.pfx else None

    @property
    def ok(self) -> bool:
        return not self.problems


def _proton_version_key(p: Path) -> tuple:
    name = p.name.lower()
    if "experimental" in name:
        return (2, 0)
    nums = [int(x) for x in re.findall(r"\d+", name)[:3]]
    return (1, *nums) if nums else (0,)


def find_protons(roots: list[Path], libs: list[Path]) -> list[Path]:
    out = []
    for lib in libs:
        for d in sorted((lib / "common").glob("Proton*")):
            if (d / "proton").is_file():
                out.append(d)
    for root in roots:
        for base in (root / "compatibilitytools.d", Path("/usr/share/steam/compatibilitytools.d")):
            if base.is_dir():
                for d in sorted(base.iterdir()):
                    if (d / "proton").is_file():
                        out.append(d)
    seen, res = set(), []
    for d in out:
        r = d.resolve()
        if r not in seen:
            seen.add(r)
            res.append(r)
    return res


def find_runtime(proton: Path, libs: list[Path]) -> Path | None:
    """Steam Linux Runtime, которого требует этот Proton (toolmanifest.vdf → require_tool_appid)."""
    names = []
    try:
        m = re.search(r'"require_tool_appid"\s+"(\d+)"',
                      (proton / "toolmanifest.vdf").read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        m = None
    if m:
        for lib in libs:
            try:
                acf = (lib / f"appmanifest_{m.group(1)}.acf").read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            d = re.search(r'"installdir"\s+"([^"]+)"', acf)
            if d:
                names.append(d.group(1))
    else:
        return None  # старый Proton без контейнера
    for name in names:
        for lib in libs:
            e = lib / "common" / name / "_v2-entry-point"
            if e.is_file():
                return e
    return None


def detect(cfg: dict) -> Setup:
    s = Setup()
    roots = steam_roots(cfg)
    if not roots:
        s.problems.append("Steam не найден. Установите Steam и GTA V.")
        return s
    s.steam_root = roots[0]
    libs = [lib for r in roots for lib in steam_libraries(r)]

    for lib in libs:
        if (lib / f"appmanifest_{GTA_APPID}.acf").is_file():
            s.steamapps = lib
            s.gta_path = lib / "common" / "Grand Theft Auto V"
            break
    if cfg.get("gta_path"):
        s.gta_path = Path(cfg["gta_path"]).expanduser()
    if not s.gta_path or not (s.gta_path / "GTA5.exe").is_file():
        s.problems.append("GTA V (Steam) не найдена. Установите Grand Theft Auto V в Steam.")

    for lib in libs:
        cd = lib / "compatdata" / GTA_APPID
        if (cd / "pfx").is_dir():
            s.compatdata = cd
            break
    if not s.compatdata:
        s.problems.append("Нет Proton-префикса GTA V. Включите Proton для GTA V в Steam "
                          "(Свойства → Совместимость) и запустите игру из Steam один раз.")

    s.protons = find_protons(roots, libs)
    if cfg.get("proton") and (Path(cfg["proton"]) / "proton").is_file():
        s.proton = Path(cfg["proton"])
    elif s.protons:
        official = [p for p in s.protons if "compatibilitytools.d" not in str(p)]
        s.proton = max(official or s.protons, key=_proton_version_key)
    if not s.proton:
        s.problems.append("Proton не найден. Установите «Proton Experimental» в Steam.")

    s.runtime_entry = find_runtime(s.proton, libs) if s.proton else None
    for lib in libs:
        eac = lib / "common" / "Proton EasyAntiCheat Runtime"
        if eac.is_dir() and not s.eac_runtime:
            s.eac_runtime = eac
    return s


def steam_running() -> bool:
    try:
        return subprocess.run(["pgrep", "-x", "steam"], capture_output=True).returncode == 0
    except OSError:
        return True


# ---------------------------------------------------------------- RAGE:MP

def ensure_updater(rage_dir: Path, progress=None) -> Path:
    """Кладёт updater.exe в папку RAGE:MP (как ядро официального лаунчера)."""
    exe = rage_dir / "updater.exe"
    if exe.is_file() and exe.stat().st_size > 100_000:
        return exe
    rage_dir.mkdir(parents=True, exist_ok=True)
    last = None
    for url in UPDATER_URLS:
        try:
            if progress:
                progress(f"Скачиваю RAGE:MP updater ({urllib.parse.urlparse(url).netloc})…")
            data = http_get(url, timeout=60)
            if data[:2] != b"MZ" or len(data) < 100_000:
                raise ValueError("файл не похож на exe")
            tmp = exe.with_suffix(".part")
            tmp.write_bytes(data)
            os.replace(tmp, exe)
            return exe
        except (OSError, ValueError, urllib.error.URLError) as e:
            last = e
    raise RuntimeError(f"Не удалось скачать RAGE:MP updater: {last}")


def map_gta_drive(pfx: Path, gta: Path) -> None:
    """Диск G: в префиксе → папка GTA V (удобно выбрать в RAGE:MP)."""
    link = pfx / "dosdevices" / "g:"
    try:
        if link.is_symlink() and Path(os.readlink(link)) == gta:
            return
        if link.is_symlink() or not link.exists():
            if link.is_symlink():
                link.unlink()
            link.symlink_to(gta)
    except OSError:
        pass


def _reg_str(v: str) -> str:
    """Строковое значение для .reg-файла: экранируем \\ и "."""
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _write_private(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)


def write_launch_reg(s: Setup, host: str, port: int, token: str) -> Path:
    """.reg-файл с launch2.* для HKCU\\Software\\RAGE-MP (как пишет ядро официального лаунчера).

    Токен идёт через файл, а не через командную строку, поэтому в нём можно любые символы.
    """
    if not _SAFE_HOST.match(host) or not (0 < int(port) < 65536):
        raise ValueError(f"Странный адрес сервера: {host}:{port}")
    token = token.strip()
    if not token or any(ord(ch) < 32 for ch in token):
        raise ValueError("Сервер выдал пустой или повреждённый игровой токен")
    base = s.rage_dir.parent  # C:\Games\GTA5RP
    reg = "\r\n".join([
        "Windows Registry Editor Version 5.00",
        "",
        r"[HKEY_CURRENT_USER\Software\RAGE-MP]",
        f'"launch2.ip"={_reg_str(host)}',
        f'"launch2.port"={_reg_str(str(int(port)))}',
        f'"launch2.params"={_reg_str(token)}',
        "", "",
    ])
    path = base / "launch5rp.reg"
    _write_private(path, b"\xff\xfe" + reg.encode("utf-16-le"))
    (base / "launch5rp.bat").unlink(missing_ok=True)  # от старой версии лаунчера
    return path


def proton_command(s: Setup, args: list[str], debug: bool = False) -> tuple[list[str], dict]:
    env = dict(os.environ)
    env.update({
        "STEAM_COMPAT_DATA_PATH": str(s.compatdata),
        "STEAM_COMPAT_CLIENT_INSTALL_PATH": str(s.steam_root),
        "STEAM_COMPAT_INSTALL_PATH": str(s.gta_path),
        "STEAM_COMPAT_APP_ID": GTA_APPID,
        "SteamAppId": GTA_APPID, "SteamGameId": GTA_APPID, "SteamOverlayGameId": GTA_APPID,
        "SteamEnv": "1", "SteamClientLaunch": "1",
    })
    if s.steamapps:
        env["STEAM_COMPAT_LIBRARY_PATHS"] = str(s.steamapps)
        env["STEAM_COMPAT_SHADER_PATH"] = str(s.steamapps / "shadercache" / GTA_APPID)
    if s.eac_runtime:
        env["PROTON_EAC_RUNTIME"] = str(s.eac_runtime)
    if debug:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        env["PROTON_LOG"] = "1"
        env["PROTON_LOG_DIR"] = str(STATE_DIR)
    cmd = [str(s.proton / "proton"), "waitforexitandrun", *args]
    if s.runtime_entry:
        mounts = [p for p in (s.proton, s.runtime_entry.parent,
                              s.steamapps / "common" / "Steamworks Shared" if s.steamapps else None)
                  if p and p.exists()]
        env["STEAM_COMPAT_TOOL_PATHS"] = ":".join(str(p) for p in (s.proton, s.runtime_entry.parent))
        env["STEAM_COMPAT_MOUNTS"] = ":".join(str(p) for p in mounts)
        cmd = [str(s.runtime_entry), "--verb=waitforexitandrun", "--", *cmd]
    return cmd, env


def prepare_launch(s: Setup, host: str, port: int, token: str, progress=None, debug=False):
    """Всё, что делает GTA5RPLauncher.exe перед стартом. Возвращает (cmd, env, cwd)."""
    if not s.ok:
        raise RuntimeError("\n".join(s.problems))
    ensure_updater(s.rage_dir, progress)
    for sub in ("clientdata", "EasyAntiCheat"):
        (s.rage_dir / sub).mkdir(exist_ok=True)
    map_gta_drive(s.pfx, s.gta_path)
    reg = write_launch_reg(s, host, port, token)
    win_reg = "C:\\" + str(reg.relative_to(s.pfx / "drive_c")).replace("/", "\\")
    # 1) regedit /S — оконное приложение, без консоли; 2) удалить .reg с токеном; 3) updater.exe
    step1, env = proton_command(s, ["regedit.exe", "/S", win_reg], debug)
    step3, _ = proton_command(s, [f"{RAGE_WIN_DIR}\\updater.exe"], debug)
    script = f"{shlex.join(step1)}; rm -f {shlex.quote(str(reg))}; exec {shlex.join(step3)}"
    return ["/bin/sh", "-c", script], env, str(s.rage_dir)


GAME_PROCS = ("GTA5.exe", "PlayGTAV.exe", "ragemp_v.exe", "updater.exe", "ragemp_game_ui.exe")


def running_game_procs() -> list[str]:
    found = []
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            cmd = (d / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore")
        except OSError:
            continue
        for p in GAME_PROCS:
            if p.lower() in cmd.lower() and p not in found:
                found.append(p)
    return found


def kill_prefix(s: Setup) -> None:
    """Аварийно закрыть всё в префиксе GTA V."""
    if not (s.proton and s.compatdata):
        return
    ws = None
    for cand in (s.proton / "files/bin/wineserver", s.proton / "dist/bin/wineserver"):
        if cand.is_file():
            ws = cand
    if ws:
        env = dict(os.environ, WINEPREFIX=str(s.pfx))
        subprocess.run([str(ws), "-k"], env=env, timeout=20, capture_output=True)


# ---------------------------------------------------------------- значки (из официального установщика)

def extract_official_icon(dest_png: Path) -> bool:
    """Достаёт значок из официального launcher_setup*.exe в ~/Загрузки (если есть)."""
    dl = [Path.home() / "Загрузки", Path.home() / "Downloads"]
    exe = None
    for d in dl:
        for f in sorted(d.glob("launcher_setup*.exe"), reverse=True) if d.is_dir() else []:
            exe = f
            break
        if exe:
            break
    if not exe or not shutil.which("7z"):
        return False
    tmp = CACHE_DIR / "icon"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        subprocess.run(["7z", "e", "-y", f"-o{tmp}", str(exe), ".rsrc/1033/ICON/100.ico"],
                       capture_output=True, timeout=60)
        ico = tmp / "100.ico"
        if not ico.is_file():
            return False
        from PySide6.QtGui import QImage  # noqa: WPS433
        img = QImage(str(ico))
        if img.isNull():
            return False
        dest_png.parent.mkdir(parents=True, exist_ok=True)
        return img.save(str(dest_png))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

