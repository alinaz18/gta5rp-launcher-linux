#!/usr/bin/env python3
"""GTA5RP Launcher for Linux — неофициальный нативный лаунчер GTA5RP (RAGE:MP).

Интерфейс на Qt (PySide6). Вход, список серверов и новости — через тот же API,
что и в официальном лаунчере; RAGE:MP и GTA V запускаются через Proton из Steam.
"""

import hashlib
import re
import shutil
import time
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import PySide6  # noqa: F401
except ImportError:
    _msg = "Не установлен PySide6. Выполните ./install.sh или: pip install --user PySide6"
    print(_msg, file=sys.stderr)
    if shutil.which("kdialog"):
        subprocess.run(["kdialog", "--error", _msg])
    sys.exit(1)

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QFrame,
    QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSplitter, QTabWidget, QTextBrowser,
    QVBoxLayout, QWidget,
)

import gta5rp_core as core

APP_NAME = "GTA5RP Launcher for Linux"
POOL = ThreadPoolExecutor(max_workers=6)
ACCENT = "#ff3b5c"

STYLE = f"""
QWidget {{ font-size: 10.5pt; color: #e6e6e6; }}
QMainWindow, QDialog, QWidget#central {{ background: #141519; }}
QLabel[muted="true"] {{ color: #8b8f99; }}
QLabel#title {{ font-size: 15pt; font-weight: 800; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: #8b8f99; padding: 10px 18px; border: none;
               border-bottom: 2px solid transparent; font-weight: 600; }}
QTabBar::tab:selected {{ color: #fff; border-bottom: 2px solid {ACCENT}; }}
QLineEdit, QComboBox {{ background: #1e2027; border: 1px solid #2c2f38; border-radius: 6px; padding: 7px 9px; }}
QLineEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{ background: #1e2027; selection-background-color: {ACCENT}; }}
QPushButton {{ background: #23262e; border: 1px solid #30343e; border-radius: 6px; padding: 7px 14px; }}
QPushButton:hover {{ background: #2b2f39; }}
QPushButton:disabled {{ color: #666; }}
QPushButton#play {{ background: {ACCENT}; color: #fff; font-size: 13pt; font-weight: 800; border: none;
               padding: 10px 34px; border-radius: 8px; min-width: 160px; }}
QPushButton#play:hover {{ background: #ff5573; }}
QPushButton#play:disabled {{ background: #3a3d46; color: #999; }}
QProgressBar {{ background: #1e2027; border: none; border-radius: 3px; max-height: 6px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
QListWidget, QTextBrowser, QPlainTextEdit {{ background: #191b21; border: 1px solid #23262e; border-radius: 8px; }}
QListWidget::item {{ padding: 8px; border-bottom: 1px solid #202329; }}
QListWidget::item:selected {{ background: #2a1d22; color: #fff; }}
QScrollArea {{ border: none; background: transparent; }}
QFrame#card {{ background: #1b1d23; border: 2px solid #23262e; border-radius: 12px; }}
QFrame#card[selected="true"] {{ border-color: {ACCENT}; }}
QFrame#warn {{ background: #2a2316; border: 1px solid #5a4620; border-radius: 8px; }}
"""


class Bus(QObject):
    """Мост из рабочих потоков в GUI-поток."""
    call = Signal(object)


BUS = None


def in_gui(fn):
    BUS.call.emit(fn)


def run_bg(fn, ok=None, err=None):
    def task():
        try:
            res = fn()
        except Exception as e:  # noqa: BLE001 — показываем пользователю любую ошибку
            if err:
                in_gui(lambda e=e: err(e))
            return
        if ok:
            in_gui(lambda: ok(res))
    POOL.submit(task)


def cached_image(url: str) -> QImage | None:
    path = core.CACHE_DIR / "img" / hashlib.sha1(url.encode()).hexdigest()
    if not path.is_file():
        try:
            data = core.http_get(url, timeout=20)
        except Exception:  # noqa: BLE001
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    img = QImage(str(path))
    return None if img.isNull() else img


# ---------------------------------------------------------------- карточка сервера

class ServerCard(QFrame):
    clicked = Signal(dict)
    activated = Signal(dict)

    W, H = 210, 132

    def __init__(self, srv: dict):
        super().__init__()
        self.setObjectName("card")
        self.srv = srv
        self.bg: QPixmap | None = None
        self.setFixedSize(self.W, self.H)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"{srv.get('host')}:{srv.get('port')}")
        url = srv.get("background")
        if url:
            run_bg(lambda: cached_image(url), self._set_bg)

    def _set_bg(self, img):
        if img is not None:
            self.bg = QPixmap.fromImage(img.scaled(self.W * 2, self.H * 2, Qt.KeepAspectRatioByExpanding,
                                                   Qt.SmoothTransformation))
            self.update()

    def set_selected(self, on: bool):
        self.setProperty("selected", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, e):
        self.clicked.emit(self.srv)

    def mouseDoubleClickEvent(self, e):
        self.activated.emit(self.srv)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(2, 2, -2, -2)
        clip = QPainterPath()
        clip.addRoundedRect(r, 10, 10)
        p.setClipPath(clip)
        if self.bg:
            src = self.bg.rect()
            x = (src.width() - r.width() * 2) // 2
            y = (src.height() - r.height() * 2) // 2
            p.drawPixmap(r, self.bg, src.adjusted(max(x, 0), max(y, 0), -max(x, 0), -max(y, 0)))
        p.fillRect(r, QColor(10, 10, 14, 120))
        s = self.srv
        online = bool(s.get("status", True))
        p.setPen(Qt.white)
        f = QFont(self.font())
        f.setPointSizeF(13)
        f.setBold(True)
        p.setFont(f)
        p.drawText(r.adjusted(12, 10, -10, 0), Qt.AlignLeft | Qt.AlignTop, f"{s.get('emoji', '')} {s.get('name')}")
        f.setPointSizeF(9.5)
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor("#d0d0d0"))
        p.drawText(r.adjusted(12, 0, -10, -30), Qt.AlignLeft | Qt.AlignBottom, f"#{s.get('id')}")
        players, mx = int(s.get("players") or 0), int(s.get("max_players") or 1)
        txt = f"{players} / {mx}" if online else "выключен"
        p.drawText(r.adjusted(12, 0, -10, -12), Qt.AlignLeft | Qt.AlignBottom, txt)
        # полоска заполненности
        bar = r.adjusted(12, r.height() - 8, -12, -4)
        p.fillRect(bar, QColor(255, 255, 255, 40))
        if online:
            bar.setWidth(int(bar.width() * min(players / mx, 1.0)))
            p.fillRect(bar, QColor(ACCENT))
        p.end()


# ---------------------------------------------------------------- капча / вход

CAPTCHA_HTML = """<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0;background:#141519;height:100%;display:flex;align-items:center;justify-content:center}</style>
@SCRIPT@</head><body><div id="c"></div><script>
function done(t){ document.title = "token:" + t; }
@INIT@
</script></body></html>"""

TURNSTILE = ('<script src="https://challenges.cloudflare.com/turnstile/v0/api.js?onload=go&render=explicit" async></script>',
             'function go(){ turnstile.render("#c", {sitekey: "@KEY@", theme: "dark", callback: done}); }')
RECAPTCHA = ('<script src="https://www.google.com/recaptcha/api.js?onload=go&render=explicit" async></script>',
             'function go(){ grecaptcha.render("c", {sitekey: "@KEY@", theme: "dark", callback: done}); }')


def solve_captcha(parent, key: str, version) -> str:
    """Показывает капчу (Turnstile или reCAPTCHA) во встроенном браузере, возвращает токен."""
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView
    except ImportError:
        QMessageBox.warning(parent, APP_NAME, "Сервер просит капчу, а модуль QtWebEngine не установлен.\n"
                            "Установите пакет pyside6 с QtWebEngine (Arch: pyside6) или войдите позже.")
        return ""
    if not core._SAFE_KEY.match(key or ""):
        return ""
    use_turnstile = str(key).startswith("0x") or "turn" in str(version).lower()
    script, init = TURNSTILE if use_turnstile else RECAPTCHA
    html = CAPTCHA_HTML.replace("@SCRIPT@", script).replace("@INIT@", init.replace("@KEY@", key))
    dlg = QDialog(parent)
    dlg.setWindowTitle("Подтвердите, что вы не робот")
    dlg.resize(420, 560)
    lay = QVBoxLayout(dlg)
    view = QWebEngineView(dlg)
    lay.addWidget(view)
    result = {"t": ""}

    def on_title(t):
        if t.startswith("token:"):
            result["t"] = t[6:]
            dlg.accept()
    view.titleChanged.connect(on_title)
    view.setHtml(html, QUrl(core.SITE + "/"))
    dlg.exec()
    return result["t"]


class LoginDialog(QDialog):
    def __init__(self, parent, login: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Вход в аккаунт GTA5RP")
        self.setMinimumWidth(380)
        self.api = core.Api()
        self.token = ""
        lay = QVBoxLayout(self)
        t = QLabel("Вход в аккаунт")
        t.setObjectName("title")
        lay.addWidget(t)
        hint = QLabel("Используйте логин и пароль от gta5rp.com")
        hint.setProperty("muted", True)
        lay.addWidget(hint)
        self.login = QLineEdit(login)
        self.login.setPlaceholderText("Логин или e-mail")
        self.pw = QLineEdit()
        self.pw.setPlaceholderText("Пароль")
        self.pw.setEchoMode(QLineEdit.Password)
        self.remember = QCheckBox("Запомнить меня")
        self.remember.setChecked(True)
        self.err = QLabel()
        self.err.setStyleSheet(f"color:{ACCENT}")
        self.err.setWordWrap(True)
        self.btn = QPushButton("Войти")
        self.btn.setObjectName("play")
        self.btn.clicked.connect(lambda: self.submit())
        for w in (self.login, self.pw, self.remember, self.err, self.btn):
            lay.addWidget(w)
        links = QHBoxLayout()
        for text, url in (("Регистрация", core.SITE), ("Забыли пароль?", core.SITE)):
            b = QPushButton(text)
            b.setFlat(True)
            b.clicked.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            links.addWidget(b)
        lay.addLayout(links)
        self.pw.returnPressed.connect(lambda: self.submit())
        (self.pw if login else self.login).setFocus()

    def submit(self, captcha: str = "", rid: str = "", code: str = ""):
        lg, pw = self.login.text().strip(), self.pw.text()
        if not lg or not pw:
            self.err.setText("Введите логин и пароль")
            return
        self.btn.setEnabled(False)
        self.err.setText("")
        rem = self.remember.isChecked()
        run_bg(lambda: self.api.login(lg, pw, rem, captcha, rid, code), self._ok, self._fail)

    def _ok(self, token):
        self.token = token
        self.accept()

    def _fail(self, e):
        self.btn.setEnabled(True)
        if isinstance(e, core.ApiError) and e.need_captcha:
            tok = solve_captcha(self, e.data.get("key"), e.data.get("captcha_version"))
            if tok:
                self.submit(captcha=tok)
            else:
                self.err.setText("Капча не пройдена")
            return
        if isinstance(e, core.ApiError) and e.twofa_rid:
            code, ok = QInputDialog.getText(self, "Двухфакторная защита",
                                            str(e) or "Введите код подтверждения:")
            if ok and code.strip():
                self.submit(rid=e.twofa_rid, code=code.strip())
            return
        self.err.setText(str(e))


# ---------------------------------------------------------------- главное окно

class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = core.load_config()
        self.api = core.Api(self.cfg.get("session_token", ""))
        self.setup = core.detect(self.cfg)
        self.servers: list[dict] = []
        self.cards: list[ServerCard] = []
        self.selected: dict | None = None
        self.proc: QProcess | None = None
        self.profile: dict = {}

        self.setWindowTitle(APP_NAME)
        self.resize(1040, 700)
        central = QWidget(objectName="central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 14, 18, 14)

        # шапка
        head = QHBoxLayout()
        title = QLabel("GTA5RP")
        title.setObjectName("title")
        head.addWidget(title)
        sub = QLabel("лаунчер для Linux")
        sub.setProperty("muted", True)
        head.addWidget(sub)
        head.addStretch()
        self.acc_label = QLabel()
        head.addWidget(self.acc_label)
        self.acc_btn = QPushButton()
        self.acc_btn.clicked.connect(self.on_account)
        head.addWidget(self.acc_btn)
        root.addLayout(head)

        self.warn = QFrame(objectName="warn")
        wl = QHBoxLayout(self.warn)
        self.warn_text = QLabel()
        self.warn_text.setWordWrap(True)
        self.warn_text.setOpenExternalLinks(True)
        wl.addWidget(self.warn_text, 1)
        root.addWidget(self.warn)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self.tabs.addTab(self._servers_tab(), "Сервера")
        self.tabs.addTab(self._news_tab(), "Новости")
        self.tabs.addTab(self._settings_tab(), "Настройки")
        self.tabs.addTab(self._log_tab(), "Журнал")

        # низ
        bottom = QHBoxLayout()
        col = QVBoxLayout()
        self.status = QLabel("Готово")
        self.sel_label = QLabel()
        self.sel_label.setProperty("muted", True)
        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.setVisible(False)
        col.addWidget(self.status)
        col.addWidget(self.sel_label)
        col.addWidget(self.busy)
        bottom.addLayout(col, 1)
        self.play_btn = QPushButton("ИГРАТЬ", objectName="play")
        self.play_btn.clicked.connect(self.on_play)
        bottom.addWidget(self.play_btn)
        root.addLayout(bottom)

        self.update_account()
        self.update_warnings()
        self.refresh_servers()
        self.refresh_news()
        if self.api.token:
            run_bg(self.api.profile, self._got_profile, lambda e: self._session_failed(e, quiet=True))
        self.timer = QTimer(self, interval=60_000, timeout=self.refresh_servers)
        self.timer.start()
        self.game_timer = QTimer(self, interval=3000, timeout=self.poll_game)
        self.game_timer.start()

    # ---------- вкладки
    def _servers_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0)
        top = QHBoxLayout()
        self.online_label = QLabel()
        self.online_label.setProperty("muted", True)
        top.addWidget(self.online_label)
        top.addStretch()
        rb = QPushButton("Обновить")
        rb.clicked.connect(self.refresh_servers)
        top.addWidget(rb)
        lay.addLayout(top)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setSpacing(12)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(self.grid_host)
        sa.viewport().setAutoFillBackground(False)
        self.grid_host.setStyleSheet("background: transparent;")
        lay.addWidget(sa, 1)
        return w

    def _news_tab(self):
        sp = QSplitter()
        self.news_list = QListWidget()
        self.news_list.setMaximumWidth(330)
        self.news_view = QTextBrowser()
        self.news_view.setOpenExternalLinks(True)
        self.news_list.currentRowChanged.connect(self.show_news)
        sp.addWidget(self.news_list)
        sp.addWidget(self.news_view)
        sp.setStretchFactor(1, 1)
        return sp

    def _settings_tab(self):
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(4, 14, 4, 4)
        self.proton_box = QComboBox()
        self.proton_box.currentIndexChanged.connect(self.on_proton)
        form.addRow("Proton:", self.proton_box)
        gl = QHBoxLayout()
        self.gta_edit = QLineEdit()
        self.gta_edit.setReadOnly(True)
        gb = QPushButton("Выбрать…")
        gb.clicked.connect(self.pick_gta)
        gl.addWidget(self.gta_edit, 1)
        gl.addWidget(gb)
        form.addRow("Папка GTA V:", gl)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow("Состояние:", self.info)
        self.debug_cb = QCheckBox("Писать подробный лог Proton (для поиска проблем)")
        form.addRow("", self.debug_cb)
        self.close_cb = QCheckBox("Сворачивать лаунчер после запуска игры")
        self.close_cb.setChecked(bool(self.cfg.get("close_on_play")))
        self.close_cb.toggled.connect(lambda v: self._set("close_on_play", v))
        form.addRow("", self.close_cb)
        row = QHBoxLayout()
        for text, fn in (("Папка RAGE:MP", self.open_rage), ("Установить EAC Runtime", self.install_eac),
                         ("Закрыть игру", self.kill_game), ("Обновить состояние", self.redetect)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        form.addRow("", row)
        about = QLabel(f"Неофициальный лаунчер v{core.VERSION} · протокол сверен с официальным "
                       f"v{core.OFFICIAL_VERSION}. Не связан с GTA5RP.")
        about.setProperty("muted", True)
        about.setWordWrap(True)
        form.addRow("", about)
        self.fill_settings()
        return w

    def _log_tab(self):
        self.log_view = QPlainTextEdit(readOnly=True)
        self.log_view.setMaximumBlockCount(5000)
        return self.log_view

    def log(self, text: str):
        self.log_view.appendPlainText(text.rstrip())

    def _set(self, k, v):
        self.cfg[k] = v
        core.save_config(self.cfg)

    # ---------- настройки
    def fill_settings(self):
        s = self.setup
        self.proton_box.blockSignals(True)
        self.proton_box.clear()
        for p in s.protons:
            self.proton_box.addItem(p.name, str(p))
        if s.proton:
            i = self.proton_box.findData(str(s.proton))
            self.proton_box.setCurrentIndex(max(i, 0))
        self.proton_box.blockSignals(False)
        self.gta_edit.setText(str(s.gta_path or ""))
        ok, no = "✔", "✘"
        lines = [
            f"{ok if s.steam_root else no} Steam: {s.steam_root or 'не найден'}"
            f" ({'запущен' if core.steam_running() else 'не запущен'})",
            f"{ok if s.compatdata else no} Префикс GTA V: {s.pfx or 'нет'}",
            f"{ok if s.runtime_entry else '–'} Steam Linux Runtime: {s.runtime_entry.parent.name if s.runtime_entry else 'нет'}",
            f"{ok if s.eac_runtime else '–'} Proton EasyAntiCheat Runtime: {'установлен' if s.eac_runtime else 'нет'}",
            f"{ok if s.rage_dir and (s.rage_dir / 'updater.exe').is_file() else '–'} RAGE:MP: "
            f"{s.rage_dir or '—'}",
        ]
        self.info.setText("\n".join(lines))

    def on_proton(self, i):
        self._set("proton", self.proton_box.itemData(i) or "")
        self.redetect()

    def pick_gta(self):
        d = QFileDialog.getExistingDirectory(self, "Папка Grand Theft Auto V", str(self.setup.gta_path or Path.home()))
        if d:
            if not (Path(d) / "GTA5.exe").is_file():
                QMessageBox.warning(self, APP_NAME, "В этой папке нет GTA5.exe")
                return
            self._set("gta_path", d)
            self.redetect()

    def redetect(self):
        self.setup = core.detect(self.cfg)
        self.fill_settings()
        self.update_warnings()

    def update_warnings(self):
        s = self.setup
        msgs = list(s.problems)
        if s.ok and not s.eac_runtime:
            msgs.append("RAGE:MP использует EasyAntiCheat. Поставьте <b>Proton EasyAntiCheat Runtime</b> "
                        "(Настройки → «Установить EAC Runtime»), иначе античит может не пустить в игру.")
        self.warn_text.setText("<br>".join(msgs))
        self.warn.setVisible(bool(msgs))

    def open_rage(self):
        d = self.setup.rage_dir
        if d:
            d.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    def install_eac(self):
        QDesktopServices.openUrl(QUrl(f"steam://install/{core.EAC_RUNTIME_APPID}"))
        self.log("Открыл установку Proton EasyAntiCheat Runtime в Steam. После установки нажмите "
                 "«Обновить состояние».")

    def kill_game(self):
        if QMessageBox.question(self, APP_NAME, "Принудительно закрыть всё в префиксе GTA V?") == QMessageBox.Yes:
            run_bg(lambda: core.kill_prefix(self.setup), lambda _: self.log("Префикс остановлен"),
                   lambda e: self.log(f"Ошибка: {e}"))

    # ---------- аккаунт
    def update_account(self):
        if self.api.token:
            name = self.profile.get("login") or self.cfg.get("login") or "аккаунт"
            self.acc_label.setText(f"👤 {name}")
            self.acc_btn.setText("Выйти")
        else:
            self.acc_label.setText("")
            self.acc_btn.setText("Войти")

    def _got_profile(self, prof):
        self.profile = prof if isinstance(prof, dict) else {}
        if self.profile.get("login"):
            self._set("login", self.profile["login"])
        self.update_account()

    def _session_failed(self, e, quiet=False):
        if isinstance(e, core.ApiError) and e.status in (401, 403):
            self.api.token = ""
            self._set("session_token", "")
            self.update_account()
            if not quiet:
                QMessageBox.information(self, APP_NAME, "Сессия истекла — войдите снова.")
        elif not quiet:
            QMessageBox.warning(self, APP_NAME, str(e))

    def on_account(self):
        if self.api.token:
            api = self.api
            run_bg(api.logout)
            self.api = core.Api()
            self.profile = {}
            self._set("session_token", "")
            self.update_account()
            return
        self.do_login()

    def do_login(self) -> bool:
        dlg = LoginDialog(self, self.cfg.get("login", ""))
        if dlg.exec() != QDialog.Accepted:
            return False
        self.api = core.Api(dlg.token)
        self.cfg["login"] = dlg.login.text().strip()
        self._set("session_token", dlg.token if dlg.remember.isChecked() else "")
        self.update_account()
        run_bg(self.api.profile, self._got_profile, lambda e: None)
        return True

    # ---------- сервера / новости
    def refresh_servers(self):
        run_bg(core.Api().servers, self._got_servers,
               lambda e: self.status.setText(f"Не удалось загрузить сервера: {e}"))

    def _got_servers(self, servers):
        if not isinstance(servers, list):
            return
        servers = sorted(servers, key=lambda s: int(s.get("id", 0)))
        known = {c.srv.get("id"): c for c in self.cards}
        if set(known) == {s.get("id") for s in servers}:
            for s in servers:  # только обновить онлайн
                known[s["id"]].srv = s
                known[s["id"]].update()
        else:
            for c in self.cards:
                c.deleteLater()
            self.cards = []
            for i, s in enumerate(servers):
                c = ServerCard(s)
                c.clicked.connect(self.select)
                c.activated.connect(lambda s: (self.select(s), self.on_play()))
                self.grid.addWidget(c, i // 4, i % 4)
                self.cards.append(c)
        self.servers = servers
        total = sum(int(s.get("players") or 0) for s in servers)
        self.online_label.setText(f"{len(servers)} серверов · {total} игроков онлайн")
        last = self.selected.get("id") if self.selected else self.cfg.get("last_server")
        for s in servers:
            if s.get("id") == last:
                self.select(s)
                break

    def select(self, srv):
        self.selected = srv
        for c in self.cards:
            c.set_selected(c.srv.get("id") == srv.get("id"))
        self.sel_label.setText(f"Сервер: {srv.get('emoji', '')} {srv.get('name')} — "
                               f"{srv.get('host')}:{srv.get('port')}")

    def refresh_news(self):
        run_bg(core.Api().news, self._got_news, lambda e: self.news_view.setPlainText(str(e)))

    def _got_news(self, items):
        self.news = items or []
        self.news_list.clear()
        for n in self.news:
            it = QListWidgetItem(f"{n.get('title', '')}\n{n.get('little_text') or ''}")
            self.news_list.addItem(it)
        if self.news:
            self.news_list.setCurrentRow(0)

    def show_news(self, row):
        if 0 <= row < len(getattr(self, "news", [])):
            n = self.news[row]
            html = n.get("text") or n.get("description") or ""
            # iframe с YouTube Qt не покажет — заменяем ссылкой
            html = re.sub(r'<iframe[^>]*src="([^"]+)"[^>]*>\s*</iframe>',
                          lambda m: f'<p><a href="https:{m.group(1)}" style="color:{ACCENT}">▶ Видео</a></p>'
                          if m.group(1).startswith("//") else f'<p><a href="{m.group(1)}">▶ Видео</a></p>', html)
            self.news_view.setHtml(f"<h2>{n.get('title', '')}</h2>{html}")

    # ---------- запуск
    def on_play(self):
        if self.proc and self.proc.state() != QProcess.NotRunning:
            QMessageBox.information(self, APP_NAME, "Игра уже запускается.")
            return
        if not self.selected:
            QMessageBox.information(self, APP_NAME, "Выберите сервер.")
            return
        self.redetect()
        if not self.setup.ok:
            QMessageBox.warning(self, APP_NAME, "\n\n".join(self.setup.problems))
            return
        if not self.api.token and not self.do_login():
            return
        if not core.steam_running():
            r = QMessageBox.question(self, APP_NAME, "Steam не запущен, а GTA V из Steam без него не стартует.\n"
                                     "Запустить Steam сейчас?")
            if r == QMessageBox.Yes:
                subprocess.Popen(["steam", "-silent"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
                self.status.setText("Жду запуска Steam…")
                QTimer.singleShot(12_000, self.on_play)
                return
        srv = self.selected
        self._set("last_server", srv.get("id"))
        self.set_busy(True, "Получаю игровой токен…")
        host, port = srv.get("host"), int(srv.get("port") or 22005)
        debug = self.debug_cb.isChecked()

        def work():
            token = self.api.rage_token()
            return core.prepare_launch(self.setup, host, port, token,
                                       progress=lambda t: in_gui(lambda: self.status.setText(t)), debug=debug)
        run_bg(work, self._launch, self._launch_failed)

    def _launch_failed(self, e):
        self.set_busy(False, "Ошибка запуска")
        if isinstance(e, core.ApiError) and e.status in (401, 403):
            self._session_failed(e)
            return
        self.log(f"Ошибка: {e}")
        QMessageBox.warning(self, APP_NAME, str(e))

    def _launch(self, res):
        cmd, env, cwd = res
        self.log("Запуск: " + " ".join(c if "launch5rp" not in c else "<launch5rp.bat>" for c in cmd))
        self.status.setText("Запускаю RAGE:MP через Proton…")
        self.proc = QProcess(self)
        qenv = QProcessEnvironment()
        for k, v in env.items():
            qenv.insert(k, v)
        self.proc.setProcessEnvironment(qenv)
        self.proc.setWorkingDirectory(cwd)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyRead.connect(lambda: self.log(bytes(self.proc.readAll()).decode(errors="replace")))
        self.proc.finished.connect(self._finished)
        self.proc.start(cmd[0], cmd[1:])
        if not self.proc.waitForStarted(5000):
            self._launch_failed(RuntimeError("Не удалось запустить Proton"))
            return
        if self.cfg.get("close_on_play"):
            QTimer.singleShot(8000, self.showMinimized)
        if not (self.setup.rage_dir / "ragemp_v.exe").is_file():
            QMessageBox.information(
                self, APP_NAME,
                "Первый запуск: RAGE:MP сейчас докачает свои файлы.\n\n"
                "• На вопрос «RAGE Multiplayer was launched from folder … never been used before» "
                "нажмите OK — это обычная проверка RAGE при новой папке.\n"
                "• Если он спросит папку GTA V — выберите диск G: (это ваша GTA V из Steam)."
            )

    def _finished(self, code, _status):
        self.set_busy(False, f"Игра закрыта (код {code})")
        self.log(f"Proton завершился с кодом {code}")
        self.fill_settings()

    def poll_game(self):
        if not (self.proc and self.proc.state() != QProcess.NotRunning):
            return
        procs = core.running_game_procs()
        if "GTA5.exe" in procs:
            self.status.setText("Игра запущена")
        elif procs:
            self.status.setText("RAGE:MP: " + ", ".join(procs))

    def set_busy(self, on, text=""):
        self.busy.setVisible(on)
        self.play_btn.setEnabled(not on)
        if text:
            self.status.setText(text)
        if on:
            self.log(text)

    def closeEvent(self, e):
        self.timer.stop()
        self.game_timer.stop()
        if self.proc and self.proc.state() != QProcess.NotRunning:
            self.proc.finished.disconnect()  # игра живёт дальше без лаунчера
        super().closeEvent(e)


def app_icon() -> QIcon:
    data = Path.home() / ".local/share/icons/hicolor"
    for p in (data / "256x256/apps/gta5rp-launcher-original.png", data / "scalable/apps/gta5rp-launcher.svg",
              Path(__file__).resolve().parent / "data" / "gta5rp-launcher.svg",
              Path("/usr/share/icons/hicolor/scalable/apps/gta5rp-launcher.svg")):
        if p.is_file():
            return QIcon(str(p))
    return QIcon()


def try_official_ui(app):
    """Оригинальный интерфейс 5RP (из установщика пользователя) с нашим ядром. None — если нельзя."""
    try:
        import gta5rp_official as official
        import gta5rp_webui as webui
    except ImportError as e:  # нет QtWebEngine/QtWebSockets
        print(f"Оригинальный интерфейс недоступен: {e}", file=sys.stderr)
        return None
    installer = official.find_installer()
    if official.needs_update(installer):
        from PySide6.QtWidgets import QProgressDialog
        dlg = QProgressDialog("Подготавливаю интерфейс GTA5RP из официального установщика…", None, 0, 0)
        dlg.setWindowTitle(APP_NAME)
        dlg.setMinimumDuration(0)
        dlg.show()
        fut = POOL.submit(official.extract_from_installer, installer)
        while not fut.done():
            app.processEvents()
            time.sleep(0.05)
        dlg.close()
        try:
            fut.result()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(None, APP_NAME, f"Не удалось взять оригинальный интерфейс:\n{e}\n\n"
                                "Открываю упрощённый интерфейс.")
    if not official.index_html():
        return None
    return webui.WebWindow(on_log=lambda t: print(t.rstrip(), file=sys.stderr))


def main():
    global BUS
    QApplication.setDesktopFileName("gta5rp-launcher")
    classic = "--classic" in sys.argv
    if not classic:
        try:  # QtWebEngine нужно импортировать до создания QApplication
            import PySide6.QtWebEngineWidgets  # noqa: F401
            QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
        except ImportError:
            classic = True
    app = QApplication([a for a in sys.argv if a != "--classic"])
    app.setApplicationName("gta5rp-launcher")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    BUS = Bus()
    BUS.call.connect(lambda fn: fn(), Qt.QueuedConnection)
    orig = Path.home() / ".local/share/icons/hicolor/256x256/apps/gta5rp-launcher-original.png"
    if not orig.is_file():
        try:
            core.extract_official_icon(orig)
        except Exception:  # noqa: BLE001
            pass
    app.setWindowIcon(app_icon())
    w = None if classic else try_official_ui(app)
    if w is None:
        w = Main()
        w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
