/* clipped website - motion and small behaviours.
   Ported from evzero's site.js: curtain, Lenis smooth scroll, cursor + ambient
   light, glow cards, per-letter blur-in, reveals, count-up, scramble, flip
   words, magnetic buttons, warp field, scrubbed motion, chapter dock.
   Plus the live caption demo in the hero and OS-aware download buttons.
   No tracking, no cookies. */
(function () {
  'use strict';
  var doc = document.documentElement;
  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var finePointer = window.matchMedia('(hover: hover) and (pointer: fine)');
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var clamp = function (v, a, b) { return Math.min(b, Math.max(a, v)); };
  var lenis = null;

  // ---------- scroll hub
  var scrollFns = [];
  var queued = false;
  function onScroll(fn) { scrollFns.push(fn); }
  function queueScroll() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(function () { queued = false; var y = window.scrollY; scrollFns.forEach(function (fn) { fn(y); }); });
  }
  window.addEventListener('scroll', queueScroll, { passive: true });
  window.addEventListener('resize', queueScroll);

  function initSmoothScroll() {
    if (reduceMotion || typeof window.Lenis !== 'function') return;
    lenis = new window.Lenis({ duration: 1.15, easing: function (t) { return 1 - Math.pow(1 - t, 4); } });
    (function raf(t) { lenis.raf(t); requestAnimationFrame(raf); })(performance.now());
    $$('a[href^="#"]').forEach(function (a) {
      a.addEventListener('click', function (e) {
        var id = a.getAttribute('href');
        var el = id.length > 1 && $(id);
        if (!el) return;
        e.preventDefault();
        lenis.scrollTo(el, { offset: -20 });
      });
    });
  }

  // ---------- curtain
  function fontsReady(cap) {
    var ready = document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve();
    return Promise.race([ready, new Promise(function (r) { setTimeout(r, cap); })]);
  }
  var readyFns = [];
  function onReady(fn) { if (doc.classList.contains('is-ready')) fn(); else readyFns.push(fn); }
  function markReady() {
    if (doc.classList.contains('is-ready')) return;
    doc.classList.add('is-ready');
    readyFns.forEach(function (fn) { fn(); });
  }
  function initCurtain() {
    clearTimeout(window.clippedFailsafe);
    var loader = $('.loader');
    if (!loader) return markReady();
    var fresh = false;
    if ($('.loader-welcome', loader) && !reduceMotion) {
      try { fresh = !sessionStorage.getItem('clipped-site-welcomed'); sessionStorage.setItem('clipped-site-welcomed', '1'); } catch (e) { /* blocked */ }
    }
    if (!fresh) {
      fontsReady(650).then(function () { setTimeout(markReady, 80); });
      setTimeout(markReady, 1500);
      return;
    }
    fontsReady(2000).then(function () {
      setTimeout(function () {
        loader.classList.add('is-welcome');
        setTimeout(function () { loader.classList.add('is-out'); setTimeout(markReady, 280); }, 2000);
      }, 700);
    });
    setTimeout(markReady, 7000);
  }
  // page changes: sweep the curtain in, then navigate
  function initTransitions() {
    $$('a[data-transition]').forEach(function (a) {
      a.addEventListener('click', function (e) {
        if (e.metaKey || e.ctrlKey || e.shiftKey || reduceMotion) return;
        e.preventDefault();
        doc.classList.add('is-leaving');
        setTimeout(function () { window.location.href = a.href; }, 650);
      });
    });
    window.addEventListener('pageshow', function (e) { if (e.persisted) doc.classList.remove('is-leaving'); });
  }

  // ---------- sticker
  var INK = '#0d0b14', P1 = '#8a78f0', P2 = '#b4a5ff', LAV = '#dcd6ff', DEEP = '#4c3aa8', WHITE = '#f6f3ee';
  var STICKER = '<svg class="stk-svg" viewBox="0 0 200 200" aria-hidden="true" focusable="false">' +
    '<g fill="' + WHITE + '" stroke="' + WHITE + '" stroke-width="22" stroke-linejoin="round"><rect x="50" y="18" width="100" height="164" rx="24"/></g>' +
    '<g stroke="' + INK + '" stroke-width="7" stroke-linejoin="round" stroke-linecap="round">' +
    '<rect x="50" y="18" width="100" height="164" rx="24" fill="' + P1 + '"/>' +
    '<rect x="64" y="36" width="72" height="96" rx="12" fill="' + INK + '" stroke="' + LAV + '" stroke-width="5"/>' +
    '<path d="M90 66L114 84L90 102Z" fill="' + WHITE + '" stroke="none"/>' +
    '<rect x="62" y="144" width="76" height="20" rx="10" fill="' + LAV + '"/>' +
    '<rect x="70" y="150" width="22" height="8" rx="4" fill="' + DEEP + '" stroke="none"/>' +
    '<rect x="98" y="150" width="32" height="8" rx="4" fill="' + P2 + '" stroke="none"/></g></svg>';
  function initStickers() { $$('[data-sticker]').forEach(function (el) { if (!el.firstElementChild) el.innerHTML = STICKER; }); }

  // ---------- cursor
  function initCursor() {
    var dot = document.createElement('div'); dot.className = 'cursor-dot';
    var ring = document.createElement('div'); ring.className = 'cursor-ring';
    var label = document.createElement('span'); label.className = 'cursor-label'; ring.appendChild(label);
    var ambient = document.createElement('div'); ambient.className = 'ambient';
    document.body.append(ambient, dot, ring);
    var evaluate = function () { doc.classList.toggle('has-cursor', finePointer.matches && window.innerWidth > 860 && !reduceMotion); };
    evaluate();
    window.addEventListener('resize', evaluate);
    var mx = -100, my = -100, rx = -100, ry = -100, ax = -100, ay = -100, seen = false, raf = 0;
    function tick() {
      rx += (mx - rx) * 0.18; ry += (my - ry) * 0.18; ax += (mx - ax) * 0.06; ay += (my - ay) * 0.06;
      ring.style.transform = 'translate3d(' + rx.toFixed(2) + 'px,' + ry.toFixed(2) + 'px,0)';
      ambient.style.transform = 'translate3d(' + ax.toFixed(1) + 'px,' + ay.toFixed(1) + 'px,0)';
      raf = Math.abs(mx - ax) > 0.5 || Math.abs(my - ay) > 0.5 ? requestAnimationFrame(tick) : 0;
    }
    window.addEventListener('mousemove', function (e) {
      mx = e.clientX; my = e.clientY;
      if (!seen) { seen = true; rx = ax = mx; ry = ay = my; doc.classList.add('cursor-seen'); }
      doc.classList.remove('cursor-out');
      dot.style.transform = 'translate3d(' + mx + 'px,' + my + 'px,0)';
      if (!raf) raf = requestAnimationFrame(tick);
    }, { passive: true });
    document.addEventListener('mouseleave', function () { doc.classList.add('cursor-out'); });
    var hoverables = 'a, button, summary, input, label, [role="button"]';
    document.addEventListener('mouseover', function (e) {
      var t = e.target;
      if (!t || !t.closest) return;
      var labelled = t.closest('[data-cursor-label]');
      if (labelled) { label.textContent = labelled.getAttribute('data-cursor-label'); ring.classList.add('has-label'); ring.classList.remove('hover'); return; }
      ring.classList.remove('has-label');
      ring.classList.toggle('hover', !!t.closest(hoverables));
    });
  }

  // ---------- text
  function textNodes(root) {
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT), nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    return nodes;
  }
  function splitChars(el) {
    var text = el.textContent.replace(/\s+/g, ' ').trim();
    if (!text) return;
    var vis = document.createElement('span'); vis.className = 'split-vis'; vis.setAttribute('aria-hidden', 'true');
    while (el.firstChild) vis.appendChild(el.firstChild);
    var sr = document.createElement('span'); sr.className = 'sr-only'; sr.textContent = text;
    el.append(sr, vis);
    var i = 0;
    textNodes(vis).forEach(function (node) {
      var frag = document.createDocumentFragment();
      node.nodeValue.split(/(\s+)/).forEach(function (part) {
        if (!part) return;
        if (/^\s+$/.test(part)) { frag.appendChild(document.createTextNode(' ')); return; }
        var w = document.createElement('span'); w.className = 'w';
        Array.from(part).forEach(function (ch) {
          var c = document.createElement('span'); c.className = 'ch'; c.textContent = ch;
          c.style.setProperty('--y', ((Math.random() * 2 - 1) * 0.35).toFixed(3) + 'em');
          c.style.setProperty('--s', (0.55 + Math.random() * 1.1).toFixed(3));
          c.style.setProperty('--b', (6 + Math.random() * 10).toFixed(1) + 'px');
          c.style.setProperty('--cd', (Math.random() * 0.45 + i * 0.012).toFixed(3) + 's');
          w.appendChild(c); i++;
        });
        frag.appendChild(w);
      });
      node.parentNode.replaceChild(frag, node);
    });
  }
  var GLYPHS = '!<>-_\\/[]{}=+*^?#01';
  function scramble(el) {
    var final = el.getAttribute('data-text') || el.textContent;
    el.setAttribute('data-text', final);
    var frame = 0;
    clearInterval(el._sc);
    el._sc = setInterval(function () {
      frame++;
      var solved = (frame / 14) * final.length;
      el.textContent = final.split('').map(function (ch, i) { return (ch === ' ' || i < solved) ? ch : GLYPHS[(Math.random() * GLYPHS.length) | 0]; }).join('');
      if (frame >= 14) { clearInterval(el._sc); el.textContent = final; }
    }, 34);
  }
  function initScramble() {
    if (reduceMotion) return;
    $$('[data-scramble]').forEach(function (el) { (el.closest('a, button') || el).addEventListener('mouseenter', function () { scramble(el); }); });
  }
  function initFlip() {
    $$('[data-flip]').forEach(function (el) {
      var words = el.getAttribute('data-flip').split('|');
      el.classList.add('flip');
      el.innerHTML = '<span></span>';
      var inner = el.firstElementChild;
      inner.textContent = words[0];
      if (reduceMotion || words.length < 2) return;
      var i = 0;
      setInterval(function () {
        if (document.hidden) return;
        i = (i + 1) % words.length;
        el.classList.remove('in'); el.classList.add('out');
        setTimeout(function () { inner.textContent = words[i]; el.classList.remove('out'); el.classList.add('in'); }, 430);
      }, 2800);
    });
  }

  // ---------- reveals + count-up
  function countUp(el) {
    var end = parseFloat(el.getAttribute('data-count'));
    if (!isFinite(end) || reduceMotion) { el.textContent = end; return; }
    var t0 = performance.now();
    (function frame(now) {
      var p = clamp((now - t0) / 1500, 0, 1);
      el.textContent = Math.round(end * (1 - Math.pow(1 - p, 4)));
      if (p < 1) requestAnimationFrame(frame);
    })(t0);
  }
  function initReveals() {
    if (!('IntersectionObserver' in window)) return;
    doc.classList.add('reveal-on');
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        var el = en.target;
        el.classList.add('is-in');
        io.unobserve(el);
        if (el.hasAttribute('data-count')) countUp(el);
      });
    }, { rootMargin: '0px 0px -8% 0px' });
    onReady(function () { $$('.reveal, .kicker, [data-split], [data-count]').forEach(function (el) { io.observe(el); }); });
  }

  // ---------- glow + magnetic
  function initGlow() {
    if (!finePointer.matches) return;
    var px = -9999, py = -9999, q = false;
    function update() {
      q = false;
      var vh = window.innerHeight;
      $$('.glow').forEach(function (c) {
        var r = c.getBoundingClientRect();
        if (r.bottom < -120 || r.top > vh + 120) return;
        var dx = Math.max(r.left - px, 0, px - r.right), dy = Math.max(r.top - py, 0, py - r.bottom);
        c.style.setProperty('--gx', (px - r.left).toFixed(1) + 'px');
        c.style.setProperty('--gy', (py - r.top).toFixed(1) + 'px');
        c.style.setProperty('--ga', clamp(1 - Math.hypot(dx, dy) / 170, 0, 1).toFixed(3));
      });
    }
    function queue() { if (!q) { q = true; requestAnimationFrame(update); } }
    window.addEventListener('pointermove', function (e) { px = e.clientX; py = e.clientY; queue(); }, { passive: true });
    onScroll(queue);
  }
  function initMagnetic() {
    if (reduceMotion) return;
    $$('[data-magnetic]').forEach(function (el) {
      var k = parseFloat(el.getAttribute('data-magnetic')) || 0.28;
      el.addEventListener('mousemove', function (e) {
        if (!finePointer.matches) return;
        var r = el.getBoundingClientRect();
        el.style.translate = ((e.clientX - r.left - r.width / 2) * k).toFixed(1) + 'px ' + ((e.clientY - r.top - r.height / 2) * k).toFixed(1) + 'px';
      });
      el.addEventListener('mouseleave', function () { el.style.translate = ''; });
    });
  }

  // ---------- warp field
  function initWarp() {
    $$('[data-warp]').forEach(function (host) {
      var aurora = document.createElement('div'); aurora.className = 'aurora'; aurora.innerHTML = '<i></i><i></i><i></i>';
      var canvas = document.createElement('canvas');
      host.append(aurora, canvas);
      var ctx = canvas.getContext('2d');
      if (!ctx) return;
      var COUNT = window.innerWidth < 700 ? 150 : 300, stars = [];
      function spawn(s, anywhere) { s.x = Math.random() * 2 - 1; s.y = Math.random() * 2 - 1; s.z = anywhere ? Math.random() * 0.95 + 0.05 : 1; s.tint = Math.random(); }
      for (var i = 0; i < COUNT; i++) { var s = {}; spawn(s, true); stars.push(s); }
      var w = 0, h = 0, dpr = 1;
      function resize() { dpr = Math.min(window.devicePixelRatio || 1, 1.6); w = host.clientWidth; h = host.clientHeight; canvas.width = Math.max(1, Math.round(w * dpr)); canvas.height = Math.max(1, Math.round(h * dpr)); }
      resize();
      window.addEventListener('resize', resize);
      var boost = 0, px = 0, py = 0, tx = 0, ty = 0;
      window.addEventListener('mousemove', function (e) { tx = e.clientX / window.innerWidth - 0.5; ty = e.clientY / window.innerHeight - 0.5; }, { passive: true });
      function draw(speed) {
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, w, h);
        var cx = w / 2 - px * 60, cy = h * 0.48 - py * 40, k = Math.max(w, h) * 0.62;
        ctx.lineCap = 'round';
        stars.forEach(function (s) {
          var z0 = s.z;
          s.z -= speed;
          if (s.z <= 0.02) { spawn(s, false); return; }
          var x1 = cx + (s.x / s.z) * k, y1 = cy + (s.y / s.z) * k;
          if (x1 < -40 || x1 > w + 40 || y1 < -40 || y1 > h + 40) { spawn(s, false); return; }
          var zt = Math.min(1, z0 + speed * 3), x0 = cx + (s.x / zt) * k, y0 = cy + (s.y / zt) * k, near = 1 - s.z;
          ctx.strokeStyle = s.tint > 0.62 ? 'rgba(180,165,255,' + (near * 0.9).toFixed(3) + ')' : 'rgba(243,240,234,' + (near * 0.7).toFixed(3) + ')';
          ctx.lineWidth = 0.4 + near * 1.5;
          ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
        });
      }
      if (reduceMotion) { draw(0); return; }
      var visible = true, running = false;
      function tick() {
        if (!visible || document.hidden) { running = false; return; }
        px += (tx - px) * 0.04; py += (ty - py) * 0.04;
        var v = lenis ? Math.abs(lenis.velocity || 0) : 0;
        boost = Math.max(boost * 0.955, Math.min(0.03, v * 0.0006));
        draw(0.0011 + boost);
        requestAnimationFrame(tick);
      }
      function start() { if (!running) { running = true; requestAnimationFrame(tick); } }
      if ('IntersectionObserver' in window) new IntersectionObserver(function (en) { visible = en[0].isIntersecting; if (visible) start(); }).observe(host);
      document.addEventListener('visibilitychange', function () { if (!document.hidden) start(); });
      draw(0);
      onReady(function () { boost = 0.05; start(); });
    });
  }

  // ---------- scrubbed motion + topbar
  function initScrub() {
    var els = $$('[data-scrub]');
    if (!els.length || reduceMotion) return;
    onScroll(function () {
      var vh = window.innerHeight;
      els.forEach(function (el) {
        var r = el.getBoundingClientRect();
        el.style.setProperty('--p', clamp((vh - r.top) / (vh + r.height), 0, 1).toFixed(4));
      });
    });
  }
  function initTopbar() {
    var bar = $('.topbar');
    if (bar) onScroll(function (y) { bar.classList.toggle('is-scrolled', y > 24); });
  }

  // ---------- chapter dock
  function initDock() {
    var chapters = $$('[data-chapter]');
    if (chapters.length < 2) return;
    var pad = function (n) { return String(n).padStart(2, '0'); };
    var dock = document.createElement('div');
    dock.className = 'dock';
    dock.innerHTML = '<div class="dock-list" role="menu">' + chapters.map(function (c, i) {
      return '<button type="button" role="menuitem"><span>' + pad(i + 1) + '</span><span>' + c.getAttribute('data-chapter') + '</span></button>';
    }).join('') + '</div><button type="button" class="dock-pill" aria-expanded="false" aria-label="Sections on this page">' +
      '<span class="dock-idx">01</span><span class="dock-name"><span></span></span>' +
      '<span class="dock-ring" aria-hidden="true"><svg viewBox="0 0 34 34"><circle cx="17" cy="17" r="16"/></svg><i></i></span></button>';
    document.body.appendChild(dock);
    var pill = $('.dock-pill', dock), idx = $('.dock-idx', dock), name = $('.dock-name', dock), circle = $('circle', dock), items = $$('.dock-list button', dock);
    var C = 2 * Math.PI * 16;
    circle.style.strokeDasharray = C;
    function setOpen(o) { dock.classList.toggle('open', o); pill.setAttribute('aria-expanded', String(o)); }
    pill.addEventListener('click', function () { setOpen(!dock.classList.contains('open')); });
    items.forEach(function (b, i) {
      b.addEventListener('click', function () {
        setOpen(false);
        if (lenis) lenis.scrollTo(chapters[i], { offset: -10 }); else chapters[i].scrollIntoView({ behavior: 'smooth' });
      });
    });
    document.addEventListener('click', function (e) { if (!dock.contains(e.target)) setOpen(false); });
    var current = -1;
    onScroll(function (y) {
      var vh = window.innerHeight, at = 0;
      chapters.forEach(function (c, i) { if (c.getBoundingClientRect().top <= vh * 0.5) at = i; });
      var max = Math.max(1, doc.scrollHeight - vh);
      circle.style.strokeDashoffset = (C * (1 - clamp(y / max, 0, 1))).toFixed(2);
      if (at === current) return;
      current = at;
      idx.textContent = pad(at + 1);
      name.firstElementChild.textContent = chapters[at].getAttribute('data-chapter');
      name.classList.remove('swap'); void name.offsetWidth; name.classList.add('swap');
      items.forEach(function (b, j) { b.classList.toggle('active', j === at); });
    });
    queueScroll();
  }

  // ---------- hero caption demo (karaoke, like the burned-in captions)
  function initCaptionDemo() {
    var caps = $('#demo-caps'), hook = $('#demo-hook'), bar = $('#demo-progress');
    if (!caps) return;
    var pages = [['okay', 'watch', 'this'], ['he’s', 'going', 'for it'], ['wait', 'wait', 'wait'], ['NO', 'WAY!'], ['clutch!'], ['that', 'was', 'insane']];
    var p = 0, w = 0, t0 = performance.now(), LOOP = 14000;
    function render() {
      caps.innerHTML = pages[p].map(function (word, i) { return '<span' + (i === w ? ' class="hl"' : '') + '>' + word + '</span>'; }).join(' ');
    }
    function step() {
      w++;
      if (w >= pages[p].length) { w = 0; p = (p + 1) % pages.length; caps.classList.remove('swap'); void caps.offsetWidth; caps.classList.add('swap'); }
      if (p === 0 && w === 0) { t0 = performance.now(); hookFlash(); }
      render();
    }
    function hookFlash() { hook.classList.add('on'); setTimeout(function () { hook.classList.remove('on'); }, 2000); }
    render();
    if (reduceMotion) return;
    onReady(function () {
      hookFlash();
      setInterval(step, 420);
      (function prog() { bar.style.width = (((performance.now() - t0) % LOOP) / LOOP * 100).toFixed(2) + '%'; requestAnimationFrame(prog); })();
    });
  }

  // ---------- downloads: highlight the visitor's OS
  function initDownloads() {
    var ua = navigator.userAgent || '';
    var plat = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || '';
    var os = /Win/i.test(plat) || /Windows/i.test(ua) ? 'windows' : /Mac/i.test(plat) || /Mac OS X/i.test(ua) ? 'mac-arm' : (/Linux/i.test(plat) && !/Android/i.test(ua)) ? 'linux' : null;
    if (!os) return;
    var card = $('.dl[data-os="' + os + '"]');
    if (card) card.classList.add('recommended');
    var hero = $('#hero-download'), label = $('#hero-download-label');
    var names = { windows: 'Download for Windows', 'mac-arm': 'Download for macOS', linux: 'Download for Linux' };
    if (hero && card) { hero.href = card.href; label.textContent = names[os]; }
  }

  initStickers();
  initSmoothScroll();
  initCurtain();
  initTransitions();
  initCursor();
  $$('[data-split]').forEach(splitChars);
  initScramble();
  initFlip();
  initReveals();
  initGlow();
  initMagnetic();
  initWarp();
  initScrub();
  initTopbar();
  initDock();
  initCaptionDemo();
  initDownloads();
  queueScroll();
})();
