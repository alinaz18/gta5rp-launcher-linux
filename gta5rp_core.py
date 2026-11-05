"""GTA5RP Launcher for Linux — ядро без интерфейса.

Как устроен официальный лаунчер (v1.0.0.11):
  * UI на Electron ходит в https://api.gta5rp.com/api/V2 (вход, сервера, новости);
  * перед входом в игру берёт одноразовый токен GET users/auth/rage/token;
  * ядро (GTA5RPLauncher.exe) кладёт RAGE:MP updater.exe в папку RageMP,
    пишет в HKCU\\Software\\RAGE-MP значения launch2.ip / launch2.port /
    launch2.params (= токен) и запускает updater.exe без аргументов.
    Дальше RAGE:MP сам обновляется, подключается к серверу и стартует GTA V.

Здесь то же самое делается напрямую, а RAGE:MP запускается через Proton
в префиксе GTA V: у Steam-версии это compatdata/271590 (чтобы игра видела Steam),
у версий Rockstar Games Launcher и Epic Games Store — Wine-префикс, где они
установлены (Heroic, Lutris, Bottles или свой), через Proton или Wine.
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

VERSION = "1.3.0"
IS_WIN = os.name == "nt"
OFFICIAL_VERSION = "1.0.0.11"  # версия официального лаунчера, с которой сверялся протокол

API = "https://api.gta5rp.com/api/V2/"
SITE = "https://gta5rp.com"
UPDATER_URLS = (
    "https://cdn.rgsvc.io/updater/prerelease/updater.exe",
    "https://static.gta5rp.com/RAGEMP_FILES/updater.exe",
    "https://via2.gta5rp.com/updater.exe",
)
GTA_APPID = "271590"               # GTA V Legacy в Steam
GTA_ENHANCED_APPID = "3240220"     # GTA V Enhanced в Steam (RAGE:MP её не поддерживает)
EPIC_GTA_APP = "9d2d0eb64d5c44529cece33fe2a46482"  # GTA V в Epic Games Store (legendary/Heroic)
STORES = {"steam": "Steam", "rgl": "Rockstar Games Launcher", "egs": "Epic Games Store"}
STORE_SHORT = {"steam": "Steam", "rgl": "Rockstar", "egs": "Epic"}
RGL_INSTALLER_URL = "https://gamedownloads.rockstargames.com/public/installer/Rockstar-Games-Launcher.exe"
EGL_INSTALLER_URL = ("https://launcher-public-service-prod06.ol.epicgames.com/launcher/api/installer/"
                     "download/EpicGamesLauncherInstaller.msi")
EAC_RUNTIME_APPID = "1826330"  # Proton EasyAntiCheat Runtime
RAGE_WIN_DIR = r"C:\Games\GTA5RP\RageMP"  # папка по умолчанию у официального лаунчера
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) " \
     "Chrome/140.0.0.0 Electron/38.2.1 Safari/537.36"

if IS_WIN:
    _APPDATA = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    _LOCAL = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    CONFIG_DIR = _APPDATA / "gta5rp-launcher"
    CACHE_DIR = _LOCAL / "gta5rp-launcher" / "cache"
    STATE_DIR = _LOCAL / "gta5rp-launcher" / "logs"
else:
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
    "gta_path": "",        # пусто = найти автоматически
    "store": "auto",       # auto / steam / rgl / egs
    "prefix": "",          # Wine-префикс для Rockstar/Epic; пусто = автоматически
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
class Install:
    """Найденная копия GTA V."""
    store: str                       # steam / rgl / egs
    gta_path: Path
    prefix: Path | None = None       # Wine-префикс (папка с drive_c)
    runner: Path | None = None       # Proton или Wine, которым её запускает родной лаунчер
    source: str = ""                 # Steam / Heroic / Lutris / Bottles / Wine / вручную
    edition: str = "legacy"          # legacy / enhanced


@dataclass
class Setup:
    steam_root: Path | None = None
    steamapps: Path | None = None       # библиотека, где стоит GTA V
    gta_path: Path | None = None
    compatdata: Path | None = None       # .../compatdata/271590 или папка с pfx
    prefix: Path | None = None           # Wine-префикс не из Steam (папка с drive_c)
    proton: Path | None = None           # папка Proton (с файлом "proton")
    wine: Path | None = None             # или бинарник Wine (для префиксов Lutris/Bottles)
    protons: list[Path] = field(default_factory=list)   # все Proton и Wine, что нашлись
    runtime_entry: Path | None = None    # SteamLinuxRuntime_*/_v2-entry-point
    eac_runtime: Path | None = None
    problems: list[str] = field(default_factory=list)
    native_rage: Path | None = None      # Windows: настоящая папка RAGE:MP, без Proton
    store: str = "steam"                 # steam / rgl / egs
    source: str = ""
    edition: str = "legacy"
    installs: list[Install] = field(default_factory=list)
    store_launcher: Path | None = None   # Rockstar Games Launcher / Epic Games Launcher в префиксе

    @property
    def pfx(self) -> Path | None:
        if self.prefix:
            return self.prefix
        return self.compatdata / "pfx" if self.compatdata else None

    @property
    def rage_dir(self) -> Path | None:
        if self.native_rage:
            return self.native_rage
        return self.pfx / "drive_c" / "Games" / "GTA5RP" / "RageMP" if self.pfx else None

    @property
    def runner(self) -> Path | None:
        return self.wine or self.proton

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


def detect_windows(cfg: dict) -> Setup:
    """Windows: ничего не эмулируем — RAGE:MP ставится в ту же папку, что у официального лаунчера."""
    s = Setup(native_rage=Path(cfg.get("rage_path") or RAGE_WIN_DIR))
    try:
        import winreg
        for root, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),):
            with winreg.OpenKey(root, key) as k:
                s.steam_root = Path(winreg.QueryValueEx(k, "SteamPath")[0])
    except OSError:
        pass
    if cfg.get("gta_path"):
        s.gta_path = Path(cfg["gta_path"])
    return s


# ---------------------------------------------------------------- Rockstar / Epic / Wine-префиксы

def gta_store(gta: Path) -> str:
    """Из какого магазина эта копия GTA V — по файлам DRM в её папке."""
    if (gta / "EOSSDK-Win64-Shipping.dll").exists():
        return "egs"
    if (gta / "steam_api64.dll").exists():
        return "steam"
    return "rgl"


def gta_edition(gta: Path) -> str:
    if (gta / "GTA5.exe").is_file():
        return "legacy"
    if (gta / "GTA5_Enhanced.exe").is_file():
        return "enhanced"
    return ""


def wine_prefix(d: Path) -> Path | None:
    """Папка с drive_c: сама d (Lutris, Bottles, Wine) или d/pfx (Proton, Heroic, umu)."""
    try:
        for c in (d / "pfx", d):
            if (c / "drive_c").is_dir():
                return c.resolve()
    except OSError:
        pass
    return None


def compat_dir(prefix: Path) -> Path:
    """STEAM_COMPAT_DATA_PATH для Proton: папка, внутри которой лежит pfx."""
    return prefix.parent if prefix.name == "pfx" else prefix


def win_to_unix(prefix: Path, win: str) -> Path | None:
    m = re.match(r"^([A-Za-z]):[\\/]*(.*)$", win.strip())
    if not m:
        return None
    drive = prefix / "dosdevices" / f"{m.group(1).lower()}:"
    if m.group(1).lower() == "c" and not drive.exists():
        drive = prefix / "drive_c"
    parts = [x for x in re.split(r"[\\/]+", m.group(2)) if x]
    return drive.joinpath(*parts) if parts else drive


def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _home() -> Path:
    return Path.home()


def _heroic_dirs() -> list[Path]:
    h = _home()
    cfg = Path(os.environ.get("XDG_CONFIG_HOME", h / ".config"))
    return [d for d in (cfg / "heroic", h / ".var/app/com.heroicgameslauncher.hgl/config/heroic") if d.is_dir()]


def _lutris_dirs() -> list[Path]:
    h = _home()
    return [d for d in (h / ".local/share/lutris", h / ".config/lutris",
                        h / ".var/app/net.lutris.Lutris/data/lutris",
                        h / ".var/app/net.lutris.Lutris/config/lutris") if d.is_dir()]


def _bottles_dirs() -> list[Path]:
    h = _home()
    return [d for d in (h / ".local/share/bottles", h / ".var/app/com.usebottles.bottles/data/bottles")
            if d.is_dir()]


def _runner_from_bin(path: str) -> Path | None:
    """Путь из настроек Heroic/Lutris → папка Proton или бинарник Wine."""
    if not path:
        return None
    p = Path(path).expanduser()
    if p.name == "proton" and p.is_file():
        return p.parent
    if (p / "proton").is_file():
        return p
    if p.is_file() and p.name.startswith("wine"):
        return p
    if (p / "bin" / "wine").is_file():
        return p / "bin" / "wine"
    return None


def gta_in_prefix(prefix: Path) -> list[Path]:
    """GTA V, установленная внутрь префикса: стандартные папки + путь из реестра Rockstar."""
    out = []
    c = prefix / "drive_c"
    for pf in ("Program Files", "Program Files (x86)"):
        for pat in ("Rockstar Games/Grand Theft Auto V*", "Epic Games/GTAV*", "Epic Games/GrandTheftAutoV*"):
            out += sorted((c / pf).glob(pat))
    try:
        reg = (prefix / "system.reg").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        reg = ""
    for m in re.finditer(r"\[Software\\\\(?:Wow6432Node\\\\)?Rockstar Games\\\\Grand Theft Auto V[^\]]*\][^\[]*?"
                         r'"InstallFolder"="([^"]+)"', reg, re.I):
        p = win_to_unix(prefix, m.group(1).replace("\\\\", "\\"))
        if p:
            out.append(p)
    return [p for p in out if gta_edition(p)]


def _heroic_installs() -> list[Install]:
    """Epic-версия из Heroic (legendary) + всё, что Heroic держит в своих префиксах."""
    found: list[Install] = []
    for hd in _heroic_dirs():
        games_cfg = {}
        for f in sorted((hd / "GamesConfig").glob("*.json")):
            data = _read_json(f)
            if isinstance(data, dict) and isinstance(data.get(f.stem), dict):
                games_cfg[f.stem] = data[f.stem]

        def prefix_of(app: str):
            g = games_cfg.get(app) or {}
            pre = wine_prefix(Path(g["winePrefix"]).expanduser()) if g.get("winePrefix") else None
            wv = g.get("wineVersion") or {}
            return pre, _runner_from_bin(wv.get("bin", "") if isinstance(wv, dict) else "")

        inst = _read_json(hd / "legendaryConfig/legendary/installed.json")
        for app, info in (inst.items() if isinstance(inst, dict) else []):
            if not isinstance(info, dict):
                continue
            if app != EPIC_GTA_APP and "grand theft auto v" not in str(info.get("title", "")).lower():
                continue
            gta = Path(str(info.get("install_path", ""))).expanduser()
            if gta_edition(gta):
                pre, run = prefix_of(app)
                found.append(Install("egs", gta, pre, run, "Heroic"))
        # Rockstar-версия, добавленная в Heroic вручную, лежит внутри его префиксов
        for app in games_cfg:
            pre, run = prefix_of(app)
            for gta in gta_in_prefix(pre) if pre else []:
                found.append(Install(gta_store(gta), gta, pre, run, "Heroic"))
    return found


def _lutris_installs() -> list[Install]:
    found: list[Install] = []
    for ld in _lutris_dirs():
        for f in sorted((ld / "games").glob("*.yml")):
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            m = re.search(r"^\s+prefix:\s*['\"]?([^'\"\n]+)", text, re.M)
            pre = wine_prefix(Path(m.group(1).strip()).expanduser()) if m else None
            if not pre:
                continue
            run = None
            v = re.search(r"^wine:\s*\n(?:\s+.*\n)*?\s+version:\s*['\"]?([^'\"\n]+)", text, re.M)
            if v:
                name = v.group(1).strip()
                for base in _lutris_dirs():
                    run = run or _runner_from_bin(str(base / "runners/wine" / name)) \
                        or _runner_from_bin(str(base / "runners/proton" / name))
            gtas = gta_in_prefix(pre)
            e = re.search(r"^\s+exe:\s*['\"]?([^'\"\n]+)", text, re.M)
            if e:
                exe = Path(e.group(1).strip()).expanduser()
                if not exe.is_absolute():
                    exe = pre / "drive_c" / exe
                if gta_edition(exe.parent) and exe.parent not in gtas:
                    gtas.insert(0, exe.parent)
            for gta in gtas:
                found.append(Install(gta_store(gta), gta, pre, run, "Lutris"))
    return found


def _bottles_installs() -> list[Install]:
    found: list[Install] = []
    for bd in _bottles_dirs():
        for b in sorted((bd / "bottles").glob("*")):
            pre = wine_prefix(b)
            if not pre:
                continue
            run = None
            try:
                m = re.search(r"^Runner:\s*['\"]?([^'\"\n]+)", (b / "bottle.yml").read_text(encoding="utf-8"), re.M)
            except OSError:
                m = None
            if m:
                run = _runner_from_bin(str(bd / "runners" / m.group(1).strip()))
            for gta in gta_in_prefix(pre):
                found.append(Install(gta_store(gta), gta, pre, run, "Bottles"))
    return found


def _loose_prefixes() -> list[Path]:
    h = _home()
    cands = [h / ".wine"]
    for base in (h / "Games", h / ".local/share/wineprefixes", h / "Games/Heroic/Prefixes",
                 h / "Games/Heroic/Prefixes/default"):
        if base.is_dir():
            cands += sorted(base.iterdir())
    return [p for p in (wine_prefix(c) for c in cands) if p]


def other_installs() -> list[Install]:
    """Все не-Steam копии GTA V: Heroic, Lutris, Bottles, обычные Wine-префиксы."""
    out: list[Install] = []
    for fn in (_heroic_installs, _lutris_installs, _bottles_installs):
        try:
            out += fn()
        except OSError:
            pass
    known = {i.prefix for i in out}
    for pre in _loose_prefixes():
        if pre not in known:
            out += [Install(gta_store(g), g, pre, None, "Wine") for g in gta_in_prefix(pre)]
    seen, res = set(), []
    for i in out:
        try:
            key = i.gta_path.resolve()
        except OSError:
            continue
        if key in seen:
            # та же игра без префикса (legendary) + с префиксом — оставляем полную запись
            j = next(x for x in res if x.gta_path.resolve() == key)
            j.prefix, j.runner = j.prefix or i.prefix, j.runner or i.runner
            continue
        seen.add(key)
        i.edition = gta_edition(i.gta_path) or "legacy"
        res.append(i)
    return res


def find_wines() -> list[Path]:
    """Proton из Heroic/Lutris и Wine-сборки, которые можно взять для не-Steam префикса."""
    out = []
    for hd in _heroic_dirs():
        out += sorted(d for d in (hd / "tools/proton").glob("*") if (d / "proton").is_file())
        out += sorted((hd / "tools/wine").glob("*/bin/wine"))
    for ld in _lutris_dirs():
        out += sorted(d for d in (ld / "runners/proton").glob("*") if (d / "proton").is_file())
        out += sorted((ld / "runners/wine").glob("*/bin/wine"))
    for bd in _bottles_dirs():
        out += sorted((bd / "runners").glob("*/bin/wine"))
    sys_wine = shutil.which("wine")
    if sys_wine:
        out.append(Path(sys_wine))
    return out


def runner_name(p: Path) -> str:
    if (p / "proton").is_file():
        return p.name
    if p.parent.name == "bin" and p.parent.parent.name not in ("usr", "local", ""):
        return f"Wine: {p.parent.parent.name}"
    return "Wine (системный)"


def store_launcher(pre: Path, store: str) -> Path | None:
    """Rockstar Games Launcher (для rgl и egs) или настоящий Epic Games Launcher (для egs) в префиксе."""
    c = pre / "drive_c"
    if store == "egs":
        names = ("Epic Games/Launcher/Portal/Binaries/Win64/EpicGamesLauncher.exe",
                 "Epic Games/Launcher/Portal/Binaries/Win32/EpicGamesLauncher.exe")
    else:
        names = ("Rockstar Games/Launcher/Launcher.exe",)
    for pf in ("Program Files (x86)", "Program Files"):
        for n in names:
            if (c / pf / n).is_file():
                return c / pf / n
    return None


def _steam_install(libs: list[Path]) -> tuple[Install | None, bool]:
    """(Steam-копия GTA V Legacy, стоит ли только Enhanced)."""
    for lib in libs:
        if (lib / f"appmanifest_{GTA_APPID}.acf").is_file():
            gta = lib / "common" / "Grand Theft Auto V"
            try:
                acf = (lib / f"appmanifest_{GTA_APPID}.acf").read_text(encoding="utf-8", errors="ignore")
                d = re.search(r'"installdir"\s+"([^"]+)"', acf)
                if d and (lib / "common" / d.group(1)).is_dir():
                    gta = lib / "common" / d.group(1)
            except OSError:
                pass
            return Install("steam", gta, None, None, "Steam"), False
    enhanced = any((lib / f"appmanifest_{GTA_ENHANCED_APPID}.acf").is_file() for lib in libs)
    return None, enhanced


def pick_install(cfg: dict, installs: list[Install]) -> Install | None:
    want = cfg.get("store") or "auto"
    if cfg.get("gta_path"):
        gta = Path(cfg["gta_path"]).expanduser()
        for i in installs:
            try:
                if i.gta_path.resolve() == gta.resolve():
                    return i
            except OSError:
                pass
        # папка, выбранная вручную: магазин по файлам, префикс — из настроек или тот, где она лежит
        pre = None
        for parent in gta.parents:
            if parent.name == "drive_c":
                pre = wine_prefix(parent.parent)
                break
        return Install(gta_store(gta), gta, pre, None, "вручную", gta_edition(gta) or "legacy")
    pool = [i for i in installs if want not in STORES or i.store == want]
    pool.sort(key=lambda i: i.edition != "legacy")  # Legacy вперёд: Enhanced RAGE:MP не умеет
    return pool[0] if pool else None


def detect(cfg: dict) -> Setup:
    if IS_WIN:
        return detect_windows(cfg)
    s = Setup()
    roots = steam_roots(cfg)
    libs = [lib for r in roots for lib in steam_libraries(r)]
    s.steam_root = roots[0] if roots else None

    steam, only_enhanced = _steam_install(libs)
    s.installs = ([steam] if steam else []) + other_installs()
    inst = pick_install(cfg, s.installs)
    for lib in libs:
        eac = lib / "common" / "Proton EasyAntiCheat Runtime"
        if eac.is_dir() and not s.eac_runtime:
            s.eac_runtime = eac
    s.protons = find_protons(roots, libs)

    if not inst:
        want = cfg.get("store") or "auto"
        if only_enhanced and want in ("auto", "steam"):
            s.problems.append("В Steam стоит только GTA V Enhanced, а RAGE:MP работает с GTA V Legacy. "
                              "Установите «Grand Theft Auto V Legacy» в Steam.")
        elif want in STORES:
            s.problems.append(f"GTA V из {STORES[want]} не найдена. Укажите её папку в настройках "
                              f"или выберите другой магазин.")
        else:
            s.problems.append("GTA V не найдена. Поддерживаются версии из Steam, Rockstar Games Launcher "
                              "и Epic Games Store — установите игру или укажите её папку в настройках.")
        s.protons += [w for w in find_wines() if w not in s.protons]
        return s

    s.store, s.source, s.edition, s.gta_path = inst.store, inst.source, inst.edition, inst.gta_path
    if not (s.gta_path / "GTA5.exe").is_file():
        if inst.edition == "enhanced":
            s.problems.append("Это GTA V Enhanced, а RAGE:MP работает только с GTA V Legacy. "
                              f"Установите Legacy-версию в {STORES[s.store]}.")
        else:
            s.problems.append(f"В папке {s.gta_path} нет GTA5.exe.")
    if s.store == "steam":
        _detect_steam(cfg, s, roots, libs)
    else:
        _detect_wine(cfg, s, inst)
    return s


def _detect_steam(cfg: dict, s: Setup, roots: list[Path], libs: list[Path]) -> None:
    if not roots:
        s.problems.append("Steam не найден. Steam-версии GTA V нужен Steam.")
        return
    for lib in libs:
        if (lib / f"appmanifest_{GTA_APPID}.acf").is_file():
            s.steamapps = lib
            break
    for lib in libs:
        cd = lib / "compatdata" / GTA_APPID
        if (cd / "pfx").is_dir():
            s.compatdata = cd
            break
    if not s.compatdata:
        s.problems.append("Нет Proton-префикса GTA V. Включите Proton для GTA V в Steam "
                          "(Свойства → Совместимость) и запустите игру из Steam один раз.")
    if cfg.get("proton") and (Path(cfg["proton"]) / "proton").is_file():
        s.proton = Path(cfg["proton"])
    elif s.protons:
        official = [p for p in s.protons if "compatibilitytools.d" not in str(p)]
        s.proton = max(official or s.protons, key=_proton_version_key)
    if not s.proton:
        s.problems.append("Proton не найден. Установите «Proton Experimental» в Steam.")
    s.runtime_entry = find_runtime(s.proton, libs) if s.proton else None


def _detect_wine(cfg: dict, s: Setup, inst: Install) -> None:
    """Rockstar / Epic: свой Wine-префикс, Proton или Wine вне Steam."""
    s.protons += [w for w in find_wines() if w not in s.protons]
    pre = wine_prefix(Path(cfg["prefix"]).expanduser()) if cfg.get("prefix") else None
    pre = pre or inst.prefix
    if not pre:
        s.problems.append(f"Не знаю, в каком Wine-префиксе стоит {STORES[s.store]}. "
                          "Укажите папку префикса в настройках (ту, где лежит drive_c).")
        return
    s.prefix, s.compatdata = pre, compat_dir(pre)
    chosen = Path(cfg["proton"]) if cfg.get("proton") else None
    if chosen and ((chosen / "proton").is_file() or chosen.is_file()):
        run = chosen
    else:
        run = inst.runner or next((p for p in s.protons if (p / "proton").is_file()), None) \
            or (s.protons[-1] if s.protons else None)
    if run and (run / "proton").is_file():
        s.proton = run
    elif run:
        s.wine = run
    else:
        s.problems.append("Не найден ни Proton, ни Wine. Поставьте GE-Proton (например, через Heroic "
                          "или ProtonUp-Qt) или пакет wine.")
    if run and run not in s.protons:
        s.protons.append(run)
    s.store_launcher = store_launcher(pre, s.store)
    if not store_launcher(pre, "rgl"):
        s.problems.append("В префиксе нет Rockstar Games Launcher — без него GTA V не стартует. "
                          "Нажмите «Установить Rockstar Games Launcher» в настройках.")
    if s.store == "egs" and not s.store_launcher:
        s.problems.append("Epic-версии GTA V нужен настоящий Epic Games Launcher в том же префиксе "
                          "(заглушки Heroic не хватает). Нажмите «Установить Epic Games Launcher» в настройках.")


def steam_running() -> bool:
    if IS_WIN:
        return "steam.exe" in _win_tasks()
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
    token = _check_launch_args(host, port, token)
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
    if s.store != "steam" or s.wine:
        return _wine_command(s, args, debug)
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


def _wine_command(s: Setup, args: list[str], debug: bool = False) -> tuple[list[str], dict]:
    """Rockstar / Epic: Proton как у Heroic/umu (без Steam и без его контейнера) или обычный Wine."""
    env = dict(os.environ)
    for k in ("SteamAppId", "SteamGameId", "SteamOverlayGameId", "SteamEnv", "SteamClientLaunch"):
        env.pop(k, None)
    if s.wine:
        env["WINEPREFIX"] = str(s.pfx)
        if debug:
            env["WINEDEBUG"] = "+seh,+loaddll,err+all,warn+all"
        else:
            env.setdefault("WINEDEBUG", "-all")
        return [str(s.wine), *args], env
    env.update({
        "STEAM_COMPAT_DATA_PATH": str(s.compatdata),
        "STEAM_COMPAT_CLIENT_INSTALL_PATH": str(s.steam_root or ""),
        "STEAM_COMPAT_INSTALL_PATH": str(s.gta_path),
        # 0 — «не Steam-игра»; SteamAppId нужен ProtonFixes (GE-Proton), иначе он падает
        "STEAM_COMPAT_APP_ID": "0", "SteamAppId": "0", "SteamGameId": "0",
    })
    if s.eac_runtime:
        env["PROTON_EAC_RUNTIME"] = str(s.eac_runtime)
    if debug:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        env["PROTON_LOG"] = "1"
        env["PROTON_LOG_DIR"] = str(STATE_DIR)
    return [str(s.proton / "proton"), "waitforexitandrun", *args], env


def prepare_prefix(s: Setup) -> None:
    """Чтобы Proton принял префикс Lutris/Bottles/Wine как свой — то же, что делает umu-launcher."""
    if s.store == "steam" or s.wine or not s.prefix:
        return
    cd = s.compatdata
    if s.prefix == cd and not (cd / "pfx").exists():
        (cd / "pfx").symlink_to(cd)
    users = s.prefix / "drive_c" / "users"
    me = os.environ.get("USER") or Path.home().name
    if (users / me).is_dir() and not (users / "steamuser").exists():
        (users / "steamuser").symlink_to(me)


def to_win(s: Setup, path: Path) -> str:
    return "C:\\" + str(path.relative_to(s.pfx / "drive_c")).replace("/", "\\")


def store_launcher_installer(s: Setup, which: str, progress=None) -> tuple[list[str], dict, str]:
    """Скачать и запустить установщик Rockstar Games Launcher (rgl) или Epic Games Launcher (egs)
    в префиксе игры. Возвращает (cmd, env, cwd)."""
    if not s.pfx:
        raise RuntimeError("Нет Wine-префикса — сначала укажите его в настройках")
    url, name = (RGL_INSTALLER_URL, "Rockstar-Games-Launcher.exe") if which == "rgl" \
        else (EGL_INSTALLER_URL, "EpicGamesLauncherInstaller.msi")
    d = s.pfx / "drive_c" / "Games" / "GTA5RP" / "installers"
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    if not f.is_file() or f.stat().st_size < 1_000_000:
        if progress:
            progress(f"Скачиваю {name}…")
        data = http_get(url, timeout=300)
        if len(data) < 1_000_000:
            raise RuntimeError(f"{name}: скачался подозрительно маленький файл")
        tmp = f.with_suffix(".part")
        tmp.write_bytes(data)
        os.replace(tmp, f)
    prepare_prefix(s)
    # exe-установщик Epic в Wine падает на проверке подписи — ставим MSI напрямую
    args = ["msiexec", "/i", to_win(s, f)] if name.endswith(".msi") else [to_win(s, f)]
    cmd, env = proton_command(s, args)
    return cmd, env, str(d)


def open_store_launcher(s: Setup) -> tuple[list[str], dict, str]:
    if not s.store_launcher:
        raise RuntimeError("Лаунчер магазина не установлен в префикс")
    prepare_prefix(s)
    cmd, env = proton_command(s, [to_win(s, s.store_launcher)])
    return cmd, env, str(s.store_launcher.parent)


def _check_launch_args(host: str, port: int, token: str) -> str:
    if not _SAFE_HOST.match(host) or not (0 < int(port) < 65536):
        raise ValueError(f"Странный адрес сервера: {host}:{port}")
    token = token.strip()
    if not token or any(ord(ch) < 32 for ch in token):
        raise ValueError("Сервер выдал пустой или повреждённый игровой токен")
    return token


def prepare_launch_windows(s: Setup, host: str, port: int, token: str, progress=None):
    """Windows: ровно то, что делает GTA5RPLauncher.exe, только открытым кодом."""
    import winreg
    token = _check_launch_args(host, port, token)
    ensure_updater(s.rage_dir, progress)
    for sub in ("clientdata", "EasyAntiCheat"):
        (s.rage_dir / sub).mkdir(exist_ok=True)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\RAGE-MP") as k:
        winreg.SetValueEx(k, "launch2.ip", 0, winreg.REG_SZ, host)
        winreg.SetValueEx(k, "launch2.port", 0, winreg.REG_SZ, str(int(port)))
        winreg.SetValueEx(k, "launch2.params", 0, winreg.REG_SZ, token)
    return [str(s.rage_dir / "updater.exe")], dict(os.environ), str(s.rage_dir)


def prepare_launch(s: Setup, host: str, port: int, token: str, progress=None, debug=False):
    """Всё, что делает GTA5RPLauncher.exe перед стартом. Возвращает (cmd, env, cwd)."""
    if IS_WIN:
        return prepare_launch_windows(s, host, port, token, progress)
    if not s.ok:
        raise RuntimeError("\n".join(s.problems))
    ensure_updater(s.rage_dir, progress)
    for sub in ("clientdata", "EasyAntiCheat"):
        (s.rage_dir / sub).mkdir(exist_ok=True)
    prepare_prefix(s)
    map_gta_drive(s.pfx, s.gta_path)
    reg = write_launch_reg(s, host, port, token)
    win_reg = to_win(s, reg)
    # 1) regedit /S — оконное приложение, без консоли; 2) удалить .reg с токеном; 3) updater.exe
    step1, env = proton_command(s, ["regedit.exe", "/S", win_reg], debug)
    step3, _ = proton_command(s, [f"{RAGE_WIN_DIR}\\updater.exe"], debug)
    script = f"{shlex.join(step1)}; rm -f {shlex.quote(str(reg))}; exec {shlex.join(step3)}"
    return ["/bin/sh", "-c", script], env, str(s.rage_dir)


GAME_PROCS = ("GTA5.exe", "PlayGTAV.exe", "GTA5_BE.exe", "ragemp_v.exe", "updater.exe", "ragemp_game_ui.exe")


def _win_tasks() -> str:
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.lower()


def running_game_procs() -> list[str]:
    if IS_WIN:
        tasks = _win_tasks()
        return [p for p in GAME_PROCS if f'"{p.lower()}"' in tasks]
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
    """Аварийно закрыть игру (Linux — весь префикс GTA V, Windows — процессы RAGE:MP и GTA V)."""
    if IS_WIN:
        for p in GAME_PROCS:
            subprocess.run(["taskkill", "/F", "/IM", p], capture_output=True, timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return
    if not (s.runner and s.pfx):
        return
    ws = None
    cands = [s.wine.parent / "wineserver"] if s.wine else \
        [s.proton / "files/bin/wineserver", s.proton / "dist/bin/wineserver"]
    for cand in cands:
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

