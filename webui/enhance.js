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
  const THEMES = [
    ['original', 'Оригинальная', '🟠'], ['zxc', 'zxc · dead inside', '🥀'], ['barbie', 'Барби', '💖'],
    ['vibe', 'Вайб-кодер', '⌨️'], ['vice', 'Vice City', '🌴'], ['casino', 'Diamond Casino', '💎'],
  ];
  const prefs = Object.assign({ bg: true, strength: 0.55, spot: true, tilt: true, motion: 'full', theme: 'original' },
    (() => { try { return JSON.parse(ls.get(K_PREFS, '{}')); } catch { return {}; } })());
  function applyPrefs() {
    const h = document.documentElement;
    h.classList.toggle('rp-nobg', !prefs.bg);
    h.classList.toggle('rp-nospot', !prefs.spot);
    h.classList.toggle('rp-lite', prefs.motion === 'lite');
    h.classList.toggle('rp-still', prefs.motion === 'off');
    h.style.setProperty('--rp-strength', String(prefs.strength));
    if (prefs.theme && prefs.theme !== 'original') h.dataset.rpTheme = prefs.theme; else delete h.dataset.rpTheme;
    ls.set(K_PREFS, JSON.stringify(prefs));
  }
  const serverTint = () => !prefs.theme || prefs.theme === 'original';
  applyPrefs();

  // ------------------------------------------------------------ фон
  const bg = document.createElement('div');
  bg.id = 'rp-bg';
  bg.innerHTML = '<div class="rp-img"></div><div class="rp-img"></div>' +
    '<div class="rp-aurora"><i></i><i></i><i></i></div><div class="rp-shade"></div>' +
    '<div id="rp-fxdom"></div><canvas id="rp-fx"></canvas>' +
    '<div class="rp-spot"></div><div class="rp-grain"></div>';
  document.body.prepend(bg);
  const [imgA, imgB] = bg.querySelectorAll('.rp-img');
  let front = imgA, current = '', want = '';

  // у тем (кроме оригинальной) свой арт на фоне — webui/themes/<тема>.webp
  const themeArt = () => (prefs.theme && prefs.theme !== 'original' && window.__rpAssets)
    ? `${window.__rpAssets}/themes/${prefs.theme}.webp` : '';

  function showBg(url) {
    const art = themeArt();
    url = art || url || DEFAULT_BG;
    want = url;
    if (url === current) return;
    const img = new Image();
    img.onload = () => {
      if (want !== url) return;
      current = url;
      const back = front === imgA ? imgB : imgA;
      back.style.backgroundImage = `url("${url}")`;
      back.classList.toggle('art', !!art);
      back.classList.add('on');
      front.classList.remove('on');
      front = back;
    };
    img.src = url;
    if (!serverTint()) {
      document.documentElement.style.removeProperty('--rp-c');
    } else if (isServerBg(url) && window.__rpTheme) {
      window.__rpTheme(url).then((c) => { if (want === url && c && serverTint()) document.documentElement.style.setProperty('--rp-c', c); });
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


  // ------------------------------------------------------------ анимации тем (canvas)
  const cv = bg.querySelector('#rp-fx'), cx = cv.getContext('2d'), fxdom = bg.querySelector('#rp-fxdom');
  let fxRaf = 0, fxTimers = [], W = 0, H = 0, last = 0;
  const rnd = (a, b) => a + Math.random() * (b - a);
  function fitCanvas() {
    const d = Math.min(window.devicePixelRatio || 1, 2);
    W = innerWidth; H = innerHeight; cv.width = W * d; cv.height = H * d; cx.setTransform(d, 0, 0, d, 0, 0);
  }
  addEventListener('resize', fitCanvas);
  fitCanvas();
  const lite = () => prefs.motion === 'lite';
  const many = (n) => Math.round(lite() ? n * 0.45 : n);

  const PALM = '<svg viewBox="0 0 100 160" class="rp-vice-palm %C"><path d="M52 160c-3-40-2-80 2-112l4 1c-3 31-4 70-1 111z"/>' +
    '<path d="M55 50C40 30 18 28 2 40c18-4 34 0 50 12zM56 49c4-22 20-36 40-38-14 8-26 20-34 40zM55 52c18-12 38-10 45 4-14-6-28-6-43 0zM54 51C46 36 30 24 10 22c16 8 30 18 40 32zM56 50c-6-18-2-36 10-48-6 16-6 32-6 48z"/></svg>';

  const FX = {
    zxc: {
      init() {
        this.p = Array.from({ length: many(28) }, () => this.petal(true));
        this.nums = []; this.n = 1000;
        fxTimers.push(setInterval(() => {
          this.nums.push({ x: W * rnd(0.55, 0.8), y: H * rnd(0.55, 0.95), a: 1, t: `${this.n} − 7 = ${this.n - 7}` });
          this.n = this.n - 7 < 7 ? 1000 : this.n - 7;
        }, lite() ? 1600 : 850));
        const glitch = () => {
          document.documentElement.classList.add('rp-glitch');
          setTimeout(() => document.documentElement.classList.remove('rp-glitch'), 340);
          fxTimers.push(setTimeout(glitch, rnd(2600, 6500)));
        };
        fxTimers.push(setTimeout(glitch, 1800));
      },
      petal(start) {
        return { x: rnd(0, W), y: start ? rnd(-H, H) : rnd(-80, -20), vy: rnd(18, 42), vx: rnd(-8, 8), r: rnd(0, 6.3),
                 vr: rnd(-1.2, 1.2), s: rnd(7, 15), ph: rnd(0, 6.3) };
      },
      frame(dt, t) {
        cx.clearRect(0, 0, W, H);
        for (const p of this.p) {
          p.y += p.vy * dt; p.x += (p.vx + Math.sin(t / 900 + p.ph) * 14) * dt; p.r += p.vr * dt;
          if (p.y > H + 30) Object.assign(p, this.petal(false));
          cx.save(); cx.translate(p.x, p.y); cx.rotate(p.r);
          const g = cx.createLinearGradient(0, -p.s, 0, p.s);
          g.addColorStop(0, 'rgba(255,60,80,.95)'); g.addColorStop(1, 'rgba(120,0,20,.85)');
          cx.fillStyle = g; cx.beginPath();
          cx.moveTo(0, -p.s); cx.quadraticCurveTo(p.s * 0.55, -p.s * 0.2, 0, p.s);
          cx.quadraticCurveTo(-p.s * 0.25, 0, 0, -p.s); cx.fill(); cx.restore();
        }
        cx.font = '600 14px "JetBrains Mono", "DejaVu Sans Mono", monospace';
        this.nums = this.nums.filter((n) => n.a > 0);
        for (const n of this.nums) {
          n.y -= 16 * dt; n.a -= 0.16 * dt;
          cx.fillStyle = `rgba(235,235,235,${Math.max(0, n.a) * 0.55})`;
          cx.fillText(n.t, n.x, n.y);
        }
      },
    },
    barbie: {
      init() {
        this.s = Array.from({ length: many(70) }, () => ({ x: rnd(0, W), y: rnd(0, H), z: rnd(2, 6), ph: rnd(0, 6.3), sp: rnd(1.5, 4) }));
        this.h = Array.from({ length: many(16) }, () => this.heart(true));
      },
      heart(start) { return { x: rnd(W * 0.2, W), y: start ? rnd(0, H) : H + 30, v: rnd(16, 38), s: rnd(8, 18), ph: rnd(0, 6.3) }; },
      frame(dt, t) {
        cx.clearRect(0, 0, W, H);
        for (const s of this.s) {
          const a = Math.max(0, Math.sin(t / 1000 * s.sp + s.ph));
          if (a < 0.05) continue;
          const r = s.z * a;
          cx.fillStyle = `rgba(255,${200 + 55 * a | 0},240,${a})`;
          cx.beginPath(); cx.moveTo(s.x, s.y - r * 2); cx.quadraticCurveTo(s.x, s.y, s.x + r * 2, s.y);
          cx.quadraticCurveTo(s.x, s.y, s.x, s.y + r * 2); cx.quadraticCurveTo(s.x, s.y, s.x - r * 2, s.y);
          cx.quadraticCurveTo(s.x, s.y, s.x, s.y - r * 2); cx.fill();
        }
        for (const h of this.h) {
          h.y -= h.v * dt; const x = h.x + Math.sin(t / 700 + h.ph) * 12;
          if (h.y < -30) Object.assign(h, this.heart(false));
          const a = Math.min(1, h.y / H + 0.15) * 0.7, s = h.s;
          cx.fillStyle = `rgba(255,70,170,${a})`; cx.beginPath();
          cx.moveTo(x, h.y + s * 0.3);
          cx.bezierCurveTo(x, h.y - s * 0.3, x - s, h.y - s * 0.3, x - s, h.y + s * 0.15);
          cx.bezierCurveTo(x - s, h.y + s * 0.6, x, h.y + s * 0.85, x, h.y + s);
          cx.bezierCurveTo(x, h.y + s * 0.85, x + s, h.y + s * 0.6, x + s, h.y + s * 0.15);
          cx.bezierCurveTo(x + s, h.y - s * 0.3, x, h.y - s * 0.3, x, h.y + s * 0.3); cx.fill();
        }
      },
    },
    vibe: {
      init() {
        this.chars = '01{}<>=;()[]λ=>constletasyncawaitvibe∑≠ｱｲｳｴｵｶｷｸ';
        this.cols = Array.from({ length: Math.ceil(W / 16) }, () => rnd(-H, 0));
        cx.clearRect(0, 0, W, H);
      },
      frame(dt) {
        cx.globalCompositeOperation = 'destination-out';
        cx.fillStyle = `rgba(0,0,0,${lite() ? 0.2 : 0.11})`; cx.fillRect(0, 0, W, H);
        cx.globalCompositeOperation = 'source-over';
        cx.font = '15px "JetBrains Mono", "DejaVu Sans Mono", monospace';
        this.cols.forEach((y, i) => {
          const ch = this.chars[(Math.random() * this.chars.length) | 0];
          cx.fillStyle = Math.random() < 0.08 ? 'rgba(220,255,235,.95)' : 'rgba(40,255,130,.75)';
          cx.fillText(ch, i * 16, y);
          this.cols[i] = y > H + rnd(0, 400) ? rnd(-200, 0) : y + 16 * (dt * 60) * 0.45;
        });
      },
    },
    vice: {
      init() {
        fxdom.innerHTML = '<div class="rp-vice-sun"></div><div class="rp-vice-grid"></div>' +
          PALM.replace('%C', 'l') + PALM.replace('%C', 'r');
        this.st = Array.from({ length: many(60) }, () => ({ x: rnd(0, W), y: rnd(0, H * 0.6), ph: rnd(0, 6.3), s: rnd(.6, 1.8) }));
      },
      frame(dt, t) {
        cx.clearRect(0, 0, W, H);
        for (const s of this.st) {
          const a = 0.3 + 0.7 * Math.abs(Math.sin(t / 1300 + s.ph));
          cx.fillStyle = `rgba(${s.ph > 3 ? '54,226,255' : '255,140,220'},${a})`;
          cx.fillRect(s.x, s.y, s.s, s.s);
        }
      },
    },
    casino: {
      init() {
        this.d = Array.from({ length: many(90) }, () => this.dust(true));
        this.g = Array.from({ length: many(7) }, () => ({ x: rnd(W * .3, W), y: rnd(0, H), ph: rnd(0, 6.3), s: rnd(10, 22) }));
      },
      dust(start) { return { x: rnd(0, W), y: start ? rnd(0, H) : H + 10, v: rnd(8, 26), r: rnd(.6, 2.2), ph: rnd(0, 6.3) }; },
      frame(dt, t) {
        cx.clearRect(0, 0, W, H);
        cx.globalCompositeOperation = 'lighter';
        for (const d of this.d) {
          d.y -= d.v * dt; d.x += Math.sin(t / 1500 + d.ph) * 6 * dt;
          if (d.y < -10) Object.assign(d, this.dust(false));
          const a = 0.35 + 0.45 * Math.abs(Math.sin(t / 900 + d.ph));
          cx.fillStyle = `rgba(255,214,120,${a})`; cx.beginPath(); cx.arc(d.x, d.y, d.r, 0, 6.3); cx.fill();
        }
        for (const g of this.g) {
          const a = Math.max(0, Math.sin(t / 1400 + g.ph)) ** 3, s = g.s * a;
          if (a < 0.03) continue;
          cx.strokeStyle = `rgba(255,240,200,${a * .9})`; cx.lineWidth = 1.2;
          cx.beginPath(); cx.moveTo(g.x - s, g.y); cx.lineTo(g.x + s, g.y); cx.moveTo(g.x, g.y - s); cx.lineTo(g.x, g.y + s); cx.stroke();
          cx.save(); cx.translate(g.x, g.y); cx.rotate(.785); cx.strokeRect(-s * .18, -s * .18, s * .36, s * .36); cx.restore();
        }
        cx.globalCompositeOperation = 'source-over';
      },
    },
  };

  function stopFx() {
    cancelAnimationFrame(fxRaf); fxRaf = 0;
    fxTimers.forEach((x) => { clearInterval(x); clearTimeout(x); }); fxTimers = [];
    fxdom.innerHTML = ''; cx.clearRect(0, 0, W, H);
    document.documentElement.classList.remove('rp-glitch');
  }
  function startFx() {
    stopFx();
    const f = FX[prefs.theme];
    if (!f) return;
    f.init();
    if (prefs.motion === 'off') { f.frame(0.016, 0); return; }
    last = performance.now();
    const step = (now) => {
      fxRaf = requestAnimationFrame(step);
      if (lite() && now - last < 33) return;  // «Лёгкие» — ~30 кадров
      const dt = Math.min(0.05, (now - last) / 1000); last = now;
      f.frame(dt, now);
    };
    fxRaf = requestAnimationFrame(step);
  }
  function setTheme(name) {
    if (!THEMES.some(([k]) => k === name)) return;
    prefs.theme = name; applyPrefs(); startFx();
    current = ''; showBg(selected());  // перерисовать фон и цвет под новую тему
  }
  window.__rpSetTheme = setTheme;

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

        <div class="rp-sec"><h4>Тема</h4>
          <div class="rp-themes">${THEMES.map(([k, n, i]) =>
            `<button class="rp-theme${prefs.theme === k ? ' on' : ''}" data-theme="${k}"><i>${i}</i>${esc(n)}</button>`).join('')}</div>
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
    if (m) { prefs.motion = m.dataset.motion; applyPrefs(); startFx(); renderDrawer(); return; }
    const th = e.target.closest('[data-theme]');
    if (th) { setTheme(th.dataset.theme); renderDrawer(); return; }
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
      Object.assign(prefs, { bg: true, strength: 0.55, spot: true, tilt: true, motion: 'full', theme: 'original' });
      applyPrefs(); startFx(); renderDrawer();
    }
  });

  // ------------------------------------------------------------ наблюдение за интерфейсом (React перерисовывает DOM)
  new MutationObserver((muts) => {
    mountSide();
    for (const m of muts) m.addedNodes.forEach((n) => { if (n.nodeType === 1) animateNew(n); });
    markSelected();
  }).observe(document.getElementById('root') || document.body, { childList: true, subtree: true });

  // выбор сервера без клика по карточке (клик в оригинале сразу запускает игру)
  window.__rpSelectServer = (url) => {
    if (!isServerBg(url)) return;
    ls.set(K_SERVER, url); showBg(url); markSelected(); renderServer();
  };

  showBg(selected());
  startFx();
  mountSide();
  loadServers();
  loadLinux();
  setInterval(loadServers, 30000);
  setInterval(loadLinux, 20000);
})();
