#!/usr/bin/env python3
"""project_match — 依頼の言葉を既存の案件に当てる部品（ppm-collection が使う）。

当て方:
  - 案件側の語（Registry の名前・目的、業務Project があればその表示名・目的）が依頼の文にいくつ当たったかで数える
  - 語の重みは「何件の案件に出る語か」で決める（多くの案件に出る一般語は軽い）
  - 案件側の語の数の平方根で割り、Goal の長い案件が有利にならないようにする
  - 題名の語に当たった分は3倍
公開範囲の守り: private の依頼は read_domain が private の案件にだけ、company の依頼は private の案件に当てない。
業務Project の表（programs・business_projects・program_memberships・business_project_links。`business_registry.py init`
で作ったときだけある）が無い DB でも止まらない。そのときは所属の手がかり無しで、Registry の projects だけで当てる。
Registry は読むだけ（呼ぶ側が読み取り専用で開いた接続を渡す）。ファイルも DB も書かない。
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import yaml

STOP = set("""の に を は が で と も から まで へ や か な こと もの これ それ あれ する した して います ます です
the and for with that this from have will about into your our are was were
確認 資料 会議 共有 対応 検討 今日 明日 今回 次回 内容 必要 可能 進める 進め 全体 本人 以下 以上 日時 参加
スキル 状態 プロダクト 本番 実行 仕組 経由 改善 設計 利用 作成 整理 管理 開発 運用 試行 検証 準備 相談 方針 課題 状況 結果 目的 範囲 予定 時間 場合 自分 一度 最初 最後 部分 問題 機能 画面 情報 案件 作業 担当 判断 説明 実装 変更 追加 記録 文書 入力 出力 使う 作る 見る""".split())
TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}|[゠-ヿー]{2,}|[一-鿿]{2,}|[Ａ-ｚ０-９]{2,}")
# 2文字ずつに分けるのは3文字以上の漢字のひと続きだけ（短い依頼文で語が足りないときの補い）。
# カタカナは外来語の1語として既に当たるので分けない（分けると「プロジェクト」などで当たりが水増しされる）
CJK_RUN = re.compile(r"[一-鿿]{3,}")
BUSINESS_TABLES = ("programs", "business_projects", "program_memberships", "business_project_links")


def tokens(text: str, bigrams: bool = False) -> list[str]:
    """語の一覧（小文字・STOP を除く）。bigrams=True のときは、3文字以上の漢字のひと続きを2文字ずつにも分けて足す。"""
    out = []
    for t in TOKEN.findall(text or ""):
        t2 = t.lower()
        if t2 in STOP:
            continue
        out.append(t2)
    if bigrams:
        for run in CJK_RUN.findall(text or ""):
            # ひと続きの中の一般語（STOP）を先に切り落とし、残りの切れ端だけを2文字ずつにする（「スキル」から「スキ」「キル」を作らない）
            for seg in _STOP_CJK.split(run):
                if len(seg) < 2:
                    continue
                for i in range(len(seg) - 1):
                    g = seg[i:i + 2]
                    if g not in STOP:
                        out.append(g)
    return out


_STOP_CJK = re.compile("|".join(sorted((re.escape(w) for w in STOP if re.fullmatch(r"[゠-ヿー一-鿿]{2,}", w)), key=len, reverse=True)))


def domain_allowed(domain: str | None, source_vis: str) -> bool:
    """公開範囲の守り。private の依頼は private の案件だけ、company の依頼は private の案件を除く。"""
    if source_vis == "private" and domain != "private":
        return False
    if source_vis == "company" and domain == "private":
        return False
    return True


def layer_domain_hint(root: Path, layer: str | None) -> str | None:
    """Program に入っていない案件の公開範囲を、Layer の intent.yaml の membership.read_domain（work／private）だけから取る。
    書かれていなければ None（推測しない）。"""
    if not layer:
        return None
    d = (root / layer).resolve()
    try:
        d.relative_to((root / "Flow").resolve())
        it = yaml.safe_load((d / "intent.yaml").read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return None
    m = it.get("membership") if isinstance(it, dict) else None
    rd = m.get("read_domain") if isinstance(m, dict) else None
    return rd if rd in ("private", "work") else None


def business_tables_present(con) -> bool:
    """業務Project の4つの表がそろっているか（無い DB では所属の手がかり無しで照らす）。"""
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    return all(t in names for t in BUSINESS_TABLES)


def load_side(con, root: Path, statuses: tuple[str, ...], normalize, bigrams: bool = False) -> dict:
    """Registry から案件と案件側の語を集める。
    normalize: top_page_url をリポジトリ相対の Flow/… に直す関数（Flow の下でなければ None）。Layer の無い行は layer=None で残す。
    返り値: {projects: [行], side: {id: {toks, prog_uid, linked_biz}}, df: {語: 件数}, progs: {uid: 行}, business_tables: bool}"""
    marks = ",".join("?" for _ in statuses)
    sql = f"SELECT id, scope_id, name, goal, status, top_page_url FROM projects WHERE status IN ({marks})"
    projects = [dict(r) for r in con.execute(sql, statuses).fetchall()]
    for r in projects:
        r["layer"] = normalize(root, r["top_page_url"]) if r["top_page_url"] else None
        r["top_page_url"] = r["layer"]
    has_biz = business_tables_present(con)
    biz, progs, memb, bmemb, link_by_pid = {}, {}, {}, {}, {}
    if has_biz:
        biz = {r["business_uid"]: dict(r) for r in con.execute(
            "SELECT business_uid, display_name, purpose FROM business_projects WHERE state='active'").fetchall()}
        progs = {r["program_uid"]: dict(r) for r in con.execute(
            "SELECT program_uid, display_name, read_domain FROM programs").fetchall()}
        memb = {r["project_id"]: r["program_uid"] for r in con.execute(
            "SELECT project_id, program_uid FROM program_memberships WHERE target_kind='aiplc_project' AND state='confirmed'").fetchall()}
        bmemb = {r["business_uid"]: r["program_uid"] for r in con.execute(
            "SELECT business_uid, program_uid FROM program_memberships WHERE target_kind='business_project' AND state='confirmed'").fetchall()}
        for link in con.execute(
                "SELECT project_id, business_uid, relation_type FROM business_project_links WHERE state='confirmed'").fetchall():
            link_by_pid.setdefault(link["project_id"], []).append(link)
    side: dict[int, dict] = {}
    df: dict[str, int] = {}
    for r in projects:
        parts = [r["name"] or "", r["goal"] or ""]
        prog_uid = memb.get(r["id"])
        linked_biz = set()
        for link in link_by_pid.get(r["id"], []):
            b = biz.get(link["business_uid"])
            if b:
                parts += [b["display_name"], b["purpose"]]
                linked_biz.add(b["display_name"])
                prog_uid = prog_uid or bmemb.get(link["business_uid"])
        toks = set(tokens(" ".join(p or "" for p in parts), bigrams)) - STOP
        side[r["id"]] = {"toks": toks, "prog_uid": prog_uid, "linked_biz": linked_biz}
        for t in toks:
            df[t] = df.get(t, 0) + 1
    return {"projects": projects, "side": side, "df": df, "progs": progs, "business_tables": has_biz}


def weight(t: str, df: dict[str, int]) -> float:
    return 1.0 / (1.0 + math.log(1 + df.get(t, 0)))  # 1件にしか出ない語 ≈ 0.59、20件に出る語 ≈ 0.25


def score(side_toks: set[str], body_toks: set[str], title_toks: set[str], df: dict[str, int]):
    """(点数, 本文に当たった語, 題名に当たった語)。どちらにも当たらなければ点数は None。"""
    hits = side_toks & body_toks
    title_hits = side_toks & title_toks
    if not hits and not title_hits:
        return None, hits, title_hits
    base = sum(weight(t, df) for t in (hits - title_hits)) + 3.0 * sum(weight(t, df) for t in title_hits)
    return round(10.0 * base / math.sqrt(max(len(side_toks), 1)), 2), hits, title_hits
