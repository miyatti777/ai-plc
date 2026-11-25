"use strict";
// BacklogLive: /api/state を数秒ごとに読み、変わったところだけ目立たせて描き直す。
(() => {
  const POLL_MS = 2000;
  const FLASH_MS = 3500;
  const CATS = [
    ["done", "完了"],
    ["in_progress", "進行中"],
    ["ready", "実行可能"],
    ["waiting", "待ち"], // 依存待ちと実行時期待ちを合わせた数（帯と凡例）
    ["blocked", "ブロック"],
    ["excluded", "除外"],
  ];
  const LABEL = Object.fromEntries(CATS);
  const md = (iso) => `${Number(iso.slice(5, 7))}/${Number(iso.slice(8, 10))}`;
  // 実行時期を待っている Taskは「依存待ち」ではなく時期を出す
  // 回す日の来ていない daily・weekly の運用タスクは次に回す日を出す
  const label = (t) => t.category === "waiting" && t.waiting_for_run && t.next_run
    ? `待ち（次に回す日 ${md(t.next_run)}）`
    : t.category === "waiting" && t.waiting_for_schedule && t.scheduled_for
    ? `待ち（実行時期 ${md(t.scheduled_for)}）`
    : t.category === "waiting" ? "依存待ち" : (LABEL[t.category] || t.status);
  // 札に添える注記: 期限超過と読めない時期。並びと実行可能の判定は変えない
  const notes = (t) => [
    t.overdue && t.due ? `期限超過（${md(t.due)}）` : "",
    t.scheduled_for_invalid ? `時期を読めない（${t.scheduled_for_raw}）` : "",
  ].filter(Boolean);
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  };
  const color = (cat) => `var(--c-${cat})`;
  let prev = null; // {layer, statuses: Map}
  let lastSig = null; // 同じ内容なら描き直さない（強調・ツールチップを保つ）
  const changedAt = new Map(); // task id -> 変化を見つけた時刻
  let timer = null;
  let gen = 0; // URL 切替のたびに増やし、古い応答とポーリングを捨てる

  function query() {
    const q = new URLSearchParams(location.search);
    const out = new URLSearchParams();
    for (const k of ["layer", "at"]) if (q.get(k)) out.set(k, q.get(k));
    return out;
  }

  function fmtTime(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    return isNaN(d) ? iso : d.toLocaleTimeString("ja-JP", { hour12: false });
  }

  function renderHeader(s) {
    $("scope").textContent = s.scope_id || "—";
    $("name").textContent = s.name || s.layer_path || "";
    $("goal").textContent = s.goal || "";
    $("goal").title = s.goal || "";
    const follow = s.mode === "follow";
    const pinned = s.mode === "pinned";
    $("mtime").textContent = s.backlog_mtime
      ? `backlog 保存 ${fmtTime(s.backlog_mtime)}${follow ? "（いちばん新しい保存なので表示中）" : ""}` : "";
    $("mode").className = "mode " + (s.mode || "");
    $("mode").textContent = follow ? "作業中のLayerを追従" : pinned ? "この Layer を表示中（URL指定）" : "固定表示";
    $("mode").title = follow ? "最後に backlog.yaml が保存された Layer を表示します"
      : pinned ? "URL の ?layer= で指定した Layer だけを表示します。ほかの Layer の保存では切り替わりません"
      : "起動時に --layer で指定した Layer だけを表示します";
    $("follow-btn").hidden = !pinned;
    $("stage").className = "stage " + (s.stage || "");
    $("stage").textContent = s.stage_label || "";
    $("stage").hidden = !s.stage_label;
    $("path").textContent = s.layer_rel || s.layer_path || "";
    // 運用タスクだけの Layer は完了率が無い（percent null → 「—」）
    document.title = s.scope_id ? `${s.scope_id} ${s.percent == null ? "—" : s.percent + "%"} — BacklogLive` : "BacklogLive";
  }

  function renderNow(s) {
    const box = $("now");
    const t = (s.tasks || []).find((x) => x.order === s.current_order);
    box.className = "now " + (t ? (t.category === "in_progress" ? "" : "ready") : "none");
    $("now-deps").replaceChildren();
    $("now-meta").replaceChildren();
    box.title = "";
    if (!t) {
      const all = s.total && s.stage !== "operating" && s.done === s.target;
      const doneOps = s.stage === "done_operating"; // 通常 Task は完了・運用タスクが残る
      $("now-label").textContent = doneOps ? "通常タスク完了" : all ? "すべて完了" : "いま";
      $("now-id").textContent = "";
      // 時期待ちがあれば、最も早い実行時期まで待つと出す
      const sched = (s.tasks || []).filter((x) => x.category === "waiting" && x.waiting_for_schedule && !x.recurring && x.scheduled_for)
        .map((x) => x.scheduled_for).sort();
      $("now-name").textContent = s.total ? (doneOps ? "通常タスクは完了。運用タスクを回す日に回します"
        : all ? "対象タスクはすべて完了しています"
        : s.stage === "operating" ? "運用タスクだけです（回す日に回します）"
        : sched.length ? `次の実行時期 ${md(sched[0])} まで待ち`
        : "実行できるタスクがありません（依存待ち・ブロックのみ）") : "タスクはまだありません";
      return;
    }
    $("now-label").textContent = s.current_reason === "進行中" ? "いま進行中" : "次に実行できるタスク";
    $("now-id").textContent = t.id;
    $("now-name").textContent = t.name;
    const meta = [t.priority, t.type, `状態: ${t.status}`, `AC ${t.ac_count}件`].filter(Boolean);
    meta.forEach((m) => $("now-meta").append(el("span", "chip", m)));
    if (t.dependencies.length) {
      $("now-deps").append(el("span", "", "依存:"));
      t.dependencies.forEach((d) => {
        const ok = d.status === "completed" || d.status === "done" || d.status === "完了";
        const st = d.status === "not_in_backlog" ? "この backlog に無い" : d.status;
        $("now-deps").append(el("span", "chip " + (ok ? "done" : "open"), `${d.id} ${ok ? "✓" : st}`));
      });
    }
    if (t.acceptance_criteria.length) box.title = t.acceptance_criteria.join("\n");
  }

  function renderProgress(s) {
    $("done-count").textContent = `${s.done} / ${s.target}`;
    $("pct").textContent = s.percent == null ? "—" : `${s.percent}%`;
    const bar = $("bar");
    if (bar.children.length !== CATS.length) {
      bar.replaceChildren(...CATS.map(([cat]) => {
        const seg = el("span");
        seg.dataset.cat = cat;
        seg.style.background = color(cat);
        return seg;
      }));
    }
    // 帯・凡例・aria-label は通常 Task だけを数える（運用タスクは下の1行）
    const counts = s.counts_normal || s.counts || {};
    [...bar.children].forEach((seg) => {
      const n = counts[seg.dataset.cat] || 0;
      seg.style.flexGrow = String(n);
      seg.style.flexBasis = "0";
      seg.title = `${LABEL[seg.dataset.cat]} ${n}`;
      seg.hidden = n === 0;
    });
    bar.setAttribute("aria-label", CATS.map(([c, l]) => `${l} ${counts[c] || 0}`).join("、"));
    $("legend").replaceChildren(...CATS.map(([cat, label]) => {
      const n = counts[cat] || 0;
      const li = el("li", n ? "" : "zero");
      const sw = el("span", "sw");
      sw.style.background = color(cat);
      li.append(sw, el("span", "", `${label} ${n}`));
      return li;
    }));
    renderOps(s);
  }

  // 帯の下の1行: 『運用 N件（回す日 N件・次 M/D）』。回す日0件・次の日が無いときは省き、運用タスクが無ければ出さない
  function renderOps(s) {
    let line = $("ops-line");
    if (!line) {
      line = el("p", "flow-legend ops-line");
      line.id = "ops-line";
      $("legend").after(line);
    }
    const o = s.operations || {};
    const parts = [o.due ? `回す日 ${o.due}件` : "", o.next ? `次 ${md(o.next)}` : ""].filter(Boolean);
    line.textContent = o.count ? `運用 ${o.count}件${parts.length ? `（${parts.join("・")}）` : ""}` : "";
    line.hidden = !o.count;
  }

  function renderTasks(s) {
    const now = Date.now();
    const list = $("tasks");
    if (!s.tasks || !s.tasks.length) {
      list.replaceChildren(el("li", "empty", "backlog にタスクがありません"));
      return;
    }
    list.replaceChildren(...s.tasks.map((t) => {
      const li = el("li", `task ${t.category}`);
      if (t.order === s.current_order) li.classList.add("current");
      if (now - (changedAt.get(t.id) || 0) < FLASH_MS) li.classList.add("changed");
      const stripe = el("span", "stripe");
      stripe.style.background = color(t.category);
      const badge = el("span", `tstatus cat-${t.category}`, label(t));
      badge.style.background = color(t.category);
      const name = el("span", "tname", t.name);
      if (t.open_dependencies.length) name.title = `依存待ち: ${t.open_dependencies.join(", ")}`;
      // 注記は名前の列の中に添える（行の列の数は変えない）
      notes(t).forEach((n) => name.append(" ", el("small", "tnote", `［${n}］`)));
      li.append(stripe, el("span", "tid", t.id), name, badge);
      pressable(li, t, `${t.id} ${t.name} の詳細を開く`);
      return li;
    }));
  }

  // ---- 流れビュー: 依存の段ごとに並べ、依存を線で結ぶ ----
  const SVGNS = "http://www.w3.org/2000/svg";
  const VIEW_KEY = "backlogLive.view";
  let view = "flow";
  const VIEWS = ["flow", "list", "ops"];
  try { const v = localStorage.getItem(VIEW_KEY); view = VIEWS.includes(v) ? v : "flow"; } catch (e) { /* 記憶できなくても動く */ }
  // 実際に出す表示。「運用・予定」を選んでいても、その Layer にタブが無ければ流れを出す（記憶は変えない）
  const shown = () => (view === "ops" && !(lastState && lastState.has_ops_tab) ? "flow" : view);
  const VIEW_BOX = { flow: "flow", list: "tasks", ops: "ops" };
  const VIEW_TAB = { flow: "tab-flow", list: "tab-list", ops: "tab-ops" };
  let lastState = null;
  let showDone = false; // 最初から続く「すべて完了した段」を展開するか
  const PRANK = { P0: 0, P1: 1, P2: 2, P3: 3 };
  const svg = (tag, attrs, cls) => {
    const e = document.createElementNS(SVGNS, tag);
    for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, String(v));
    if (cls) e.setAttribute("class", cls);
    return e;
  };
  // 箱の中の名前は幅に合わせて折り返す（最大3行、超えたら「…」。全文はホバー）
  const PRIO_BONUS = { P0: 14, P1: 6 }; // 同じ行数なら P0 ＞ P1 ＞ それ以外 の大きさになる
  const LINE_H = 15, MAX_LINES = 3;
  let flowW = 176; // いま描いている箱の幅（描画ごとに決める）
  // 文字幅はブラウザで実測する（使えなければ半角6.8px・全角12pxで見積もる）
  let measureCtx = null;
  try {
    measureCtx = document.createElement("canvas").getContext("2d");
    measureCtx.font = `12px ${getComputedStyle(document.body).fontFamily}`;
  } catch (e) { measureCtx = null; }
  const charWCache = new Map();
  const charW = (ch) => {
    if (charWCache.has(ch)) return charWCache.get(ch);
    const w = measureCtx ? measureCtx.measureText(ch).width : (/[\u0000-\u00ff\uff61-\uff9f]/.test(ch) ? 6.8 : 12);
    charWCache.set(ch, w);
    return w;
  };
  const textW = (text) => [...text].reduce((a, c) => a + charW(c), 0);
  const wrapCache = new Map();
  function wrapName(text, w) {
    const key = `${w}|${text}`;
    if (wrapCache.has(key)) return wrapCache.get(key);
    const max = Math.max(24, w - 22);
    const lines = [];
    let cur = "", width = 0;
    for (const ch of text || "") {
      const cw = charW(ch);
      if (width + cw > max && cur) { lines.push(cur); cur = ""; width = 0; }
      cur += ch;
      width += cw;
    }
    if (cur) lines.push(cur);
    let out = lines.length ? lines : [""];
    if (out.length > MAX_LINES) {
      out = out.slice(0, MAX_LINES);
      let last = out[MAX_LINES - 1];
      while (last && textW(last) + 12 > max) last = [...last].slice(0, -1).join("");
      out[MAX_LINES - 1] = last + "…";
    }
    if (wrapCache.size > 2000) wrapCache.clear();
    wrapCache.set(key, out);
    return out;
  }
  const nodeH = (t) => 30 + LINE_H * wrapName(t.name || "", flowW).length + (PRIO_BONUS[(t.priority || "").toUpperCase()] || 0);

  function applyView() {
    const v = shown();
    const flow = v === "flow";
    $("tab-ops").hidden = !(lastState && lastState.has_ops_tab);
    $("ops").hidden = v !== "ops";
    $("flow").hidden = !flow;
    $("flow-legend").hidden = !flow;
    $("tasks").hidden = v !== "list";
    for (const b of document.querySelectorAll(".tabs button")) b.setAttribute("aria-selected", String(b.dataset.view === v));
  }

  function renderFlow(s) {
    lastState = s;
    const box = $("flow");
    if (!s || !s.tasks || !s.tasks.length || !s.flow || !s.tasks.some((t) => !t.recurring)) {
      const onlyOps = s && s.tasks && s.tasks.length && s.flow;
      box.replaceChildren(el("p", "empty", onlyOps ? "通常のタスクがありません" : "backlog にタスクがありません"));
      $("flow-legend").replaceChildren(...(onlyOps ? [opsNote(s)] : []));
      return;
    }
    if (shown() !== "flow") return;
    const f = s.flow;
    const W = Math.max(280, box.clientWidth || 600);
    const vertical = W < 560;
    const levels = Math.max(1, f.level_count);
    const byLevel = Array.from({ length: levels }, () => []);
    const flowTasks = s.tasks.filter((t) => !t.recurring); // 運用タスクは図に出さない（運用・予定のタブ）
    flowTasks.forEach((t) => byLevel[Math.min(t.level, levels - 1)].push(t));
    byLevel.forEach((row) => row.sort((a, b) =>
      (PRANK[(a.priority || "").toUpperCase()] ?? 9) - (PRANK[(b.priority || "").toUpperCase()] ?? 9) || a.order - b.order));

    const PAD = 8, GAP = 10, LABEL_H = 18, BAND = 30;
    const pos = new Map();
    const labels = [];
    let width, height;
    // 最初から続く「すべて完了・除外の段」を1本の帯にたたむ（展開はクリック）
    const closed = (t) => t.category === "done" || t.category === "excluded";
    let fold = 0;
    while (fold < levels - 1 && byLevel[fold].length && byLevel[fold].every(closed)) fold += 1;
    if (fold < 2 || showDone) fold = 0;
    const folded = byLevel.slice(0, fold).flat();
    let band = null;
    // 段の中で完了・除外が4件以上なら「完了 N件」の1つの箱にまとめる
    const summaries = [];
    const itemsOf = (row, li) => {
      const done = row.filter(closed);
      if (showDone || done.length < 4) return row;
      const sum = { summary: true, level: li, tasks: done, priority: "" };
      summaries.push(sum);
      return [sum, ...row.filter((t) => !closed(t))];
    };
    const place = (item, rect) => {
      if (item.summary) {
        item.rect = rect;
        item.tasks.forEach((t) => pos.set(t.order, { ...rect, grouped: true }));
      } else {
        pos.set(item.order, rect);
      }
    };
    const itemH = (item) => (item.summary ? 30 : nodeH(item));
    if (vertical) {
      const cols = Math.max(1, Math.floor((W - PAD * 2 + GAP) / (140 + GAP)));
      const nodeW = Math.floor((W - PAD * 2 - GAP * (cols - 1)) / cols);
      flowW = nodeW;
      let y = PAD;
      if (fold) {
        band = { x: PAD, y, w: W - PAD * 2, h: BAND };
        folded.forEach((t) => pos.set(t.order, { x: PAD, y, w: W - PAD * 2, h: BAND, folded: true }));
        y += BAND + 22;
      }
      byLevel.forEach((row, li) => {
        if (li < fold) return;
        labels.push({ x: PAD, y: y + 11, text: `${li + 1}段目（${row.length}件）` });
        y += LABEL_H;
        const items = itemsOf(row, li);
        for (let i = 0; i < items.length; i += cols) {
          const chunk = items.slice(i, i + cols);
          const rowH = Math.max(...chunk.map(itemH));
          chunk.forEach((t, j) => place(t, { x: PAD + j * (nodeW + GAP), y: y + (rowH - itemH(t)) / 2, w: nodeW, h: itemH(t) }));
          y += rowH + GAP;
        }
        y += 14; // 段のあいだは線を通すために空ける
      });
      width = W;
      height = y;
    } else {
      const nodeW = 176, colGap = 48;
      flowW = nodeW;
      let maxY = 0;
      if (fold) band = { x: PAD, y: PAD + LABEL_H, w: 120, h: 0 };
      const x0 = fold ? 120 + colGap : 0;
      byLevel.forEach((col, li) => {
        if (li < fold) return;
        const x = PAD + x0 + (li - fold) * (nodeW + colGap);
        labels.push({ x, y: PAD + 11, text: `${li + 1}段目（${col.length}件）` });
        let y = PAD + LABEL_H;
        itemsOf(col, li).forEach((t) => { place(t, { x, y, w: nodeW, h: itemH(t) }); y += itemH(t) + GAP; });
        maxY = Math.max(maxY, y);
      });
      width = Math.max(W, PAD * 2 + x0 + (levels - fold) * (nodeW + colGap) - colGap);
      height = maxY + PAD;
      if (band) {
        band.h = Math.max(BAND, maxY - band.y - GAP);
        folded.forEach((t) => pos.set(t.order, { ...band, folded: true })); // 帯の高さが決まってから線の出どころにする
      }
    }

    const root = svg("svg", { width, height, viewBox: `0 0 ${width} ${height}`, role: "img",
      "aria-label": `依存の流れ: ${levels}段・${flowTasks.length}件` });
    const defs = svg("defs");
    for (const k of ["base", "critical", "to_current", "cycle"]) {
      const m = svg("marker", { id: `arrow-${k}`, viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" });
      m.append(svg("path", { d: "M0,0 L10,5 L0,10 z" }, `arrow ${k === "base" ? "" : k}`));
      defs.append(m);
    }
    root.append(defs);
    for (const l of labels) {
      const tx = svg("text", { x: l.x, y: l.y }, "level-label");
      tx.textContent = l.text;
      root.append(tx);
    }

    // 線: 普通 → 最長の連なり → いまのタスクへの流れ の順に重ねる
    const weight = (e) => (e.to_current ? 3 : e.critical ? 2 : e.cycle ? 1 : 0);
    const edges = [...f.edges].sort((a, b) => weight(a) - weight(b));
    const gEdges = svg("g");
    for (const e of edges) {
      const a = pos.get(e.from), b = pos.get(e.to);
      if (!a || !b || b.folded || b.grouped) continue;
      let d;
      if (vertical) {
        const x1 = a.x + a.w / 2, y1 = a.y + a.h, x2 = b.x + b.w / 2, y2 = b.y;
        const dy = Math.max(16, (y2 - y1) / 2);
        d = `M${x1},${y1} C${x1},${y1 + dy} ${x2},${y2 - dy} ${x2},${y2}`;
      } else {
        const x1 = a.x + a.w, y1 = a.y + a.h / 2, x2 = b.x, y2 = b.y + b.h / 2;
        const dx = Math.max(16, (x2 - x1) / 2);
        d = `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`;
      }
      const kind = e.to_current ? "to_current" : e.critical ? "critical" : e.cycle ? "cycle" : "base";
      gEdges.append(svg("path", { d, "marker-end": `url(#arrow-${kind})` }, `edge ${kind === "base" ? "" : kind}`));
    }
    root.append(gEdges);
    if (band) {
      const g = svg("g", { role: "button", tabindex: 0 }, "done-band");
      const tt = svg("title");
      tt.textContent = "クリックで完了した段を表示";
      g.append(tt, svg("rect", { x: band.x, y: band.y, width: band.w, height: band.h, rx: 8 }));
      const tx = svg("text", { x: band.x + 12, y: band.y + 19 });
      tx.textContent = vertical ? `1〜${fold}段目: すべて完了（${folded.length}件）▸ 表示する` : `1〜${fold}段目 完了 ${folded.length}件`;
      g.append(tx);
      const open = () => { showDone = true; renderFlow(lastState); };
      g.addEventListener("click", open);
      g.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); open(); } });
      root.append(g);
    }

    for (const sum of summaries) {
      const r = sum.rect;
      const g = svg("g", { role: "button", tabindex: 0, transform: `translate(${r.x},${r.y})` }, "done-band");
      const tt = svg("title");
      tt.textContent = `完了・除外: ${sum.tasks.map((t) => t.id).join(", ")}\nクリックで表示`;
      g.append(tt, svg("rect", { x: 0, y: 0, width: r.w, height: r.h, rx: 8 }));
      const tx = svg("text", { x: 12, y: 19 });
      tx.textContent = `完了 ${sum.tasks.length}件 ▸`;
      g.append(tx);
      const open = () => { showDone = true; renderFlow(lastState); };
      g.addEventListener("click", open);
      g.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); open(); } });
      root.append(g);
    }

    const now = Date.now();
    const gNodes = svg("g");
    for (const t of flowTasks) {
      const p = pos.get(t.order);
      if (!p || p.folded || p.grouped) continue;
      const pr = /^P[0-3]$/i.test(t.priority || "") ? t.priority.toLowerCase() : "";
      const cls = ["node", `cat-${t.category}`];
      if (pr) cls.push(pr);
      if (t.order === s.current_order) cls.push("current");
      if (now - (changedAt.get(t.id) || 0) < FLASH_MS) cls.push("changed");
      if (t.category === "waiting" && t.waiting_for_schedule) cls.push("wait-sched"); // 依存待ちと見分ける
      const g = svg("g", { transform: `translate(${p.x},${p.y})` }, cls.join(" "));
      pressable(g, t, `${t.id} ${t.name} の詳細を開く`);
      const title = svg("title");
      const deps = t.dependencies.map((d) => d.id).join(", ");
      title.textContent = `${t.id} ${t.name}\n状態: ${label(t)}${notes(t).length ? ` ／ ${notes(t).join(" ／ ")}` : ""}${t.priority ? ` ／ ${t.priority}` : ""}${deps ? `\n依存: ${deps}` : ""}${t.in_cycle ? "\n循環に入っています" : ""}`;
      g.append(title);
      if (t.order === s.current_order) g.append(svg("rect", { x: -4, y: -4, width: p.w + 8, height: p.h + 8, rx: 11 }, "halo"));
      g.append(svg("rect", { x: 0, y: 0, width: p.w, height: p.h, rx: 8 }, "box"));
      g.append(svg("rect", { x: 0, y: 0, width: pr === "p0" ? 8 : 5, height: p.h, rx: 2 }, "accent"));
      const id = svg("text", { x: pr === "p0" ? 15 : 12, y: pr === "p0" ? 18 : 15 }, "nid");
      const head = `${t.id}${/^P[0-3]$/i.test(t.priority || "") ? " · " + t.priority.toUpperCase() : ""}`;
      const headLines = wrapName(head, p.w);
      id.textContent = headLines.length > 1 ? `${headLines[0].slice(0, -1)}…` : headLines[0];
      g.append(id);
      const top = pr === "p0" ? 37 : pr === "p1" ? 34 : 31; // 優先度の上乗せ分は名前の上に空ける
      wrapName(t.name || "", p.w).forEach((line, i) => {
        const nm = svg("text", { x: pr === "p0" ? 15 : 12, y: top + i * LINE_H }, "nname");
        nm.textContent = line;
        g.append(nm);
      });
      gNodes.append(g);
    }
    root.append(gNodes);
    box.replaceChildren(root);

    const legend = [
      el("span", "", vertical ? "上から下へ進みます。" : "左から右へ進みます。"),
      el("span", "", "同じ段のタスクは並行できます。"),
      el("span", "", "青い線はいまのタスクへの直接の依存、濃い太線は最も長い依存の連なり、枠が太いほど優先度が高いタスクです。"),
    ];
    if (flowTasks.some((t) => t.category === "waiting" && t.waiting_for_schedule)) {
      legend.push(el("span", "", " 青い点線の箱は実行時期を待っているタスク、灰色の破線の箱は依存を待っているタスクです。"));
    }
    // 決まりに反して運用タスクに依存している Task は線が無いので、理由を1行出す
    const opsIds = new Set(s.tasks.filter((t) => t.recurring).map((t) => t.id));
    const onOps = flowTasks.filter((t) => t.dependencies.some((d) => opsIds.has(d.id)));
    if (onOps.length) legend.push(el("span", "", ` ${onOps.map((t) => t.id).join("、")} は運用タスクに依存しています（図には線を引きません）。`));
    if (f.hidden_recurring) legend.push(opsNote(s));
    if (showDone) {
      const b = el("button", "linklike", "完了したタスクをたたむ");
      b.type = "button";
      b.addEventListener("click", () => { showDone = false; renderFlow(lastState); });
      legend.push(b);
    }
    if (f.cycle && f.cycle.length) legend.push(el("span", "warn", ` 依存が循環しています: ${f.cycle.join(", ")}（同じ段に並べ、赤い破線で示しています）`));
    $("flow-legend").replaceChildren(...legend);
  }

  // ---- 「運用・予定」タブ: 上に運用タスク、下に実行時期・期限を日付順に ----
  const BUCKETS = [["past", "今日より前（時期が来ている・期限を過ぎた）"], ["today", "今日・今週"], ["future", "この先"]];
  // 今年でない日付は年も出す（2027-05-01 を「5/1」とだけ出すと今年の日付に見える）
  const ymd = (iso) => (Number(iso.slice(0, 4)) === new Date().getFullYear() ? md(iso) : `${iso.slice(0, 4)}/${md(iso)}`);
  const dateLabel = (e) => (e.week ? `${ymd(e.date)} の週` : ymd(e.date));
  function opsRow(t, cells, cls) {
    const li = el("li", `ops-row ${cls || ""}`);
    const stripe = el("span", "stripe");
    stripe.style.background = color(t.category);
    const main = el("span", "ops-main");
    main.append(el("span", "tid", t.id), " ", el("span", "tname", t.name));
    const meta = el("span", "ops-meta");
    cells.filter(Boolean).forEach((c) => meta.append(typeof c === "string" ? el("span", "chip", c) : c));
    li.append(stripe, main, meta);
    pressable(li, t, `${t.id} ${t.name} の詳細を開く`);
    return li;
  }

  function renderOpsTab(s) {
    const box = $("ops");
    if (!s || !s.has_ops_tab) { box.replaceChildren(); return; }
    const byOrder = new Map((s.tasks || []).map((t) => [t.order, t]));
    const out = [];
    // 運用タスク: 今日回すもの → 次に回す日の早い順 → 会議の後 → 閉じたもの
    const ops = (s.tasks || []).filter((t) => t.recurring);
    const rank = (t) => (t.retired ? [3, ""] : t.run_due ? [0, ""] : t.next_run ? [1, t.next_run] : [2, ""]);
    ops.sort((a, b) => { const x = rank(a), y = rank(b); return x[0] - y[0] || x[1].localeCompare(y[1]) || a.order - b.order; });
    // 中身の無い欄は出さない（運用タスクだけ・予定だけの Layer で空の見出しを並べない）
    if (ops.length) {
      out.push(el("h3", "ops-head", `運用タスク（${ops.length}件）`));
      const ol = el("ol", "ops-list");
      ops.forEach((t) => {
        const next = t.retired ? "閉じた" : t.recurrence === "per_meeting" ? "次: 会議の後"
          : t.run_due ? "今日回す" : t.next_run ? `次: ${ymd(t.next_run)}` : "";
        const nextChip = el("span", "chip " + (t.run_due && !t.retired ? "open" : ""), next);
        ol.append(opsRow(t, [RECUR_LABEL[t.recurrence] || t.recurrence, t.last_run_any ? `前回: ${ymd(t.last_run_any)}` : "まだ回していない",
          next ? nextChip : "",
          // 回す・回す日待ち以外の状態（依存待ち・ブロック・完了・除外）は札で示す
          !t.retired && !["ready", "in_progress"].includes(t.category) && !t.waiting_for_run && !t.waiting_for_schedule ? label(t) : "",
        ], t.retired ? "retired" : ""));
      });
      out.push(ol);
    }
    // 予定と期限
    const ag = s.agenda || { entries: [], invalid: [], hidden_done: 0 };
    const nAg = ag.entries.length + ag.invalid.length;
    if (nAg) out.push(el("h3", "ops-head", `予定と期限（${nAg}件）`));
    else if (ag.hidden_done) out.push(el("h3", "ops-head", "予定と期限"), el("p", "empty", "まだ終わっていない Task に、実行時期・期限の書かれたものはありません"));
    for (const [b, title] of BUCKETS) {
      const rows = ag.entries.filter((e) => e.bucket === b);
      if (!rows.length) continue;
      out.push(el("h4", `ops-bucket ${b}`, `${title}（${rows.length}）`));
      const ol = el("ol", "ops-list");
      rows.forEach((e) => {
        const t = byOrder.get(e.order);
        if (!t) return;
        const kind = el("span", "chip " + (e.kind === "due" ? (e.overdue ? "late" : "due") : "sched"),
          `${e.kind === "due" ? "期限" : "実行時期"} ${dateLabel(e)}${e.overdue ? "（過ぎた）" : ""}`);
        ol.append(opsRow(t, [kind, label(t)], e.overdue ? "overdue" : ""));
      });
      out.push(ol);
    }
    if (ag.invalid.length) {
      out.push(el("h4", "ops-bucket invalid", `日付を読めない（${ag.invalid.length}）`));
      const ol = el("ol", "ops-list");
      ag.invalid.forEach((e) => {
        const t = byOrder.get(e.order);
        if (t) ol.append(opsRow(t, [`${e.kind === "due" ? "期限" : "実行時期"}: ${e.raw}`, label(t)], "invalid"));
      });
      out.push(ol);
    }
    if (ag.hidden_done) out.push(el("p", "flow-legend", `完了・除外の Task の日付 ${ag.hidden_done}件は出していません。`));
    box.replaceChildren(...out);
  }

  // ---- タスクの詳細: 箱を押すと、その Task の中身をシート／パネルで出す ----
  let selectedId = null;
  let opener = null; // 閉じたときにフォーカスを戻す先の ID
  let openerEl = null; // 押した箱・行そのもの（同じ Task の行が2つあるとき押した方へ戻す。描き直されていたら ID で探す）
  let taskLayer = null; // &task= を開いた Layer（別の Layer の同じ ID を URL から開き直さないため。null は URL の切り替え直後）
  const DETAIL_LABEL = {
    description: "説明", output: "成果物", result: "結果", guardrails: "守ること（guardrails）",
    verification: "検証", blocked_reason: "止まっている理由", note: "メモ", pr_url: "PR",
  };
  const DETAIL_META = [
    ["owner", "担当"], ["estimated_hours", "見積（時間）"], ["started_at", "開始"], ["completed_at", "完了"],
    ["executed_by", "実行した環境"], ["origin", "出どころ"],
  ];

  function pressable(node, t, aria) {
    node.setAttribute("role", "button");
    node.setAttribute("tabindex", "0");
    node.setAttribute("aria-label", aria);
    node.dataset.task = t.id;
    if (t.id === selectedId) node.classList.add("selected");
    node.addEventListener("click", (ev) => { ev.stopPropagation(); openerEl = node; openDetail(t.id, true); });
    node.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); openerEl = node; openDetail(t.id, true); }
    });
  }

  function markSelected() {
    for (const n of document.querySelectorAll("[data-task]")) n.classList.toggle("selected", n.dataset.task === selectedId);
  }

  // 開いた Task を URL の &task= に残す（再読込でも開いたまま）。履歴は増やさない
  function setTaskParam(id) {
    const u = new URL(location.href);
    if (id) u.searchParams.set("task", id); else u.searchParams.delete("task");
    history.replaceState(history.state, "", u.pathname + u.search);
  }

  // fromBox: 箱から開いたときだけ、閉じたときのフォーカスの戻り先にする（依存の札で移ったときは変えない）
  // focus: URL から自動で開いたときは false（フォーカスを動かさない）
  function openDetail(id, fromBox, focus = true) {
    const s = lastState;
    if (!s || !(s.tasks || []).some((t) => t.id === id)) return;
    if (fromBox || !opener) opener = id;
    selectedId = id;
    taskLayer = s.layer_path;
    setTaskParam(id);
    renderDetail(s);
    $("detail").hidden = false;
    $("detail-backdrop").hidden = false;
    document.body.classList.add("detail-open");
    markSelected();
    if (shown() === "flow") renderFlow(s); // 広い幅ではパネルの分だけ図の幅が変わる
    if (focus) $("detail-close").focus();
  }

  // focus: 本人が閉じたときだけフォーカスを戻す（Layer の切り替えなどで自動で閉じたときは動かさない）
  // url: &task= を外すか（読めない Layer・URL の切り替えでは残し、読めたらまた開く）
  function closeDetail({ focus = true, url = true } = {}) {
    if (!selectedId) return;
    selectedId = null;
    if (url) setTaskParam(null);
    $("detail").hidden = true;
    $("detail-backdrop").hidden = true;
    document.body.classList.remove("detail-open");
    markSelected();
    if (shown() === "flow" && lastState) renderFlow(lastState);
    // 隠れている表示の箱を拾わないよう、今の表示の中で探す。無ければ表示の切り替えボタンへ戻す
    const box = $(VIEW_BOX[shown()]);
    const back = openerEl && openerEl.isConnected && box.contains(openerEl) ? openerEl
      : opener && box.querySelector(`[data-task="${CSS.escape(opener)}"]`);
    opener = null;
    openerEl = null;
    if (focus) (back || $(VIEW_TAB[shown()])).focus();
  }

  const section = (title, ...children) => [el("h3", "", title), ...children];
  const textBlock = (v, cls) => Array.isArray(v)
    ? (() => { const ul = el("ul", cls); v.forEach((x) => ul.append(el("li", "", x))); return ul; })()
    : el("p", cls, v);

  function depChips(rows, empty) {
    if (!rows.length) return el("p", "none", empty);
    const box = el("div", "deps");
    rows.forEach((d) => {
      const ok = d.status === "completed" || d.status === "done" || d.status === "完了";
      const st = d.status === "not_in_backlog" ? "この backlog に無い" : d.status;
      const text = `${d.id} ${ok ? "✓" : st}`;
      if (d.status === "not_in_backlog") { box.append(el("span", "chip open", text)); return; }
      const b = el("button", "chip " + (ok ? "done" : "open"), text);
      b.type = "button";
      b.title = `${d.id} の詳細を開く`;
      b.addEventListener("click", () => openDetail(d.id));
      box.append(b);
    });
    return box;
  }

  // 開いている間に backlog が更新されたら中身を差し替える。Task が消えたら最後の内容に印を付ける
  function syncDetail(s) {
    if (selectedId) { renderDetail(s); return; }
    const want = new URLSearchParams(location.search).get("task");
    if (!want) return;
    // 読めない応答を挟んで追従先が替わったときは prev で気づけないので、開いた Layer と照らして外す
    if (taskLayer && taskLayer !== s.layer_path) { setTaskParam(null); return; }
    if ((s.tasks || []).some((t) => t.id === want)) openDetail(want, true, false);
  }

  // 運用タスクの回し方・実行の記録と、実行時期の変更履歴。無い Task では何も出さない
  const RECUR_LABEL = { daily: "毎日", weekly: "毎週", per_meeting: "会議の後" };
  function opsSections(t, d) {
    const out = [];
    if (t.recurring) {
      const dl = el("dl");
      const row = (k, v) => { if (v) dl.append(el("dt", "", k), el("dd", "", v)); };
      row("回し方", RECUR_LABEL[t.recurrence] || t.recurrence || "");
      row("前回回した日", t.last_run_any ? md(t.last_run_any) : "まだ回していない"); // 今日以前の読める日付の最大（server が決める）
      row("次に回す日", t.retired ? "" : t.recurrence === "per_meeting" ? "会議の後に回す"
        : t.run_due ? "今日（回す日）" : t.next_run ? md(t.next_run) : "");
      row("閉じた日", d.retired_at || "");
      row("閉じた理由", d.retired_reason || "");
      out.push(...section("運用タスク", dl));
    }
    if (d.runs && d.runs.length) {
      const ol = el("ol", "runs");
      d.runs.forEach((r) => {
        const li = el("li");
        li.append(el("strong", "", r.date || "（日付なし）"), " ", r.summary || "");
        if (r.output) li.append(el("div", "mono sub", Array.isArray(r.output) ? r.output.join(" / ") : r.output));
        if (r.checked_ac) li.append(el("div", "sub", `確かめた AC: ${Array.isArray(r.checked_ac) ? r.checked_ac.join("、") : r.checked_ac}`));
        ol.append(li);
      });
      const more = d.runs_total > d.runs.length ? `（全 ${d.runs_total} 件のうち新しい ${d.runs.length} 件）` : `（${d.runs.length} 件・新しい順）`;
      out.push(...section(`実行の記録${more}`, ol));
    }
    if (d.schedule_history && d.schedule_history.length) {
      const ul = el("ul");
      d.schedule_history.forEach((h) => {
        ul.append(el("li", "", `${h.date || "（日付なし）"}: ${h.from || "（なし）"} → ${h.to || "（なし）"}${h.reason ? `（${h.reason}）` : ""}`));
      });
      const n = d.schedule_history_total || d.schedule_history.length;
      out.push(...section(n > d.schedule_history.length ? `実行時期の変更（全 ${n} 件のうち新しい ${d.schedule_history.length} 件）` : "実行時期の変更", ul));
    }
    return out;
  }

  function renderDetail(s) {
    const t = (s.tasks || []).find((x) => x.id === selectedId);
    if (!t) {
      $("detail-chips").replaceChildren(el("span", "chip open", "この Task は backlog にありません（最後に読めた内容を表示しています）"));
      return;
    }
    const d = t.detail || {};
    $("detail-id").textContent = t.id;
    $("detail-name").textContent = t.name || "（名前なし）";
    const chips = [label(t), t.priority, t.type, ...notes(t)].filter(Boolean);
    if (t.recurrence) chips.push(`運用タスク（${t.recurrence}）`);
    if (t.scheduled_for) chips.push(`実行時期 ${md(t.scheduled_for)}`);
    if (t.due && !t.due_invalid) chips.push(`期限 ${md(t.due)}`);
    $("detail-chips").replaceChildren(...chips.map((c) => el("span", "chip", c)));
    const body = [];
    if (d.description) body.push(...section(DETAIL_LABEL.description, textBlock(d.description)));
    const ac = el("ol");
    t.acceptance_criteria.forEach((a) => ac.append(el("li", "", a)));
    body.push(...section(`受け入れ条件（${t.acceptance_criteria.length}件）`,
      t.acceptance_criteria.length ? ac : el("p", "none", "backlog に書かれていません")));
    body.push(...section("依存（この Task の前に終わっている必要がある Task）", depChips(t.dependencies, "なし")));
    body.push(...section("この Task を待っている Task", depChips(t.dependents || [], "なし")));
    body.push(...opsSections(t, d));
    for (const k of ["output", "result", "guardrails", "verification", "blocked_reason", "note", "pr_url"]) {
      if (d[k]) body.push(...section(DETAIL_LABEL[k], textBlock(d[k], k === "output" || k === "pr_url" ? "mono" : "")));
    }
    const meta = DETAIL_META.filter(([k]) => d[k]);
    if (meta.length) {
      const dl = el("dl");
      meta.forEach(([k, l]) => dl.append(el("dt", "", l), el("dd", "", Array.isArray(d[k]) ? d[k].join(" / ") : d[k])));
      body.push(...section("そのほか", dl));
    }
    $("detail-body").replaceChildren(...body);
  }

  // 「運用・予定」のタブへ移るボタン。移ったらタブのボタンにフォーカスを置く（押したボタンは隠れるため）
  // タブがあるときだけ移るボタンにする。閉じた運用タスクしか無くタブが無いときは文だけ（押しても何も起きないボタンを出さない）
  function opsNote(s) {
    const n = s.flow.hidden_recurring;
    return s.has_ops_tab ? opsLink(n) : el("span", "", ` 閉じた運用タスク ${n}件は図に出していません（一覧のタブで見られます）。`);
  }

  function opsLink(n) {
    const b = el("button", "linklike", `運用タスク ${n}件は「運用・予定」のタブに出しています`);
    b.type = "button";
    b.addEventListener("click", () => { setView("ops"); $("tab-ops").focus(); });
    return b;
  }

  function setView(v) {
    view = VIEWS.includes(v) ? v : "flow";
    try { localStorage.setItem(VIEW_KEY, view); } catch (e) { /* 記憶できなくても動く */ }
    applyView();
    if (shown() === "flow" && lastState) renderFlow(lastState);
  }

  function diff(s) {
    const statuses = new Map((s.tasks || []).map((t) => [t.id, `${t.category}|${t.name}`]));
    if (prev && prev.layer === s.layer_path) {
      statuses.forEach((v, k) => { if (prev.statuses.get(k) !== v) changedAt.set(k, Date.now()); });
    } else {
      changedAt.clear();
    }
    prev = { layer: s.layer_path, statuses };
  }

  function setLive(ok, text) {
    $("live").classList.toggle("off", !ok);
    $("live-text").textContent = text;
  }

  function banner(msg) {
    $("banner").hidden = !msg;
    $("banner").textContent = msg || "";
  }

  async function tick() {
    const my = gen;
    try {
      const qs = query().toString();
      const res = await fetch("/api/state" + (qs ? "?" + qs : ""), { cache: "no-store" });
      const s = await res.json();
      if (my !== gen) return; // 途中で URL が変わった
      setLive(true, `最終読取 ${fmtTime(s.read_at)}`);
      if (!s.tasks) {
        // 前の Layer の本体を残さない。次に読めたら必ず描き直す
        lastSig = null;
        prev = null;
        closeDetail({ focus: false, url: false }); // 読めない Layer に前の Layer の詳細を残さない
        renderHeader({ ...s, scope_id: s.requested_layer || "", name: "表示できません", goal: "", stage_label: "" });
        if (s.mode === "pinned" || !s.mode) {
          $("mode").className = "mode unavailable";
          $("mode").textContent = s.mode ? "指定の Layer を表示できません" : "表示できません";
          $("follow-btn").hidden = !query().get("layer");
        }
        renderNow({ tasks: [], total: 0 });
        renderProgress({ done: 0, target: 0, percent: 0, counts: {} });
        $("tasks").replaceChildren(el("li", "empty", "この Layer は読めません"));
        lastState = null;
        $("flow").replaceChildren(el("p", "empty", "この Layer は読めません"));
        $("ops").replaceChildren();
        applyView(); // 運用・予定のタブを隠し、流れを出す
        $("flow-legend").replaceChildren();
        $("now-name").textContent = "この Layer は読めません";
        banner(s.error || "状態を読めませんでした");
        if (s.candidates && s.candidates.length) showCandidates(s.candidates, "同じ scope_id の Layer が複数あります。表示するものを選んでください");
        return;
      }
      const notes = [];
      if (s.stale) notes.push(`${s.error} — 最後に読めた内容を表示しています`);
      if (s.intent_error) notes.push(`${s.intent_error}（名前と Goal を表示できません）`);
      if (s.duplicate_ids && s.duplicate_ids.length) notes.push(`タスクIDが重複しています: ${s.duplicate_ids.join(", ")}`);
      if (s.layer_param_ignored) notes.push(s.layer_param_ignored);
      banner(notes.join(" ／ "));
      const { read_at, ...rest } = s;
      const sig = JSON.stringify(rest);
      if (sig === lastSig) return;
      lastSig = sig;
      if (prev && prev.layer !== s.layer_path) {
        // 追従で別の Layer に替わったら、前の Layer の詳細を閉じ、&task= も外す（新しい Layer の同じ ID を開かない）
        closeDetail({ focus: false });
        setTaskParam(null); // 詳細は閉じていても URL に task が残っていることがある（closeDetail は開いていないと何もしない）
      }
      diff(s);
      renderHeader(s);
      renderNow(s);
      renderProgress(s);
      renderTasks(s);
      lastState = s; // タブの有無を先に決めてから流れを描く（隠れたまま描くと幅0で横向きになる）
      renderOpsTab(s);
      applyView();
      renderFlow(s);
      syncDetail(s);
    } catch (e) {
      if (my === gen) setLive(false, "サーバに接続できません（最後の表示のまま）");
    } finally {
      if (my === gen) timer = setTimeout(tick, document.hidden ? POLL_MS * 3 : POLL_MS);
    }
  }

  function restart() {
    gen += 1;
    closeDetail({ focus: false, url: false });
    taskLayer = null; // URL を切り替えたので、URL の task はその URL の Layer のもの
    showDone = false;
    candKey = null;
    clearTimeout(timer);
    lastSig = null;
    prev = null;
    changedAt.clear();
    tick();
  }

  // ?layer= を書き換えて表示を切り替える（null で追従に戻す）
  function navigate(layer, at) {
    const u = new URL(location.href);
    u.searchParams.delete("layer");
    u.searchParams.delete("at");
    u.searchParams.delete("task");
    if (layer) u.searchParams.set("layer", layer);
    if (layer && at) u.searchParams.set("at", at);
    history.pushState(null, "", u.pathname + u.search);
    $("picker").open = false;
    restart();
  }

  function layerButton(row, active) {
    const b = el("button", active ? "active" : "");
    const at = row.at || null;
    b.type = "button";
    b.append(el("span", "sid", row.scope_id || "（scope_id なし）"), el("span", "lname", row.name || ""),
      el("span", "lrel", row.rel + (row.backlog_mtime ? `  ・保存 ${fmtTime(row.backlog_mtime)}` : "")));
    b.disabled = !row.scope_id;
    b.addEventListener("click", () => navigate(row.scope_id, at));
    return el("li").appendChild(b).parentNode;
  }

  let candKey = null;
  function showCandidates(rows, note) {
    const key = rows.map((r) => r.rel).join("|");
    if (key === candKey) return; // 同じ候補を2秒ごとに開き直さない
    candKey = key;
    $("picker").dataset.keep = "1";
    $("picker-note").textContent = note;
    $("layer-list").replaceChildren(...rows.map((r) => layerButton(r, false)));
    $("picker").open = true;
  }

  async function loadLayers() {
    $("picker-note").textContent = "読み込み中…";
    try {
      const res = await fetch("/api/layers", { cache: "no-store" });
      const d = await res.json();
      if (!d.available) {
        $("picker-note").textContent = d.reason || "Layer は選べません";
        $("layer-list").replaceChildren();
        return;
      }
      const cur = query().get("layer");
      const curAt = query().get("at");
      $("picker-note").textContent = `保存の新しい順に ${d.layers.length} 件（全 ${d.total} 件）`;
      $("layer-list").replaceChildren(...d.layers.map((r) => layerButton(r, r.scope_id === cur && (!r.at || r.at === curAt))));
    } catch (e) {
      $("picker-note").textContent = "一覧を読めませんでした";
    }
  }

  $("picker").addEventListener("toggle", () => {
    if (!$("picker").open) { delete $("picker").dataset.keep; return; }
    if ($("picker").dataset.keep) return; // 重複候補を出した直後は一覧で上書きしない
    loadLayers();
  });
  $("follow-btn").addEventListener("click", () => navigate(null));
  $("detail-close").addEventListener("click", () => closeDetail());
  $("detail-backdrop").addEventListener("click", () => closeDetail());
  $("detail").addEventListener("click", (ev) => ev.stopPropagation());
  // 詳細の外側を押したら閉じる（別のタスクの箱は pressable が先に受けて、そちらを開く）
  document.addEventListener("click", () => { if (selectedId) closeDetail(); });
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && selectedId) closeDetail(); });
  for (const b of document.querySelectorAll(".tabs button")) b.addEventListener("click", () => setView(b.dataset.view));
  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { if (lastState) renderFlow(lastState); }, 200);
  });
  applyView();
  window.addEventListener("popstate", restart);
  document.addEventListener("visibilitychange", () => {
    // 戻ったらすぐ読む。前回の内容と強調は残す（URL は変わっていない）
    if (!document.hidden) { gen += 1; clearTimeout(timer); tick(); }
  });
  tick();
})();
