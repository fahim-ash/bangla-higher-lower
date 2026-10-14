(() => {
  const $ = (id) => document.getElementById(id);
  const HS_KEY = "hl-bd-highscore";

  let items = [];
  let deck = [];
  let left, right, next;
  let score = 0;
  let busy = false;

  const fmt = (n) => Math.round(n).toLocaleString("en-US");
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function getHigh() {
    try { return Number(localStorage.getItem(HS_KEY)) || 0; } catch { return 0; }
  }
  function setHigh(v) {
    try { localStorage.setItem(HS_KEY, String(v)); } catch { /* storage unavailable */ }
  }

  function shuffle(a) {
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  }

  // Draw the next item, never one that is currently on screen.
  function draw() {
    const onScreen = new Set([left, right, next].filter(Boolean).map((i) => i.id));
    if (!deck.length) deck = shuffle(items.filter((i) => !onScreen.has(i.id)));
    const item = deck.pop();
    new Image().src = item.image; // preload
    return item;
  }

  function show(screen) {
    document.querySelectorAll(".screen").forEach((s) => s.classList.toggle("active", s.id === screen));
  }

  function header(item) {
    return `
      <span class="cat">${esc(item.category)}</span>
      <h2 class="name">${esc(item.name)}</h2>
      ${item.name_bn ? `<p class="name-bn" lang="bn">${esc(item.name_bn)}</p>` : ""}
      <p class="has">has</p>`;
  }

  function footer(item) {
    return `<a class="wiki-link" href="${esc(item.page_url)}" target="_blank" rel="noopener">Wikipedia ↗</a>`;
  }

  function revealedHTML(item) {
    return header(item) + `
      <p class="views">${fmt(item.views)}</p>
      <p class="unit">views in a typical month</p>` + footer(item);
  }

  function questionHTML(item, than) {
    return header(item) + `
      <div class="choices">
        <button class="choice" data-guess="higher">Higher <span class="arrow">▲</span> <span class="bn">বেশি</span></button>
        <button class="choice" data-guess="lower">Lower <span class="arrow">▼</span> <span class="bn">কম</span></button>
      </div>
      <p class="than">views than <b>${esc(than.name)}</b></p>` + footer(item);
  }

  function paint(panel, item, html) {
    panel.style.backgroundImage = `url("${item.image}")`;
    panel.innerHTML = html;
  }

  function render() {
    paint($("p0"), left, revealedHTML(left));
    paint($("p1"), right, questionHTML(right, left));
    paint($("p2"), next, questionHTML(next, right));
    $("p1").querySelectorAll(".choice").forEach((b) => b.addEventListener("click", () => guess(b.dataset.guess)));
    const vs = $("vs");
    vs.className = "vs";
    vs.textContent = "VS";
    $("score").textContent = score;
    $("highscore").textContent = getHigh();
  }

  function countUp(el, target, ms) {
    return new Promise((resolve) => {
      const start = performance.now();
      const step = (t) => {
        const p = Math.min(1, (t - start) / ms);
        const eased = 1 - Math.pow(1 - p, 3);
        el.textContent = fmt(target * eased);
        if (p < 1) requestAnimationFrame(step);
        else resolve();
      };
      requestAnimationFrame(step);
    });
  }

  const wait = (ms) => new Promise((r) => setTimeout(r, ms));

  async function guess(dir) {
    if (busy) return;
    busy = true;
    const correct = dir === "higher" ? right.views >= left.views : right.views <= left.views;

    // Swap the buttons for a counting number, as in the original.
    const p1 = $("p1");
    p1.querySelector(".choices").outerHTML = `<p class="views">0</p><p class="unit">views in a typical month</p>`;
    p1.querySelector(".than").remove();
    await countUp(p1.querySelector(".views"), right.views, 1000);

    const vs = $("vs");
    vs.className = "vs " + (correct ? "correct" : "wrong");
    vs.textContent = correct ? "✓" : "✗";

    if (!correct) {
      await wait(1100);
      return gameOver();
    }

    score++;
    $("score").textContent = score;
    if (score > getHigh()) { setHigh(score); $("highscore").textContent = score; }

    await wait(600);
    const track = $("track");
    track.classList.add("sliding");
    await wait(800);
    left = right;
    right = next;
    next = draw();
    track.classList.remove("sliding"); // snaps back without transition
    render();
    busy = false;
  }

  function message(s) {
    if (s === 0) return "আরেকবার চেষ্টা করুন! · Give it another go!";
    if (s < 5) return "মোটামুটি! · Not bad!";
    if (s < 10) return "ভালো খেলেছেন! · Well played!";
    if (s < 20) return "দারুণ! আপনি বাংলাদেশ ভালোই চেনেন। · Great — you know Bangladesh!";
    return "অসাধারণ! আপনি তো বিশেষজ্ঞ! · Incredible — a true expert!";
  }

  function gameOver() {
    $("final-score").textContent = score;
    $("over-msg").textContent = message(score);
    $("over-bg").style.backgroundImage = `url("${right.image}")`;
    show("over");
    busy = false;
  }

  function start() {
    score = 0;
    deck = shuffle(items.slice());
    left = right = next = null;
    left = draw();
    right = draw();
    next = draw();
    render();
    show("game");
  }

  function goHome() {
    $("hs-home").textContent = getHigh();
    const pick = items[Math.floor(Math.random() * items.length)];
    if (pick) $("home-bg").style.backgroundImage = `url("${pick.image}")`;
    show("home");
  }

  async function load() {
    const btn = $("play-btn");
    try {
      const res = await fetch("items.json", { cache: "no-store" });
      items = await res.json();
      if (items.length < 4) throw new Error("not enough items");
      btn.textContent = "Play · খেলুন";
      btn.disabled = false;
    } catch (e) {
      btn.textContent = "No data — run fetch.py";
      console.error(e);
    }
    goHome();
  }

  $("play-btn").addEventListener("click", start);
  $("again-btn").addEventListener("click", start);
  $("home-btn").addEventListener("click", goHome);
  document.addEventListener("keydown", (e) => {
    if (!$("game").classList.contains("active")) return;
    if (e.key === "ArrowUp") guess("higher");
    if (e.key === "ArrowDown") guess("lower");
  });

  load();
})();
