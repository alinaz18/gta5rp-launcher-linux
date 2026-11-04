# GTA5RP Launcher for Linux

**Русский** · [English](README.en.md) · [Сайт](https://alinaz18.github.io/gta5rp-launcher-linux/)

Неофициальный лаунчер [GTA5RP](https://gta5rp.com) для **Linux и Windows**. Интерфейс —
оригинальный, из официального установщика 5RP, но с новым оформлением и шестью темами;
вместо защищённого Windows-ядра работает собственное ядро на Python. На Linux RAGE:MP и
GTA V запускаются через Proton из Steam, на Windows — напрямую.

![Сервера](docs/shots/servers.webp)

| Главная | Linux-настройки |
|---|---|
| ![Главная](docs/shots/home.webp) | ![Настройки](docs/shots/settings.webp) |

## Темы

| Оригинальная | zxc · dead inside | Барби |
|---|---|---|
| ![original](docs/shots/themes-original.webp) | ![zxc](docs/shots/themes-zxc.webp) | ![barbie](docs/shots/themes-barbie.webp) |
| **Вайб-кодер** | **Vice City** | **Diamond Casino** |
| ![vibe](docs/shots/themes-vibe.webp) | ![vice](docs/shots/themes-vice.webp) | ![casino](docs/shots/themes-casino.webp) |

Каждая тема со своей анимацией: лепестки ликориса, «1000−7» и глитч у zxc, блёстки и
сердечки у Барби, матричный дождь у вайб-кодера, неоновый закат с сеткой и пальмами у
Vice City, золотая пыль у Diamond Casino.

## Возможности

- **Оригинальный интерфейс 5RP** — вход в аккаунт, сервера, новости, профиль, капча и 2FA
  работают как в официальном лаунчере.
- **Живой фон под сервер** — арт выбранного сервера во всё окно, цветные сияния в его
  гамме и свет за курсором; при наведении на другой сервер всё плавно перетекает в его тему.
- **Новое оформление** — стеклянная левая панель, карточки с 3D-наклоном и бликом,
  каскадные анимации; можно облегчить или выключить для слабых ПК.
- **Левая панель** — карточка «Ваш сервер» с живым онлайном и индикаторы Steam / Proton /
  античит / RAGE:MP.
- **Linux-настройки** — выбор Proton, папка GTA V, сворачивание после запуска, подробный
  лог Proton, проверка системы, установка EasyAntiCheat Runtime, аварийное закрытие игры.
- **Шесть тем с анимацией** — переключаются в настройках одним кликом.
- **Версия для Windows** — тот же интерфейс, фон и темы; RAGE:MP запускается напрямую.
- **Официальный установщик скачивается сам**, если его нет в «Загрузках».
- **Простой интерфейс на Qt** — запасной вариант для Linux (`gta5rp-launcher --classic`).

## Требования

- GTA V (Legacy) в Steam с включённым Proton; игру нужно один раз запустить из Steam;
- Steam должен быть запущен во время игры;
- **Proton EasyAntiCheat Runtime** — RAGE:MP использует EasyAntiCheat
  (лаунчер сам предложит поставить);
- интернет при первом запуске: лаунчер возьмёт официальный установщик из «Загрузок» или
  скачает его с files.gta5rp.com — из него берётся оригинальный интерфейс;
- Python 3.9+, PySide6 с QtWebEngine, Wine (только для распаковки установщика).

## Установка

```sh
git clone https://github.com/alinaz18/gta5rp-launcher-linux
cd gta5rp-launcher-linux
./install.sh
```

Или готовые пакеты из [релизов](https://github.com/alinaz18/gta5rp-launcher-linux/releases):
`.deb` (Debian / Ubuntu / Mint), `.rpm` (Fedora / openSUSE). Для Arch — `packaging/aur/PKGBUILD`.

Первый запуск: лаунчер один раз распакует интерфейс из установщика (~10 секунд).
При первом входе в игру RAGE:MP спросит, можно ли работать из новой папки, — нажмите
**OK**; если он спросит папку GTA V — выберите диск **G:** (это ваша GTA V из Steam).

Удаление — `./uninstall.sh`.

### Windows

Скачайте `GTA5RP-Launcher-Setup-*.exe` (или portable-архив) из
[последнего релиза](https://github.com/alinaz18/gta5rp-launcher-linux/releases/latest) и запустите.
Официальный лаунчер 5RP скачается и установится сам — из него берётся интерфейс.

![Windows](docs/shots/windows.webp)
*Снято автотестом на настоящей Windows в GitHub Actions.*

## Как это работает

Официальный лаунчер состоит из интерфейса на Electron и защищённого ядра
`GTA5RPLauncher.exe`, которые общаются JSON-сообщениями. Этот лаунчер:

1. достаёт интерфейс (`app.asar`) из вашего установщика и показывает его в Qt WebEngine;
2. отвечает на сообщения интерфейса своим ядром (`gta5rp_webui.py`);
3. по кнопке «Играть» делает то же, что оригинал: кладёт RAGE:MP `updater.exe` в
   `C:\Games\GTA5RP\RageMP`, пишет адрес сервера и игровой токен в
   `HKCU\Software\RAGE-MP` (`launch2.*`) и запускает updater через Proton в префиксе
   GTA V из Steam.

Файлы интерфейса GTA5RP не входят в репозиторий — они берутся только из официального
установщика. Логотип, арты серверов и интерфейс на скриншотах — © GTA5RP. Ежедневный [watchdog](.github/workflows/watchdog.yml) проверяет,
что API 5RP и зеркала RAGE:MP отвечают как ожидается, и открывает issue, если что-то
изменилось.

## Отказ от ответственности

Проект не связан с GTA5RP, RAGE Multiplayer, Rockstar Games или Valve. Используйте на
свой страх и риск; решения о блокировках принимает администрация проекта.

Лицензия — [MIT](LICENSE).
