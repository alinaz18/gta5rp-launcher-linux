#!/usr/bin/env python3
"""Ежедневная проверка: API GTA5RP и RAGE:MP отвечают так, как ждёт лаунчер.

Пишет watchdog-report.md и выходит с кодом 1, если что-то изменилось.
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gta5rp_core as core  # noqa: E402

problems: list[str] = []
notes: list[str] = []


def check(name, fn):
    try:
        fn()
        notes.append(f"- ✅ {name}")
    except Exception as e:  # noqa: BLE001
        problems.append(f"- ❌ **{name}**: {e}")


def servers():
    s = core.Api().servers()
    assert isinstance(s, list) and s, "пустой список серверов"
    for k in ("id", "name", "host", "port", "players", "max_players"):
        assert all(k in x for x in s), f"у серверов нет поля {k!r}"


def news():
    assert isinstance(core.Api().news(), list), "новости не список"


def launcher_version():
    r = core.Api().launcher_update()
    if r.get("type") != "ok":
        raise AssertionError(f"вышел новый официальный лаунчер {r.get('v')} (сверялись с {core.OFFICIAL_VERSION}): "
                             "переснять протокол (app.asar + RPC ядра) и обновить OFFICIAL_VERSION")


def rage_token_endpoint():
    try:
        core.Api().rage_token()
    except core.ApiError as e:
        assert e.status == 401, f"ожидался 401 без входа, пришло {e.status}: {e}"
        return
    raise AssertionError("токен выдан без входа?!")


def login_endpoint():
    try:
        core.Api().login("watchdog_nonexistent_user_5rp", "x")
    except core.ApiError as e:
        assert 400 <= e.status < 500 and e.data, f"странный ответ входа: {e.status} {e}"
        return
    raise AssertionError("вход прошёл с фиктивными данными?!")


def updater():
    ok = []
    for url in core.UPDATER_URLS:
        req = urllib.request.Request(url, headers={"User-Agent": core.UA, "Range": "bytes=0-1"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                if r.read(2) == b"MZ":
                    ok.append(url)
        except (urllib.error.URLError, OSError):
            pass
    assert ok, "ни одно зеркало RAGE:MP updater.exe не отдаёт exe"
    if len(ok) < len(core.UPDATER_URLS):
        notes.append(f"  - живых зеркал updater: {len(ok)}/{len(core.UPDATER_URLS)}")


for name, fn in (("Список серверов", servers), ("Новости", news), ("Версия официального лаунчера", launcher_version),
                 ("Эндпоинт игрового токена", rage_token_endpoint), ("Эндпоинт входа", login_endpoint),
                 ("RAGE:MP updater.exe", updater)):
    check(name, fn)

report = "## Watchdog GTA5RP\n\n" + "\n".join(problems + notes) + "\n"
Path("watchdog-report.md").write_text(report, encoding="utf-8")
print(report)
sys.exit(1 if problems else 0)
