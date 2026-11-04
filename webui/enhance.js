// GTA5RP Launcher for Linux — живой фон под сервер, виджеты левой панели, эффекты и Linux-настройки.
(() => {
  if (document.getElementById('rp-bg')) return;

  const API = 'https://api.gta5rp.com/api/V2/';
  const K_SERVER = 'rp-enh:server-bg';
  const K_PREFS = 'rp-enh:prefs';
  const DEFAULT_BG = './images/gtav-bg.png';
  const bridge = (name, ...a) => (window.__rp ? window.__rp(name, ...a) : Promise.resolve(null));
  const ls = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch {} },
  };
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const IS_WIN = /^Win/.test(navigator.platform || '');
  const isServerBg = (u) => /^https:\/\/([a-z0-9-]+\.)?gta5rp\.com\/sidback\/\d+\.png/.test(u || '');
  const fmt = (n) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
  const sidOf = (u) => { const m = /sidback\/(\d+)\.png/.exec(u || ''); return m ? +m[1] : 0; };

  // ------------------------------------------------------------ настройки оформления
  const prefs = Object.assign({ bg: true, strength: 0.55, spot: true, tilt: true, motion: 'full' },
    (() => { try { return JSON.parse(ls.get(K_PREFS, '{}')); } catch { return {}; } })());
  function applyPrefs() {
    const h = document.documentElement;
    h.classList.toggle('rp-nobg', !prefs.bg);
    h.classList.toggle('rp-nospot', !prefs.spot);
    h.classList.toggle('rp-lite', prefs.motion === 'lite');
    h.classList.toggle('rp-still', prefs.motion === 'off');
    h.style.setProperty('--rp-strength', String(prefs.strength));
    ls.set(K_PREFS, JSON.stringify(prefs));
  }
  applyPrefs();

  // ------------------------------------------------------------ фон
  const bg = document.createElement('div');
  bg.id = 'rp-bg';
  bg.innerHTML = '<div class="rp-img"></div><div class="rp-img"></div>' +
    '<div class="rp-aurora"><i></i><i></i><i></i></div><div class="rp-shade"></div>' +
    '<div class="rp-spot"></div><div class="rp-grain"></div>';
  document.body.prepend(bg);
  const [imgA, imgB] = bg.querySelectorAll('.rp-img');
  let front = imgA, current = '', want = '';

  function showBg(url) {
    url = url || DEFAULT_BG;
    want = url;
    if (url === current) return;
    const img = new Image();
    img.onload = () => {
      if (want !== url) return;
      current = url;
      const back = front === imgA ? imgB : imgA;
      back.style.backgroundImage = `url("${url}")`;
      back.classList.add('on');
      front.classList.remove('on');
      front = back;
    };
    img.src = url;
    if (isServerBg(url) && window.__rpTheme) {
      window.__rpTheme(url).then((c) => { if (want === url && c) document.documentElement.style.setProperty('--rp-c', c); });
    } else if (!isServerBg(url)) {
      document.documentElement.style.setProperty('--rp-c', '#ff7a2f');
    }
  }
  const selected = () => ls.get(K_SERVER, '');

  // свет за курсором
  let raf = 0, mx = 0, my = 0;
  document.addEventListener('mousemove', (e) => {
    mx = e.clientX; my = e.clientY;
    if (!raf) raf = requestAnimationFrame(() => {
      raf = 0;
      document.documentElement.style.setProperty('--mx', mx + 'px');
      document.documentElement.style.setProperty('--my', my + 'px');
    });
  }, { passive: true });

  // ------------------------------------------------------------ карточки серверов
  function cardOf(target) {
    const el = target instanceof Element ? target.closest('button.group') : null;
    return el && el.querySelector('img[src*="/sidback/"]') ? el : null;
  }
  const cardUrl = (card) => card.querySelector('img[src*="/sidback/"]').src;

  let hovered = null;
  document.addEventListener('mouseover', (e) => {
    const card = cardOf(e.target);
    if (card === hovered) return;
    if (hovered) hovered.style.transform = '';
    hovered = card;
    showBg(card ? cardUrl(card) : selected());
  }, true);

  document.addEventListener('mousemove', (e) => {
    if (!hovered) return;
    const r = hovered.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
    hovered.style.setProperty('--px', (x * 100) + '%');
    hovered.style.setProperty('--py', (y * 100) + '%');
    if (prefs.tilt && prefs.motion !== 'off') {
      hovered.style.transform = `perspective(900px) rotateX(${(0.5 - y) * 7}deg) rotateY(${(x - 0.5) * 9}deg) translateY(-3px)`;
    }
  }, { passive: true });

  document.addEventListener('click', (e) => {
    const card = cardOf(e.target);
    if (!card) return;
    ls.set(K_SERVER, cardUrl(card));
    showBg(cardUrl(card));
    markSelected();
    renderServer();
  }, true);

  function markSelected() {
    const sid = sidOf(selected());
    document.querySelectorAll('button.group').forEach((b) => {
      const img = b.querySelector('img[src*="/sidback/"]');
      b.classList.toggle('rp-selected', !!img && sid > 0 && sidOf(img.src) === sid);
    });
  }

  // каскадное появление новых карточек
  let seq = 0, seqTimer = 0;
  function animateNew(root) {
    root.querySelectorAll?.('button.group:not([data-rp-in]), #root h2.font-secondary:not([data-rp-in])').forEach((el) => {
      el.dataset.rpIn = '1';
      if (prefs.motion === 'off') return;
      el.style.setProperty('--i', String(seq++));
      el.classList.add('rp-in');
      el.addEventListener('animationend', () => el.classList.remove('rp-in'), { once: true });
    });
    clearTimeout(seqTimer);
    seqTimer = setTimeout(() => { seq = 0; }, 300);
  }

  // ------------------------------------------------------------ левая панель
  let servers = [];
  let linux = null;
  const side = document.createElement('div');
  side.id = 'rp-side';
  side.innerHTML =
    '<div class="rp-card rp-server" title="Сервер для входа"><div class="rp-thumb"></div><div class="rp-meta"></div></div>' +
    '<div class="rp-card rp-sys" title="Состояние системы — открыть Linux-настройки"></div>' +
    `<button class="rp-btn" data-act="settings">⚙ ${IS_WIN ? 'Настройки лаунчера' : 'Linux-настройки'}</button>`;
  side.querySelector('.rp-server').addEventListener('click', () => {
    const a = [...document.querySelectorAll('#root nav a')].find((x) => /сервер/i.test(x.textContent));
    a?.click();
  });
  side.querySelector('.rp-sys').addEventListener('click', openDrawer);
  side.querySelector('[data-act=settings]').addEventListener('click', openDrawer);

  function mountSide() {
    const nav = document.querySelector('#root nav');
    if (!nav || side.isConnected) return;
    nav.after(side);
    renderServer();
    renderSys();
  }

  function renderServer() {
    const card = side.querySelector('.rp-server');
    const thumb = card.querySelector('.rp-thumb');
    const meta = card.querySelector('.rp-meta');
    const sid = sidOf(selected());
    const s = servers.find((x) => +x.id === sid);
    if (!sid) {
      thumb.style.backgroundImage = `url("${DEFAULT_BG}")`;
      meta.innerHTML = '<div class="rp-label">Сервер</div><div class="rp-name">Не выбран</div>' +
        '<div class="rp-online">Нажмите на сервер в списке</div>';
      return;
    }
    thumb.style.backgroundImage = `url("${selected()}")`;
    const on = s ? +s.players || 0 : 0, max = s ? +s.max_players || 1 : 1;
    meta.innerHTML = `<div class="rp-label">Ваш сервер · #${sid}</div>` +
      `<div class="rp-name">${esc(s ? `${s.emoji || ''} ${s.name}` : `Сервер ${sid}`)}</div>` +
      `<div class="rp-online"><span class="rp-dot"></span><b>${fmt(on)}</b><span>/ ${fmt(max)} онлайн</span></div>` +
      '<div class="rp-bar"><i></i></div>';
    requestAnimationFrame(() => { meta.querySelector('.rp-bar i').style.width = Math.min(100, on / max * 100) + '%'; });
  }

  function renderSys() {
    const box = side.querySelector('.rp-sys');
    if (!linux) { box.innerHTML = '<span class="rp-chip">Проверяю…</span>'; return; }
    const chips = linux.chips || [];
    box.innerHTML = chips.map(([n, ok]) => `<span class="rp-chip${ok ? ' ok' : ''}">${n}</span>`).join('');
  }

  async function loadServers() {
    try {
      const r = await fetch(API + 'servers/stats', { headers: { 'X-Lang': 'ru' } });
      if (r.ok) { servers = await r.json(); renderServer(); }
    } catch {}
  }
  async function loadLinux() {
    const s = await bridge('linuxState');
    if (s) { linux = JSON.parse(s); renderSys(); }
  }

  // ------------------------------------------------------------ Linux-настройки
  const drawer = document.createElement('div');
  drawer.id = 'rp-drawer';
  document.body.appendChild(drawer);
  drawer.addEventListener('click', (e) => { if (e.target.classList.contains('rp-veil')) closeDrawer(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && drawer.classList.contains('open')) closeDrawer(); });

  const toggle = (id, on) => `<label class="rp-toggle"><input type="checkbox" data-k="${id}" ${on ? 'checked' : ''}><i></i></label>`;

  function renderDrawer() {
    const L = linux || { protons: [], checks: [], problems: [] };
    const win = L.platform === 'win';
    const opts = L.protons.map((p) => `<option value="${esc(p.path)}" ${p.path === L.proton ? 'selected' : ''}>${esc(p.name)}</option>`).join('');
    drawer.innerHTML = `
      <div class="rp-veil"></div>
      <div class="rp-panel">
        <div class="rp-head"><div><h3>${win ? 'Настройки лаунчера' : 'Linux-настройки'}</h3><small>GTA5RP Launcher ${win ? 'для Windows' : 'for Linux'} ${esc(L.version || '')}</small></div>
          <button class="rp-x" data-act="close" title="Закрыть (Esc)">✕</button></div>

        <div class="rp-sec"><h4>Запуск игры</h4>
          ${win ? '' : `<div class="rp-row"><span>Proton<small>чем запускать RAGE:MP и GTA V</small></span>
            <select class="rp-select" data-k="proton">${opts || '<option>не найден</option>'}</select></div>
          <div class="rp-row"><span>Папка GTA V</span><button class="rp-btn" data-act="gta">Выбрать…</button></div>
          <div class="rp-path">${esc(L.gta_path || 'не найдена')}</div>`}
          <div class="rp-row"><span>Сворачивать после запуска<small>окно уйдёт в панель задач</small></span>${toggle('close_on_play', L.close_on_play)}</div>
          ${win ? '' : `<div class="rp-row"><span>Подробный лог Proton<small>для поиска проблем</small></span>${toggle('debug_log', L.debug_log)}</div>`}
        </div>

        <div class="rp-sec"><h4>Состояние</h4>
          <div class="rp-checks">${L.checks.map((c) => `<div class="rp-check${c.ok ? ' ok' : ''}"><b>${esc(c.name)}</b><em>${esc(c.hint)}</em></div>`).join('')}</div>
          ${L.problems.length ? `<div class="rp-warn">${L.problems.map(esc).join('<br>')}</div>` : ''}
          <div class="rp-actions">
            ${win || (L.checks.find((c) => c.name === 'EasyAntiCheat Runtime') || {}).ok
              ? '<button class="rp-btn" data-act="refresh">Проверить снова</button>'
              : '<button class="rp-btn primary" data-act="eac">Установить античит</button>'}
            <button class="rp-btn" data-act="rage">Папка RAGE:MP</button>
            <button class="rp-btn" data-act="logs">Папка логов</button>
            <button class="rp-btn danger" data-act="kill">Закрыть игру</button>
          </div>
        </div>

        <div class="rp-sec"><h4>Оформление</h4>
          <div class="rp-row"><span>Фон под сервер<small>арт сервера за интерфейсом</small></span>${toggle('p:bg', prefs.bg)}</div>
          <div class="rp-row"><span>Яркость фона</span>
            <input class="rp-range" type="range" min="0.15" max="0.9" step="0.05" value="${prefs.strength}" data-k="p:strength"></div>
          <div class="rp-row"><span>Свет за курсором</span>${toggle('p:spot', prefs.spot)}</div>
          <div class="rp-row"><span>3D-наклон карточек</span>${toggle('p:tilt', prefs.tilt)}</div>
          <div class="rp-row"><span>Анимации<small>«Лёгкие» — для слабых ПК</small></span>
            <span class="rp-seg">${[['full', 'Полные'], ['lite', 'Лёгкие'], ['off', 'Выкл']].map(([v, t]) =>
              `<button data-motion="${v}" class="${prefs.motion === v ? 'on' : ''}">${t}</button>`).join('')}</span></div>
          <div class="rp-actions"><button class="rp-btn" data-act="classic">Простой интерфейс</button>
            <button class="rp-btn" data-act="reset">Сбросить оформление</button></div>
        </div>

        <div class="rp-foot">Интерфейс — оригинальный GTA5RP ${esc(L.official || '')}, взят из вашего установщика.
          Ядро, ${win ? 'запуск' : 'запуск через Proton'} и оформление — неофициальный лаунчер; с GTA5RP не связан.</div>
      </div>`;
  }

  async function openDrawer() {
    renderDrawer();
    drawer.classList.add('open');
    await loadLinux();
    if (drawer.classList.contains('open')) renderDrawer();
  }
  function closeDrawer() { drawer.classList.remove('open'); loadLinux(); }

  drawer.addEventListener('change', async (e) => {
    const k = e.target.dataset.k;
    if (!k) return;
    if (k.startsWith('p:')) {
      const name = k.slice(2);
      prefs[name] = e.target.type === 'checkbox' ? e.target.checked : +e.target.value;
      applyPrefs();
      if (name === 'bg') showBg(selected());
      return;
    }
    const v = e.target.type === 'checkbox' ? e.target.checked : e.target.value;
    const s = await bridge('setLinux', k, JSON.stringify(v));
    if (s) { linux = JSON.parse(s); renderDrawer(); renderSys(); }
  });
  drawer.addEventListener('input', (e) => {
    if (e.target.dataset.k === 'p:strength') { prefs.strength = +e.target.value; applyPrefs(); }
  });
  drawer.addEventListener('click', async (e) => {
    const m = e.target.closest('[data-motion]');
    if (m) { prefs.motion = m.dataset.motion; applyPrefs(); renderDrawer(); return; }
    const act = e.target.closest('[data-act]')?.dataset.act;
    if (!act) return;
    if (act === 'close') return closeDrawer();
    if (act === 'gta') { const s = await bridge('pickGtaPath'); if (s) { linux = JSON.parse(s); renderDrawer(); } }
    if (act === 'eac') bridge('installEac');
    if (act === 'refresh') { await loadLinux(); renderDrawer(); }
    if (act === 'rage') bridge('openRage');
    if (act === 'logs') bridge('openLogs');
    if (act === 'kill' && confirm('Принудительно закрыть RAGE:MP и GTA V?')) bridge('killGame');
    if (act === 'classic') bridge('restartClassic');
    if (act === 'reset') {
      Object.assign(prefs, { bg: true, strength: 0.55, spot: true, tilt: true, motion: 'full' });
      applyPrefs(); renderDrawer();
    }
  });

  // ------------------------------------------------------------ наблюдение за интерфейсом (React перерисовывает DOM)
  new MutationObserver((muts) => {
    mountSide();
    for (const m of muts) m.addedNodes.forEach((n) => { if (n.nodeType === 1) animateNew(n); });
    markSelected();
  }).observe(document.getElementById('root') || document.body, { childList: true, subtree: true });

  showBg(selected());
  mountSide();
  loadServers();
  loadLinux();
  setInterval(loadServers, 30000);
  setInterval(loadLinux, 20000);
})();
