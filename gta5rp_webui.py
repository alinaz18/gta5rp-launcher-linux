"""Оригинальный интерфейс GTA5RP внутри Qt WebEngine + наше ядро вместо GTA5RPLauncher.exe.

Интерфейс общается с ядром по двум WebSocket (core и status) сообщениями вида
{"message_id": N, "data": {...}, "is_waiting_response": bool} — здесь они обслуживаются
на Python, а «Играть» запускает RAGE:MP через Proton (gta5rp_core.prepare_launch).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from PySide6.QtCore import QFile, QIODevice, QObject, QProcess, QProcessEnvironment, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QDesktopServices, QImage
from PySide6.QtNetwork import QHostAddress
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineScript, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebSockets import QWebSocketServer

import gta5rp_core as core
import gta5rp_official as official

MSG_START_GAME, MSG_SET_CACHE, MSG_GET_CACHE = 2, 3, 4
MSG_UPDATE_LAUNCHER, MSG_GET_CONFIG, MSG_SET_CONFIG = 6, 7, 8
MSG_GET_VERSION, MSG_GET_TOKEN, MSG_SET_TOKEN = 9, 10, 11
MSG_PING, MSG_PROGRESS = 1, 666

# rage_state из интерфейса: 0 не установлен, 1 установлен, 2 загрузка файлов, 3 загрузка мультиплеера,
# 4 запуск, 5 запущен, 6 не запущен, 7 закрыт; game_state: 0 не запущена, 1 запущена, 2 закрыта
CACHE_FILE = core.CONFIG_DIR / "webui-cache.json"
WEB_PROFILE_DIR = official.DATA_DIR / "web"
EXTRA_DIR = Path(__file__).resolve().parent / "webui"


def cached_image(url: str):
    import hashlib
    path = core.CACHE_DIR / "img" / hashlib.sha1(url.encode()).hexdigest()
    if not path.is_file():
        try:
            data = core.http_get(url, timeout=10)
        except Exception:  # noqa: BLE001
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    img = QImage(str(path))
    return None if img.isNull() else img


def _qrc_text(path: str) -> str:
    f = QFile(path)
    if not f.open(QIODevice.ReadOnly):
        return ""
    return bytes(f.readAll()).decode()


class Store:
    """GET/SET_CACHE и SET_TOKEN официального ядра (в оригинале — реестр Windows)."""

    def __init__(self):
        try:
            self.data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}
        self.data.setdefault("cache", {})
        self.data.setdefault("config", {"hardware_acceleration": "1", "connection_type": "0"})
        self.data.setdefault("token", "")

    def save(self):
        core.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_FILE.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # тут токен сессии
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False)
        os.replace(tmp, CACHE_FILE)


class CoreBackend(QObject):
    """Два WebSocket-сервера на 127.0.0.1, как мост ecef_process ↔ GTA5RPLauncher.exe."""

    log = Signal(str)
    launched = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.store = Store()
        self.status = {"game_state": 0, "launcher_state": 1, "rage_state": 1}
        self.status_clients = []
        self.proc: QProcess | None = None
        self.core = self._server("core", self._on_core)
        self.stat = self._server("status", self._on_status)
        self.setup = core.detect(core.load_config())
        self._refresh_installed()
        self.poll = QTimer(self, interval=2000, timeout=self._poll_game)
        self.poll.start()

    # ---------- серверы
    def _server(self, name, handler):
        srv = QWebSocketServer(f"gta5rp-{name}", QWebSocketServer.NonSecureMode, self)
        if not srv.listen(QHostAddress.LocalHost, 0):
            raise RuntimeError(f"Не удалось открыть порт для {name}")

        def on_new():
            while srv.hasPendingConnections():
                ws = srv.nextPendingConnection()
                origin = ws.origin()
                if origin not in ("", "null", "file://"):
                    ws.close()
                    continue
                ws.textMessageReceived.connect(lambda m, ws=ws: handler(ws, m))
                ws.binaryMessageReceived.connect(lambda m, ws=ws: handler(ws, bytes(m).decode(errors="replace")))
                if name == "status":
                    self.status_clients.append(ws)
                    ws.disconnected.connect(lambda ws=ws: self.status_clients.remove(ws)
                                            if ws in self.status_clients else None)
        srv.newConnection.connect(on_new)
        return srv

    def url(self, which: str) -> str:
        srv = self.core if which == "core" else self.stat
        return f"ws://127.0.0.1:{srv.serverPort()}/"

    # ---------- статус
    def _status_msg(self) -> str:
        return json.dumps({"data": dict(self.status), "success": True})

    def set_status(self, **kw):
        changed = any(self.status.get(k) != v for k, v in kw.items())
        self.status.update(kw)
        if changed:
            msg = self._status_msg()
            for ws in list(self.status_clients):
                ws.sendTextMessage(msg)

    def _refresh_installed(self):
        rd = self.setup.rage_dir
        installed = bool(rd and (rd / "updater.exe").is_file())
        if self.status["rage_state"] in (0, 1, 6, 7):
            self.status["rage_state"] = 1 if installed else 0

    def _on_status(self, ws, text):
        try:
            msg = json.loads(text)
        except ValueError:
            return
        if msg.get("message_id") in (MSG_PROGRESS, MSG_PING):
            ws.sendTextMessage(self._status_msg())

    # ---------- core
    def _on_core(self, ws, text):
        try:
            msg = json.loads(text)
        except ValueError:
            return
        mid = msg.get("message_id")
        data = msg.get("data") or {}
        wait = msg.get("is_waiting_response", True)
        reply = None
        st = self.store
        if mid == MSG_GET_VERSION:
            reply = core.OFFICIAL_VERSION
        elif mid == MSG_GET_CONFIG:
            key = str(data.get("key", ""))
            val = core.RAGE_WIN_DIR if key == "rage_install_path" else st.data["config"].get(key, "")
            reply = json.dumps({"key": key, "success": True, "value": val})
        elif mid == MSG_SET_CONFIG:
            if data.get("key") != "rage_install_path":
                st.data["config"][str(data.get("key"))] = str(data.get("value", ""))
                st.save()
        elif mid == MSG_GET_CACHE:
            key = str(data.get("key", ""))
            reply = json.dumps({"key": key, "success": True, "value": st.data["cache"].get(key, "")})
        elif mid == MSG_SET_CACHE:
            v = data.get("value", "")
            st.data["cache"][str(data.get("key"))] = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
            st.save()
        elif mid == MSG_GET_TOKEN:
            reply = json.dumps({"token": st.data.get("token", "")})
        elif mid == MSG_SET_TOKEN:
            st.data["token"] = str(data.get("token", ""))
            st.save()
        elif mid == MSG_START_GAME:
            self.start_game(str(data.get("host", "")), int(data.get("port") or 22005), str(data.get("token", "")))
        elif mid == MSG_UPDATE_LAUNCHER:
            self.log.emit("Интерфейс предложил обновить официальный лаунчер — скачайте новый установщик "
                          "с gta5rp.com, этот лаунчер подхватит его интерфейс сам.")
        if wait:
            ws.sendTextMessage(reply if reply is not None else json.dumps({"success": True}))

    # ---------- запуск игры
    def start_game(self, host: str, port: int, token: str):
        if self.proc and self.proc.state() != QProcess.NotRunning:
            self.log.emit("Игра уже запускается")
            return
        if not token:
            self.log.emit("Интерфейс не передал игровой токен — войдите в аккаунт")
            self.set_status(rage_state=6)
            return
        cfg = core.load_config()
        self.setup = core.detect(cfg)
        if not self.setup.ok:
            self.log.emit("\n".join(self.setup.problems))
            self.set_status(rage_state=100)
            return
        self.set_status(rage_state=3, game_state=0)
        from concurrent.futures import ThreadPoolExecutor
        pool = getattr(self, "_pool", None) or ThreadPoolExecutor(max_workers=1)
        self._pool = pool
        fut = pool.submit(core.prepare_launch, self.setup, host, port, token, None, bool(cfg.get("debug_log")))

        def check():
            if not fut.done():
                QTimer.singleShot(200, check)
                return
            try:
                cmd, env, cwd = fut.result()
            except Exception as e:  # noqa: BLE001
                self.log.emit(f"Ошибка запуска: {e}")
                self.set_status(rage_state=100)
                return
            self._spawn(cmd, env, cwd)
        check()

    def _spawn(self, cmd, env, cwd):
        self.set_status(rage_state=4)
        self.proc = QProcess(self)
        qenv = QProcessEnvironment()
        for k, v in env.items():
            qenv.insert(k, v)
        self.proc.setProcessEnvironment(qenv)
        self.proc.setWorkingDirectory(cwd)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyRead.connect(lambda: self.log.emit(bytes(self.proc.readAll()).decode(errors="replace")))
        self.proc.finished.connect(self._finished)
        self.proc.start(cmd[0], cmd[1:])
        if core.load_config().get("close_on_play"):
            QTimer.singleShot(8000, self.launched.emit)

    def _finished(self, code, _st):
        self.log.emit(f"RAGE:MP завершился (код {code})")
        self.set_status(rage_state=7, game_state=2 if self.status["game_state"] == 1 else 0)
        self._refresh_installed()

    def _poll_game(self):
        if not (self.proc and self.proc.state() != QProcess.NotRunning):
            return
        procs = core.running_game_procs()
        if "GTA5.exe" in procs:
            self.set_status(rage_state=5, game_state=1)
        elif "ragemp_v.exe" in procs:
            self.set_status(rage_state=5)
        elif "updater.exe" in procs:
            self.set_status(rage_state=2)


class Bridge(QObject):
    """window.api из preload.js оригинала."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win

    @Slot()
    def rendererReady(self):
        self.win.renderer_ready()

    @Slot()
    def minimize(self):
        self.win.showMinimized()

    @Slot()
    def close(self):
        self.win.close()

    @Slot()
    def startDrag(self):
        h = self.win.windowHandle()
        if h:
            h.startSystemMove()

    @Slot(str)
    def openExternal(self, url):
        if url.startswith(("https://", "http://")):
            QDesktopServices.openUrl(QUrl(url))

    @Slot(str)
    def openFolder(self, path):
        s = core.detect(core.load_config())
        p = None
        if path[:3].lower() == "c:\\" and s.pfx:
            p = s.pfx / "drive_c" / Path(*path[3:].split("\\"))
        if p and p.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    @Slot(result=bool)
    def checkOnline(self):
        return True

    # ---------- Linux-настройки (панель из enhance.js)
    def _state(self) -> str:
        cfg = core.load_config()
        s = core.detect(cfg)
        self.win.backend.setup = s
        rd = s.rage_dir
        rage_ok = bool(rd and (rd / "updater.exe").is_file())
        rage = {"name": "RAGE:MP", "ok": rage_ok, "hint": "установлен" if rage_ok else "скачается при запуске"}
        steam_on = core.steam_running()
        if core.IS_WIN:
            checks = [rage,
                      {"name": "Папка RAGE:MP", "ok": True, "hint": str(rd)},
                      {"name": "Steam", "ok": steam_on, "hint": "запущен" if steam_on else "не запущен (нужен для Steam-версии GTA V)"}]
            chips = [["RAGE:MP", rage_ok], ["Steam", steam_on], ["Windows", True], ["Ядро", True]]
        elif s.store == "steam" or not s.gta_path:
            checks = [
                {"name": "GTA V", "ok": bool(s.gta_path and (s.gta_path / "GTA5.exe").is_file()),
                 "hint": "Steam" if s.gta_path else "не найдена"},
                {"name": "Steam", "ok": bool(s.steam_root) and steam_on,
                 "hint": "запущен" if steam_on else ("не запущен" if s.steam_root else "не найден")},
                {"name": "Префикс Proton", "ok": bool(s.compatdata), "hint": "compatdata/271590"},
                {"name": "Steam Linux Runtime", "ok": bool(s.runtime_entry),
                 "hint": s.runtime_entry.parent.name if s.runtime_entry else "нет"},
                {"name": "EasyAntiCheat Runtime", "ok": bool(s.eac_runtime),
                 "hint": "установлен" if s.eac_runtime else "нужен для античита"},
                rage,
            ]
            chips = [["Steam", checks[1]["ok"]], ["Proton", bool(s.proton) and bool(s.compatdata)],
                     ["Античит", bool(s.eac_runtime)], ["RAGE:MP", rage_ok]]
        else:
            rgl = bool(s.pfx and core.store_launcher(s.pfx, "rgl"))
            checks = [
                {"name": "GTA V", "ok": bool((s.gta_path / "GTA5.exe").is_file()),
                 "hint": f"{core.STORES[s.store]}" + (f" · {s.source}" if s.source else "")},
                {"name": "Wine-префикс", "ok": bool(s.pfx), "hint": s.pfx.name if s.pfx else "не найден"},
                {"name": "Proton / Wine", "ok": bool(s.runner),
                 "hint": core.runner_name(s.runner) if s.runner else "не найден"},
                {"name": "Rockstar Games Launcher", "ok": rgl, "hint": "в префиксе" if rgl else "не установлен"},
            ]
            if s.store == "egs":
                checks.append({"name": "Epic Games Launcher", "ok": bool(s.store_launcher),
                               "hint": "в префиксе" if s.store_launcher else "не установлен"})
            checks += [{"name": "EasyAntiCheat Runtime", "ok": bool(s.eac_runtime),
                        "hint": "установлен" if s.eac_runtime else ("нужен для античита" if s.steam_root
                                                                    else "ставится через Steam, не обязателен")},
                       rage]
            chips = [[core.STORE_SHORT[s.store], bool(s.gta_path) and bool(s.pfx)],
                     ["Wine" if s.wine else "Proton", bool(s.runner)],
                     ["Лаунчер", rgl and (s.store != "egs" or bool(s.store_launcher))], ["RAGE:MP", rage_ok]]
        need = ""
        if s.store in ("rgl", "egs") and s.pfx and s.runner:
            if not core.store_launcher(s.pfx, "rgl"):
                need = "rgl"
            elif s.store == "egs" and not s.store_launcher:
                need = "egs"
        found = {}
        for i in s.installs:
            found.setdefault(i.store, f"{i.source}" + (" · Enhanced" if i.edition == "enhanced" else ""))
        return json.dumps({
            "platform": "win" if core.IS_WIN else "linux",
            "protons": [{"name": core.runner_name(p), "path": str(p)} for p in s.protons],
            "proton": str(s.runner or ""),
            "gta_path": str(s.gta_path or ""),
            "store": cfg.get("store") or "auto", "store_now": s.store if s.gta_path else "",
            "stores": [{"id": k, "name": v, "found": found.get(k, "")} for k, v in core.STORES.items()],
            "prefix": str(s.pfx or "") if s.store != "steam" else "",
            "need_launcher": need,
            "can_open_egl": s.store == "egs" and bool(s.store_launcher),
            "close_on_play": bool(cfg.get("close_on_play")),
            "debug_log": bool(cfg.get("debug_log")),
            "problems": s.problems,
            "checks": checks,
            "chips": chips,
            "version": core.VERSION, "official": official.installed_info().get("version", ""),
        }, ensure_ascii=False)

    @Slot(result=str)
    def linuxState(self):
        return self._state()

    @Slot(str, str, result=str)
    def setLinux(self, key, value_json):
        cfg = core.load_config()
        value = json.loads(value_json)
        if key == "proton" and (not value or (Path(value) / "proton").is_file() or Path(value).is_file()):
            cfg["proton"] = value
        elif key == "store" and value in ("auto", *core.STORES):
            cfg["store"] = value
            cfg["gta_path"] = cfg["prefix"] = ""  # папку и префикс ищем заново под новый магазин
        elif key == "prefix" and value == "":
            cfg["prefix"] = ""
        elif key in ("close_on_play", "debug_log"):
            cfg[key] = bool(value)
        elif key == "gta_path" and value == "":
            cfg["gta_path"] = ""
        core.save_config(cfg)
        return self._state()

    @Slot(result=str)
    def pickGtaPath(self):
        from PySide6.QtWidgets import QFileDialog
        cur = core.detect(core.load_config()).gta_path
        d = QFileDialog.getExistingDirectory(self.win, "Папка Grand Theft Auto V", str(cur or Path.home()))
        if d and (Path(d) / "GTA5.exe").is_file():
            cfg = core.load_config()
            cfg["gta_path"] = d
            cfg["prefix"] = ""
            cfg["store"] = core.gta_store(Path(d))
            core.save_config(cfg)
        return self._state()

    @Slot(result=str)
    def pickPrefix(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        cur = core.detect(core.load_config()).pfx
        d = QFileDialog.getExistingDirectory(self.win, "Wine-префикс с GTA V (папка, где лежит drive_c)",
                                             str(cur or Path.home()))
        if d:
            if core.wine_prefix(Path(d)):
                cfg = core.load_config()
                cfg["prefix"] = d
                core.save_config(cfg)
            else:
                QMessageBox.warning(self.win, "GTA5RP", "В этой папке нет drive_c — это не Wine-префикс.")
        return self._state()

    def _run_in_prefix(self, make, what: str):
        """Скачать/запустить что-то в префиксе игры в фоне, не блокируя окно."""
        import threading
        backend = self.win.backend

        def work():
            try:
                cmd, env, cwd = make(lambda m: backend.log.emit(m))
                backend.log.emit(f"{what}: запускаю…")
                subprocess.Popen(cmd, env=env, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
            except Exception as e:  # noqa: BLE001
                backend.log.emit(f"{what}: ошибка — {e}")
        threading.Thread(target=work, daemon=True).start()

    @Slot(str)
    def installStoreLauncher(self, which):
        if which not in ("rgl", "egs"):
            return
        s = core.detect(core.load_config())
        name = "Rockstar Games Launcher" if which == "rgl" else "Epic Games Launcher"
        self._run_in_prefix(lambda pr: core.store_launcher_installer(s, which, pr), f"Установка {name}")

    @Slot()
    def openStoreLauncher(self):
        s = core.detect(core.load_config())
        self._run_in_prefix(lambda pr: core.open_store_launcher(s), "Epic Games Launcher")

    @Slot()
    def installEac(self):
        QDesktopServices.openUrl(QUrl(f"steam://install/{core.EAC_RUNTIME_APPID}"))

    @Slot()
    def openRage(self):
        rd = core.detect(core.load_config()).rage_dir
        if rd:
            rd.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(rd)))

    @Slot()
    def killGame(self):
        core.kill_prefix(core.detect(core.load_config()))

    @Slot()
    def openLogs(self):
        core.STATE_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(core.STATE_DIR)))

    @Slot()
    def restartClassic(self):
        import sys
        QProcess.startDetached(sys.executable, [str(Path(__file__).resolve().parent / "gta5rp_launcher.py"), "--classic"])
        self.win.close()

    @Slot(str, result=str)
    def serverTheme(self, url):
        """Цвет темы сервера: средний цвет его картинки, насыщенный и посветлее."""
        if not url.startswith(("https://gta5rp.com/sidback/", "https://test.gta5rp.com/sidback/")):
            return ""
        img = cached_image(url)
        if img is None:
            return ""
        c = QColor(img.scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).pixel(0, 0))
        h, s, v, _ = c.getHsvF()
        c.setHsvF(max(h, 0.0), min(1.0, max(s * 1.6, 0.55)), 0.95)
        return c.name()


SHIM = r"""
(() => {
  const ready = new Promise(res => {
    const init = () => new QWebChannel(qt.webChannelTransport, ch => res(ch.objects.bridge));
    if (window.qt && qt.webChannelTransport) init(); else document.addEventListener('DOMContentLoaded', init);
  });
  const call = (name, ...args) => ready.then(b => new Promise(r => b[name](...args, r)));
  window.api = Object.freeze({
    coreUrl: "@CORE@", statusUrl: "@STATUS@",
    rendererReady: () => { call('rendererReady'); },
    minimize: () => { call('minimize'); },
    close: () => { call('close'); },
    openExternalLink: (o) => call('openExternal', (o && o.url) || String(o)),
    openFolder: (o) => { call('openFolder', (o && o.path) || ''); },
    openRageFolder: () => Promise.resolve({ success: false, canceled: true }),
    checkOnline: () => call('checkOnline'),
  });
  window.__rpTheme = (url) => call('serverTheme', url);
  window.__rp = (name, ...args) => call(name, ...args);
  window.__rpAssets = "@ASSETS@";
  // окно без рамки: тянем за элементы .draggable (в Electron это -webkit-app-region: drag)
  document.addEventListener('mousedown', (e) => {
    if (e.button !== 0 || !(e.target instanceof Element)) return;
    if (e.target.closest('.draggable_lock,a,input,button,iframe,select,textarea,[role=button]')) return;
    if (e.target.closest('.draggable')) { e.preventDefault(); call('startDrag'); }
  }, true);
})();
"""


class Page(QWebEnginePage):
    def __init__(self, profile, parent):
        super().__init__(profile, parent)

    def acceptNavigationRequest(self, url, nav_type, is_main):
        # внешние ссылки — в браузер, само окно остаётся на локальном интерфейсе
        if is_main and url.scheme() in ("http", "https"):
            QDesktopServices.openUrl(url)
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main)

    def createWindow(self, _type):
        page = QWebEnginePage(self.profile(), self)
        page.urlChanged.connect(lambda u, p=page: (QDesktopServices.openUrl(u), p.deleteLater()))
        return page


class WebWindow(QWebEngineView):
    def __init__(self, on_log=None):
        super().__init__()
        self.backend = CoreBackend(self)
        if on_log:
            self.backend.log.connect(on_log)
        self.backend.launched.connect(self.showMinimized)
        self.setWindowTitle("GTA5RP Launcher")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setFixedSize(1200, 770)
        self.setAttribute(Qt.WA_DeleteOnClose)

        WEB_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        profile = QWebEngineProfile("gta5rp", self)
        profile.setPersistentStoragePath(str(WEB_PROFILE_DIR / "storage"))
        profile.setCachePath(str(core.CACHE_DIR / "web"))
        profile.setHttpUserAgent(core.UA)
        page = Page(profile, self)
        s = page.settings()
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        s.setAttribute(QWebEngineSettings.JavascriptCanOpenWindows, True)

        self.channel = QWebChannel(page)
        self.channel.registerObject("bridge", Bridge(self))
        page.setWebChannel(self.channel)
        shim = SHIM.replace("@CORE@", self.backend.url("core")).replace("@STATUS@", self.backend.url("status")).replace("@ASSETS@", QUrl.fromLocalFile(str(EXTRA_DIR)).toString())
        self._add_script(page, "qwebchannel", _qrc_text(":/qtwebchannel/qwebchannel.js"))
        self._add_script(page, "gta5rp-shim", shim)
        for extra in ("enhance.css", "enhance.js"):
            p = EXTRA_DIR / extra
            if p.is_file():
                src = p.read_text(encoding="utf-8")
                if extra.endswith(".css"):
                    src = "(()=>{const s=document.createElement('style');s.textContent=%s;" \
                          "(document.head||document.documentElement).appendChild(s);})();" % json.dumps(src)
                self._add_script(page, extra, src, QWebEngineScript.DocumentReady)
        self.setPage(page)
        self.setContextMenuPolicy(Qt.NoContextMenu)
        self.page().setBackgroundColor(Qt.black)

        url = QUrl.fromLocalFile(str(official.index_html()))
        url.setFragment("/")
        self.load(url)
        self._shown = False
        QTimer.singleShot(6000, self.renderer_ready)  # если интерфейс не сообщил о готовности

    @staticmethod
    def _add_script(page, name, source, point=QWebEngineScript.DocumentCreation):
        sc = QWebEngineScript()
        sc.setName(name)
        sc.setSourceCode(source)
        sc.setInjectionPoint(point)
        sc.setWorldId(QWebEngineScript.MainWorld)
        sc.setRunsOnSubFrames(False)
        page.scripts().insert(sc)

    def renderer_ready(self):
        if not self._shown:
            self._shown = True
            self.show()
