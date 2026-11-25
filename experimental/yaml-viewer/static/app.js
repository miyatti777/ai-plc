/* YamlViewer — 表＋札で registers を読む（閲覧専用）。サーバの /api/list と /api/state だけを使う。 */
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const POLL_MS = 3000;
  const BACKLOG_LIVE = "http://127.0.0.1:8770/";  // BacklogLive（図はあちら）
  const FILES = [
    { key: "hypotheses", label: "仮説", group: "box" },
    { key: "issues", label: "論点", group: "box" },
    { key: "wbs", label: "WBS", group: "box" },
    { key: "roadmap", label: "節目", group: "box" },
    { key: "todo", label: "ToDo", group: "box" },
    { key: "intent", label: "案件", group: "layer" },
    { key: "context", label: "Context", group: "layer" },
    { key: "backlog", label: "タスク", group: "layer" },
    { key: "plain", label: "YAML", group: "plain" },
  ];
  const ID_FILE = [[/^H\d+$/, "hypotheses"], [/^I\d+$/, "issues"], [/^W\d+(\.\d+)*$/, "wbs"], [/^MS\d+$/, "roadmap"], [/^D\d+$/, "todo"], [/^T\d+$/, "backlog"]];
  const ID_TOKEN = /(?<![\w/.@:-])(MS\d+|H\d+|I\d+|W\d+(?:\.\d+)*|D\d+|T\d+)(?![\w/-])/g;
  const UNKNOWN = new Set(["[unknown]", "undecided", "unknown", "", "null", "none", "tbd", "-"]);
  const LABEL = {
    id: "ID", claim: "主張", kind: "種類", status: "状態", priority: "優先", due: "期限", owner: "担当", method: "確かめ方",
    success: "成立の条件", falsification: "反証の条件", evidence: "根拠", risk_note: "注意", sources: "出典", judgements: "判定の履歴",
    question: "問い", answer: "答え", parent: "親の論点", reason: "理由", validation_plan: "検証の仮説", evidence_refs: "証拠",
    decided_by: "決めた人", review_at: "見直し日", title: "題名", source: "出どころ", wbs_id: "WBS", note: "メモ", deliverable: "成果物",
    exit_criteria: "終わりの条件", gate: "関門", issue_ids: "論点", milestone_id: "節目", depends: "依存", schedule: "日程",
    baseline: "合意した日程", forecast: "見込み", actual: "実績", history: "変更の履歴", start: "始め", end: "終わり", agreed_at: "合意した日時",
    agreed_by: "合意した人", scope: "範囲", milestone: "節目", period: "時期", wbs_ids: "WBS", source_of_truth: "正本", expected_value: "期待する値",
    legacy_ref: "旧い参照", issue_id: "論点", date: "日付", event: "出来事", verdict: "判定", judged_by: "判定した人", evidence_ref: "証拠", from: "前", to: "後",
    change_conditions: "変える条件", exit_conditions: "終える条件",
    name: "名前", description: "やること", type: "種類", dependencies: "依存", estimated_hours: "見積（時間）", command: "指示", origin: "出どころ",
    acceptance_criteria: "受け入れ条件", guardrails: "してはいけないこと", output: "成果物", result: "結果", executed_by: "実行した環境",
    completed_at: "完了日", scheduled_for: "実行時期", recurrence: "繰り返し", runs: "実行の記録", delegable: "委譲できる", wbs_id: "WBS",
    summary: "要約", url: "場所", scope_id: "ID", scope_name: "フォルダ名", display_name: "表示名", workflow_depth: "深度", workflow_depth_reason: "深度の理由",
    goal: "ゴール", success_criteria: "成功条件", mode: "モード", deadline: "期限", classification: "分類", affiliation: "所属", executor: "実行環境",
    membership: "業務所属", request_provenance: "原要求", original_request: "原文", via: "窓口", explicit_changes: "明示の変更", text: "本文",
    generated_at: "作った日", context_documents: "Context 文書", inheritance_rules: "引き継ぎの決まり", sync_targets: "同期先", jev_monitor: "Jev 監視",
    decisions: "決めごと", construction: "Agent 定義", refactoring_log: "再計画の記録", focus_strategy: "分解の戦略", parent_scope: "親", sub_agent_scopes: "子",
  };
  const WORD = {
    kind: { opportunity: "機会", problem: "課題", solution: "解決策", validation: "検証" },
    status: {
      unknown: ["未判定", "muted"], not_supported: ["反証", "bad"], structurally_supported: ["構造上は支持", "warn"], supported: ["支持", "ok"],
      open: ["未解決", "warn"], resolved: ["解決", "ok"], not_needed: ["検討不要", "muted"], cancelled: ["中止", "muted"], on_hold: ["保留", ""],
      draft: ["下書き", ""], planned: ["計画", ""], pending_acceptance: ["受入待ち", "warn"], partially_accepted: ["一部受入", "warn"], accepted: ["受入", "ok"],
      reached: ["到達", "ok"], todo: ["未着手", ""], doing: ["進行中", "warn"], done: ["完了", "ok"],
      pending: ["未着手", ""], in_progress: ["進行中", "warn"], completed: ["完了", "ok"], blocked: ["止まっている", "bad"], deferred: ["先送り", "muted"],
      active: ["進行中", "warn"], paused: ["一時停止", "muted"],
    },
    priority: { critical: ["最重要", "bad"], high: ["高", "warn"], medium: ["中", ""], low: ["低", ""], P0: ["P0", "bad"], P1: ["P1", "warn"], P2: ["P2", ""], P3: ["P3", ""] },
    verdict: { supported: "支持", not_supported: "反証", undetermined: "判定不能" },
    judged_by: { owner: "本人", decider: "判断者", ai_proxy: "AI の代理" },
  };
  // 表の列（ファイルごと）。fn は行から表示値を作る
  const COLS = {
    hypotheses: [
      { k: "id", h: "ID", cls: "id" }, { k: "kind", h: "種類" }, { k: "claim", h: "主張", cls: "title" }, { k: "status", h: "状態" },
      { k: "priority", h: "優先" }, { k: "due", h: "期限", cls: "date" },
      { k: "_evidence", h: "根拠", cls: "num", fn: (r) => countOf(r.evidence) },
      { k: "_judge", h: "最新の判定", fn: (r) => lastJudgement(r) },
    ],
    issues: [
      { k: "id", h: "ID", cls: "id" }, { k: "question", h: "問い", cls: "title" }, { k: "status", h: "状態" }, { k: "priority", h: "優先" },
      { k: "owner", h: "担当" }, { k: "due", h: "期限", cls: "date" }, { k: "answer", h: "答え", cls: "text" },
    ],
    wbs: [
      { k: "id", h: "ID", cls: "id", indent: true }, { k: "deliverable", h: "成果物", cls: "title" }, { k: "status", h: "状態" },
      { k: "milestone_id", h: "節目" }, { k: "_fc", h: "見込み", cls: "date", fn: (r) => range(r.schedule && r.schedule.forecast) },
      { k: "_ac", h: "実績", cls: "date", fn: (r) => range(r.schedule && r.schedule.actual) }, { k: "owner", h: "担当" }, { k: "depends", h: "依存" },
    ],
    roadmap: [
      { k: "id", h: "ID", cls: "id" }, { k: "milestone", h: "節目", cls: "title" }, { k: "period", h: "時期", cls: "date" }, { k: "status", h: "状態" }, { k: "wbs_ids", h: "WBS" },
    ],
    todo: [
      { k: "id", h: "ID", cls: "id" }, { k: "title", h: "題名", cls: "title" }, { k: "status", h: "状態" }, { k: "owner", h: "担当" },
      { k: "wbs_id", h: "WBS" }, { k: "due", h: "期限", cls: "date" }, { k: "source", h: "出どころ", cls: "text" },
    ],
    context: [
      { k: "name", h: "名前" }, { k: "url", h: "場所", cls: "id" }, { k: "summary", h: "要約", cls: "text" },
    ],
    backlog: [
      { k: "id", h: "ID", cls: "id" }, { k: "name", h: "名前", cls: "title" }, { k: "status", h: "状態" }, { k: "priority", h: "優先" },
      { k: "dependencies", h: "依存" }, { k: "_ac", h: "受入条件", cls: "num", fn: (r) => countOf(r.acceptance_criteria) },
      { k: "scheduled_for", h: "実行時期", cls: "date" }, { k: "due", h: "期限", cls: "date" }, { k: "output", h: "成果物", cls: "text" },
    ],
  };
  // Layer の YAML から表の行を取り出す（registers は rows をサーバが返す）
  function rowsOf(key, info) {
    if (!info) return [];
    if (Array.isArray(info.rows)) return info.rows;
    const d = info.data;
    if (!d || typeof d !== "object") return [];
    if (key === "context") {
      const seen = new Set();
      return (Array.isArray(d.context_documents) ? d.context_documents : []).map((x, i) => {
        if (!x || typeof x !== "object") return { id: "c" + i, name: String(x == null ? "" : x) };
        let id = x.url ? String(x.url) : "c" + i;
        if (seen.has(id)) id += "#" + i;
        seen.add(id);
        return { id, ...x };
      });
    }
    if (key === "backlog") return Array.isArray(d.tasks) ? d.tasks.filter((t) => t && typeof t === "object").map((t, i) => (t.id == null || t.id === "" ? { id: "t" + i, ...t } : t)) : [];
    return [];
  }

  const state = { items: [], index: null, data: null, tab: "hypotheses", filter: "", sort: null, sel: null, sig: "" };
  const known = {}; // id -> file（リンクにするのは今ある ID だけ）

  function valuesText(v) {
    if (v == null) return "";
    if (typeof v !== "object") return String(v).toLowerCase() + " ";
    return (Array.isArray(v) ? v : Object.values(v)).map(valuesText).join("");
  }
  function isUnknown(v) { return v == null || (typeof v === "string" && UNKNOWN.has(v.trim().toLowerCase())); }
  function countOf(v) { return Array.isArray(v) ? String(v.length) : (v ? "1" : ""); }
  function range(s) { if (!s || typeof s !== "object") return ""; const a = s.start || "", b = s.end || ""; return a || b ? `${a}〜${b}` : ""; }
  function lastJudgement(r) {
    const j = Array.isArray(r.judgements) ? r.judgements.filter((x) => x && typeof x === "object") : [];
    if (!j.length) return "";
    const l = j[j.length - 1];
    return `${WORD.verdict[l.verdict] || l.verdict || ""}（${WORD.judged_by[l.judged_by] || l.judged_by || ""}・${l.date || ""}）`;
  }
  function fileOf(id) { if (known[id]) return known[id]; for (const [re, f] of ID_FILE) if (re.test(id)) return f; return null; }
  function idTokens(text) {
    const out = []; let m; ID_TOKEN.lastIndex = 0;
    while ((m = ID_TOKEN.exec(text))) out.push([m.index, m[0]]);
    return out;
  }
  function el(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === "class") e.className = v; else if (k === "text") e.textContent = v; else if (k.startsWith("on")) e.addEventListener(k.slice(2), v); else e.setAttribute(k, v);
    }
    for (const k of kids) if (k != null) e.append(k);
    return e;
  }
  // 文字列の中の ID をリンクにして返す（今ある ID だけ）
  function linkify(text) {
    const frag = document.createDocumentFragment();
    let last = 0;
    for (const [at, id] of idTokens(text)) {
      if (!known[id]) continue;
      if (at > last) frag.append(text.slice(last, at));
      frag.append(el("a", { class: "ref", href: "#", onclick: (ev) => { ev.preventDefault(); ev.stopPropagation(); goTo(id); } }, id));
      last = at + id.length;
    }
    if (last < text.length) frag.append(text.slice(last));
    return frag;
  }
  function badge(key, v) {
    const w = WORD[key] && typeof v === "string" ? WORD[key][v] : undefined;
    if (Array.isArray(w)) return el("span", { class: "badge " + w[1], text: w[0] });
    if (typeof w === "string") return el("span", { class: "badge", text: w });
    if (isUnknown(v)) return el("span", { class: "badge dim", text: v == null ? "未記入" : String(v) });
    return el("span", { class: "badge", text: String(v) });
  }
  function cellValue(col, row) {
    const raw = col.fn ? col.fn(row) : row[col.k];
    if (col.k === "status" || col.k === "priority" || col.k === "kind") return badge(col.k, raw);
    if (Array.isArray(raw)) { const f = document.createDocumentFragment(); raw.forEach((x) => f.append(typeof x === "string" ? linkify(x) : el("span", { text: JSON.stringify(x) }), " ")); return raw.length ? f : el("span", { class: "dim", text: "—" }); }
    if (isUnknown(raw)) return el("span", { class: "dim", text: raw == null || raw === "" ? "—" : String(raw) });
    const s = String(raw);
    if (col.cls === "text") return el("div", { class: "clip", title: s }, linkify(s));
    if (col.cls === "title") return el("div", { class: "full" }, linkify(s));  // 題名の列は切らずに全文を折り返す
    return linkify(s);
  }

  // --- 描画 ---------------------------------------------------------------
  function renderSources() {
    const sel = $("#source"); sel.replaceChildren();
    for (const it of state.items) {
      const tag = it.origin === "path" ? "指定: " : "";
      const form = it.form === "sheets" ? "Sheets" : it.form === "registers" ? "旧 registers" : it.form === "plain" ? "一般の YAML" : "Layer だけ";
      sel.append(el("option", { value: String(it.index), text: `${tag}${it.name}${it.scope_id ? "（" + it.scope_id + "）" : ""} · ${form}` }));
    }
    if (state.index != null) sel.value = String(state.index);
  }
  function renderHead() {
    const d = state.data; if (!d) return;
    $("#head-name").textContent = d.display_name || d.name || "";
    const bits = [];
    if (d.scope_id) bits.push(d.scope_id);
    if (d.registers) bits.push(d.registers); else if (d.layer) bits.push(d.layer); else if (d.plain) bits.push(d.plain);
    $("#head-meta").textContent = bits.join(" · ");
  }
  function renderTabs() {
    const nav = $("#tabs"); nav.replaceChildren();
    const files = state.data ? state.data.files : {};
    let lastGroup = null;
    for (const f of FILES) {
      const info = files[f.key];
      if (!info) continue;  // 箱の無い Layer・Layer の無い箱では、その組のタブを出さない
      if (lastGroup && lastGroup !== f.group) nav.append(el("span", { class: "tab-sep", text: "｜" }));
      lastGroup = f.group;
      const n = rowsOf(f.key, info).length;
      const count = (f.key === "intent" || f.key === "plain") ? "" : (info.exists ? String(n) : "なし");
      const b = el("button", { class: "tab", role: "tab", "aria-selected": String(state.tab === f.key), onclick: () => { state.tab = f.key; state.sel = null; state.sort = null; pushHash(); render(); } }, f.label, count ? el("span", { class: "n", text: count }) : null);
      if (!info.exists && !n) b.disabled = true;
      nav.append(b);
    }
  }
  function rowsFor(key) {
    const info = state.data && state.data.files[key];
    let rows = rowsOf(key, info).slice();
    const q = state.filter.trim().toLowerCase();
    if (q) rows = rows.filter((r) => valuesText(r).includes(q));
    if (state.sort) {
      const { k, dir } = state.sort; const col = COLS[key].find((c) => c.k === k);
      const val = (r) => { const v = col && col.fn ? col.fn(r) : r[k]; return isUnknown(v) ? "￿" : String(Array.isArray(v) ? v.join(",") : v); };
      rows.sort((a, b) => val(a).localeCompare(val(b), "ja", { numeric: true }) * dir);
    }
    return rows;
  }
  function renderTable() {
    const wrap = $("#table-wrap"); wrap.replaceChildren();
    const key = state.tab, info = state.data && state.data.files[key];
    if (!info) { wrap.append(el("div", { class: "empty", text: "置き場を選んでください" })); return; }
    if (info.error) wrap.append(el("div", { class: "errbox", text: `${key === "plain" && state.data.plain ? state.data.plain.split("/").pop() : key + ".yaml"}: ${info.error}` }));
    if (key === "intent") { renderIntent(wrap, info); return; }
    if (key === "plain") { renderPlain(wrap, info); return; }
    if (key === "backlog" && state.data.scope_id) {
      wrap.append(el("div", { class: "hint" }, "進み具合の図は ", el("a", { class: "ext", href: BACKLOG_LIVE + "?layer=" + encodeURIComponent(state.data.scope_id), target: "_blank", rel: "noopener" }, "BacklogLive で見る"), "（起動していないときは開けません）"));
    }
    if (key === "issues" && info.charter && typeof info.charter === "object") {
      const c = el("div", { class: "charter" });
      for (const k of ["change_conditions", "exit_conditions"]) {
        const v = info.charter[k];
        c.append(el("h3", { text: LABEL[k] || k }));
        const ul = el("ul");
        (Array.isArray(v) ? v : [v]).forEach((x) => ul.append(el("li", { class: isUnknown(x) ? "dim" : "" }, isUnknown(x) ? String(x == null ? "未記入" : x) : linkify(String(x)))));
        c.append(ul);
      }
      wrap.append(c);
    }
    const rows = rowsFor(key);
    if (!rows.length) { wrap.append(el("div", { class: "empty", text: info.exists ? "行がありません" : `${key}.yaml はありません` })); return; }
    const cols = COLS[key] || COLS.todo;
    const thead = el("thead"), tr = el("tr");
    for (const c of cols) {
      const arrow = state.sort && state.sort.k === c.k ? (state.sort.dir > 0 ? "▲" : "▼") : "";
      tr.append(el("th", { onclick: () => { state.sort = state.sort && state.sort.k === c.k ? (state.sort.dir > 0 ? { k: c.k, dir: -1 } : null) : { k: c.k, dir: 1 }; render(); } }, c.h, el("span", { class: "arrow", text: arrow })));
    }
    thead.append(tr);
    const tbody = el("tbody");
    for (const r of rows) {
      const id = String(r.id == null ? "" : r.id);
      const trr = el("tr", { "data-id": id, class: state.sel === id ? "sel" : "", onclick: () => { state.sel = id; pushHash(); render(); } });
      for (const c of cols) {
        const td = el("td", { class: c.cls || "" }, cellValue(c, r));
        if (c.indent) { const depth = Math.min(3, (id.match(/\./g) || []).length); if (depth) td.classList.add("indent-" + depth); }
        trr.append(td);
      }
      tbody.append(trr);
    }
    wrap.append(el("table", {}, thead, tbody));
    if (state.sel) { const t = tbody.querySelector(`tr[data-id="${CSS.escape(state.sel)}"]`); if (t && t.scrollIntoView) t.scrollIntoView({ block: "nearest" }); }
  }
  function renderValue(v, depth) {
    if (v == null || v === "") return el("span", { class: "dim", text: "—" });
    if (typeof v === "string") return isUnknown(v) ? el("span", { class: "dim", text: v }) : el("span", {}, linkify(v));
    if (typeof v !== "object") return el("span", { text: String(v) });
    if (Array.isArray(v)) {
      if (!v.length) return el("span", { class: "dim", text: "—" });
      const ul = el("ul");
      v.forEach((x) => ul.append(el("li", {}, renderValue(x, depth + 1))));
      return ul;
    }
    const box = el("div", { class: depth ? "sub" : "" });
    const dl = el("dl", { class: "kv" });
    for (const [k, x] of Object.entries(v)) { dl.append(el("dt", { text: LABEL[k] || k })); dl.append(el("dd", {}, renderValue(x, depth + 1))); }
    box.append(dl); return box;
  }
  // 一般の YAML: 最上位のキーを見出し、mapping は キー: 値、list は箇条書き、mapping の list は札、深い所は折りたたみ
  const CARD_PAGE = 200;   // 札はこの数ずつ出す（大きい YAML で固まらないように）
  const KEY_PAGE = 200;    // mapping のキーはこの数ずつ
  const LI_PAGE = 500;     // スカラーだけの list はこの数ずつ
  // 親に N 件ずつ足し、残りがあれば「さらに表示」を置く
  function paged(parent, total, page, addRange, unit) {
    const step = (from) => {
      const to = Math.min(total, from + page);
      addRange(from, to);
      if (to < total) {
        const more = el("button", { class: "tab y-more", onclick: () => { more.remove(); step(to); } }, `さらに ${Math.min(page, total - to)} ${unit}を表示（残り ${total - to}）`);
        parent.append(more);
      }
    };
    step(0);
  }
  const OPEN_CARDS = 50;   // 浅い所で最初から開く札の数
  function scalarNode(v) {
    if (v == null) return el("span", { class: "dim", text: "—" });
    if (v === "") return el("span", { class: "dim", text: "（空の文字列）" });
    if (typeof v === "boolean") return el("span", { class: "badge", text: v ? "はい" : "いいえ" });
    if (typeof v === "number") return el("span", { class: "num-val", text: String(v) });
    const t = String(v);
    return isUnknown(t) ? el("span", { class: "dim", text: t }) : el("span", { class: t.includes("\n") ? "pre" : "" }, linkify(t));
  }
  function cardTitle(m) {
    for (const k of ["title", "name", "id", "claim", "question", "summary", "label"]) {
      if ((typeof m[k] === "string" && m[k]) || typeof m[k] === "number") return String(m[k]);
    }
    const first = Object.values(m).find((x) => typeof x === "string" && x && x.length <= 40);  // 長文を題名にしない
    return first || "";
  }
  function clipTitle(t) { return t; }  // 札の題名も全文（折り返しは CSS の .y-title）
  // details の中身は初めて開いたときに作る（閉じたままの巨大な木を作らない）
  function lazyDetails(d, build) {
    if (d.open) { d.append(build()); return d; }
    d.addEventListener("toggle", () => { if (d.open && !d.dataset.built) { d.dataset.built = "1"; d.append(build()); } }, { once: false });
    return d;
  }
  function treeNode(v, depth) {
    if (v == null || typeof v !== "object") return scalarNode(v);
    if (Array.isArray(v)) {
      if (!v.length) return el("span", { class: "dim", text: "（空）" });
      const allScalar = v.every((x) => x == null || typeof x !== "object");
      if (allScalar) {
        const box = el("div"); const ul = el("ul", { class: "y-list" }); box.append(ul);
        paged(box, v.length, LI_PAGE, (from, to) => { for (let i = from; i < to; i++) ul.append(el("li", {}, scalarNode(v[i]))); }, "件");
        return box;
      }
      const wrap = el("div", { class: "y-cards" });
      paged(wrap, v.length, CARD_PAGE, (from, to) => {
        for (let i = from; i < to; i++) {
          const x = v[i];
          if (x && typeof x === "object" && !Array.isArray(x)) {
            const d = el("details", { class: "y-card" }); if (depth < 2 && i < OPEN_CARDS) d.open = true;
            d.append(el("summary", {}, el("span", { class: "y-idx", text: String(i + 1) }), " ", el("span", { class: "y-title" }, linkify(clipTitle(String(cardTitle(x)))))));
            wrap.append(lazyDetails(d, () => mapNode(x, depth + 1)));
          } else wrap.append(el("div", { class: "y-item" }, el("span", { class: "y-idx", text: String(i + 1) }), " ", treeNode(x, depth + 1)));
        }
      }, "件");
      return wrap;
    }
    return mapNode(v, depth);
  }
  function mapNode(m, depth) {
    const keys = Object.keys(m);
    if (!keys.length) return el("span", { class: "dim", text: "（空）" });
    const box = el("div"); const dl = el("dl", { class: "y-map" }); box.append(dl);
    paged(box, keys.length, KEY_PAGE, (from, to) => {
      for (let i = from; i < to; i++) {
        const k = keys[i], v = m[k];
        const big = v && typeof v === "object" && (Array.isArray(v) ? v.length > 0 : Object.keys(v).length > 0);
        dl.append(el("dt", { class: "y-key", text: k }));
        const small = big && !Array.isArray(v) && Object.keys(v).length === 1;  // 1項目だけの mapping は畳まない
        if (big && depth >= 3 && !small) { const d = el("details", { class: "y-fold" }); d.append(el("summary", { text: Array.isArray(v) ? `${v.length} 件` : `${Object.keys(v).length} 項目` })); dl.append(el("dd", {}, lazyDetails(d, () => treeNode(v, depth + 1)))); }
        else dl.append(el("dd", {}, treeNode(v, depth + 1)));
      }
    }, "項目");
    return box;
  }
  function renderPlain(wrap, info) {
    const d = info.data;
    if (info.error && (d === null || d === undefined)) return;  // 壊れているときは案内1行だけ
    if (d === null || d === undefined) { wrap.append(el("div", { class: "empty", text: info.exists ? "中身が空です" : "ファイルがありません" })); return; }
    if (typeof d !== "object") { wrap.append(section("値", scalarNode(d))); return; }
    if (Array.isArray(d)) { wrap.append(section("一覧（" + d.length + " 件）", treeNode(d, 0))); return; }
    const entries = Object.entries(d);
    paged(wrap, entries.length, KEY_PAGE, (from, to) => {
      for (let i = from; i < to; i++) {
        const [k, v] = entries[i];
        const sec = el("section", { class: "sec y-top" }, el("h3", { class: "y-h", text: k }));
        sec.append(treeNode(v, 1)); wrap.append(sec);
      }
    }, "項目");
  }
  function section(title, body) { return el("section", { class: "sec" }, el("h3", { text: title }), body); }
  function renderIntent(wrap, info) {
    const d = info.data;
    if (!d || typeof d !== "object") { wrap.append(el("div", { class: "empty", text: "intent.yaml を読めません" })); return; }
    const head = el("div", { class: "intent-head" });
    head.append(el("div", { class: "intent-title" }, el("span", { class: "id", text: String(d.scope_id || "") }), " ", String(d.display_name || d.scope_name || "")));
    const meta = el("div", { class: "intent-meta" });
    for (const [k, v] of [["status", d.status], ["workflow_depth", d.workflow_depth], ["mode", d.mode], ["deadline", d.deadline], ["owner", d.owner]]) {
      if (v == null) continue;
      meta.append(el("span", { class: "meta" }, el("span", { class: "k", text: (LABEL[k] || k) + " " }), k === "status" ? badge("status", v) : el("span", { text: String(v) })));
    }
    head.append(meta); wrap.append(head);
    const g = d.goal && typeof d.goal === "object" && !Array.isArray(d.goal) ? d.goal : {};
    const goalIsMap = d.goal && typeof d.goal === "object" && !Array.isArray(d.goal);
    const desc = goalIsMap ? (g.description == null ? "" : g.description) : d.goal;
    wrap.append(section("ゴール", typeof desc === "string" ? (desc ? el("p", { class: "goal" }, linkify(desc)) : el("span", { class: "dim", text: "—" })) : renderValue(desc, 0)));
    const sc = Array.isArray(g.success_criteria) ? g.success_criteria : [];
    const ol = el("ol"); sc.forEach((x) => ol.append(el("li", {}, renderValue(x, 1))));
    wrap.append(section("成功条件", sc.length ? ol : (g.success_criteria != null ? renderValue(g.success_criteria, 0) : el("span", { class: "dim", text: "—" }))));
    const gRest = Object.fromEntries(Object.entries(g).filter(([k]) => k !== "description" && k !== "success_criteria"));
    if (Object.keys(gRest).length) wrap.append(section("ゴールのそのほか（範囲外・候補・経緯など）", renderValue(gRest, 0)));
    if (d.classification) wrap.append(section("分類", renderValue(d.classification, 0)));
    if (d.membership) wrap.append(section("業務所属", renderValue(d.membership, 0)));
    const rp = d.request_provenance;
    if (rp && typeof rp === "object") {
      const o = rp.original_request && typeof rp.original_request === "object" && !Array.isArray(rp.original_request) ? rp.original_request : null;
      const box = el("div", {});
      if (o && typeof o.text === "string") box.append(el("blockquote", { class: "quote" }, o.text), el("div", { class: "muted-text", text: (o.source ? "出典: " + String(o.source) : "") + (rp.via ? "　窓口: " + String(rp.via) : "") }));
      else box.append(renderValue(rp.original_request, 0), rp.via ? el("div", { class: "muted-text", text: "窓口: " + String(rp.via) }) : null);
      const ch = Array.isArray(rp.explicit_changes) ? rp.explicit_changes : [];
      if (ch.length) { const ul = el("ul"); ch.forEach((x) => ul.append(el("li", {}, renderValue(x, 1)))); box.append(el("div", { class: "muted-text", text: "明示の変更:" }), ul); }
      wrap.append(section("原要求", box));
    }
    const shown = new Set(["scope_id", "display_name", "scope_name", "status", "workflow_depth", "mode", "deadline", "owner", "goal", "classification", "membership", "request_provenance"]);
    const rest = Object.fromEntries(Object.entries(d).filter(([k]) => !shown.has(k)));
    if (Object.keys(rest).length) wrap.append(section("そのほかの欄", renderValue(rest, 0)));
  }
  function renderDetail() {
    const aside = $("#detail");
    const rows = rowsOf(state.tab, state.data && state.data.files[state.tab]);
    const row = state.sel ? rows.find((r) => String(r.id) === state.sel) : null;
    if (!row) { aside.hidden = true; aside.replaceChildren(); return; }
    aside.hidden = false; aside.replaceChildren();
    const title = row.claim || row.question || row.deliverable || row.milestone || row.title || row.name || "";
    aside.append(el("h2", {}, el("span", { class: "id", text: String(row.id) }), el("span", { class: "title", text: String(title) }), el("button", { class: "close", title: "閉じる", onclick: () => { state.sel = null; pushHash(); render(); } }, "×")));
    const order = Object.keys(row).filter((k) => k !== "id");
    const dl = el("dl", { class: "kv" });
    for (const k of order) {
      dl.append(el("dt", { text: LABEL[k] || k }));
      const v = row[k];
      dl.append(el("dd", {}, (k === "status" || k === "priority" || k === "kind") ? badge(k, v) : renderValue(v, 0)));
    }
    aside.append(dl);
  }
  function ensureTab() {
    const files = state.data ? state.data.files : null;
    if (!files || files[state.tab]) return;
    const first = FILES.find((f) => files[f.key] && (files[f.key].exists || rowsOf(f.key, files[f.key]).length));
    const prefer = files.plain ? "plain" : (files.intent && !files.hypotheses ? "intent" : null);
    state.tab = prefer || (first ? first.key : state.tab);
    state.sel = null; state.sort = null; pushHash();
  }
  function render() {
    ensureTab(); renderHead(); renderTabs();
    const f = $("#filter"); f.disabled = state.tab === "plain"; f.placeholder = state.tab === "plain" ? "（一般の YAML では絞り込みは使えません）" : "絞り込み（ID・言葉）";
    renderTable(); renderDetail();
  }

  function goTo(id) {
    const f = fileOf(id); if (!f) return;
    state.tab = f; state.sel = id; state.filter = ""; $("#filter").value = ""; pushHash(); render();
  }
  function rebuildKnown() {
    for (const k of Object.keys(known)) delete known[k];
    const files = state.data ? state.data.files : {};
    for (const f of FILES) { if (f.key === "context" || f.key === "intent") continue; for (const r of rowsOf(f.key, files[f.key])) if (r.id != null) known[String(r.id)] = f.key; }
  }

  // --- URL ハッシュ（#i=0&tab=wbs&id=W2.1） ---------------------------------
  function pushHash() {
    const p = new URLSearchParams();
    if (state.index != null) p.set("i", String(state.index));
    p.set("tab", state.tab);
    if (state.sel) p.set("id", state.sel);
    history.replaceState(null, "", "#" + p.toString());
  }
  function readHash() {
    const p = new URLSearchParams(location.hash.slice(1));
    if (p.get("i") && /^\d+$/.test(p.get("i"))) state.index = Number(p.get("i"));
    if (p.get("tab") && FILES.some((f) => f.key === p.get("tab"))) state.tab = p.get("tab");
    if (p.get("id")) state.sel = p.get("id");
  }

  // --- 取得 -----------------------------------------------------------------
  async function getJSON(url) { const r = await fetch(url, { cache: "no-store" }); return r.json(); }
  async function loadList() {
    const j = await getJSON("/api/list");
    state.items = j.items || [];
    if (state.index == null || !state.items.some((x) => x.index === state.index)) state.index = state.items.length ? state.items[0].index : null;
    renderSources();
  }
  async function poll() {
    const st = $("#status");
    try {
      if (state.index == null) { await loadList(); }
      if (state.index == null) { st.textContent = "箱が見つかりません（--path で渡すか Flow に箱のある Layer を置く）"; st.classList.add("err"); return; }
      const j = await getJSON("/api/state?i=" + state.index);
      if (!j.ok) { st.textContent = j.error || "読めません"; st.classList.add("err"); return; }
      const sig = JSON.stringify(Object.fromEntries(Object.entries(j.files).map(([k, v]) => [k, [v.mtime, v.error]])));
      const changed = sig !== state.sig;
      state.data = j; state.sig = sig;
      if (changed) { rebuildKnown(); render(); }
      const errs = Object.values(j.files).filter((v) => v.error).length;
      st.classList.toggle("err", errs > 0);
      st.textContent = errs ? `${errs} ファイルが読めません（最後の正常な状態を表示）` : `更新 ${j.generated_at}`;
    } catch (e) {
      st.textContent = "サーバに届きません"; st.classList.add("err");
    }
  }

  // --- 起動 -----------------------------------------------------------------
  readHash();
  $("#source").addEventListener("change", (ev) => { state.index = Number(ev.target.value); state.sel = null; state.sig = ""; pushHash(); poll(); });
  $("#filter").addEventListener("input", (ev) => { state.filter = ev.target.value; if (state.tab !== "plain") renderTable(); });
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && state.sel) { state.sel = null; pushHash(); render(); } });
  window.addEventListener("hashchange", () => { const before = state.index; readHash(); if (state.index !== before) { state.sig = ""; renderSources(); } poll().then(render); });
  loadList().then(poll).catch(() => poll());
  setInterval(() => { poll(); if (Math.random() < 0.1) loadList().catch(() => {}); }, POLL_MS);
})();
