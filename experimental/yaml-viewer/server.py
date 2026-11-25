#!/usr/bin/env python3
"""YamlViewer — AI-PLC が出す YAML を読みやすく見る閲覧専用のローカルサーバ。

対象: AIPM の箱の registers 5ファイル（hypotheses・issues・wbs・roadmap・todo。新しい形は Sheets/ 直下、
古い形は Documents/aipm_project/registers/）と、Layer の intent・context・backlog。
127.0.0.1 だけで listen し、GET 以外は受けない。何も書かない。
画面から任意のパスは受け取らず、サーバが見つけた（または --path で渡された）一覧の番号だけを受ける。
YAML が壊れていても最後の正常な状態を返す。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

import yaml

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}
DEFAULT_PORT = 8772
REPO_ROOT = HERE.parents[1]
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
REGISTER_FILES = ("hypotheses", "issues", "wbs", "roadmap", "todo")
LIST_KEYS = {"hypotheses": "hypotheses", "issues": "issues", "wbs": "wbs", "roadmap": "roadmap", "todo": "todo"}
LAYER_FILES = ("intent", "context", "backlog")
PRUNE_DIRS = frozenset({"documents", "context", "agents", "node_modules", "__pycache__", "sheets", "sublayers_bak"})
MONTH_DIR = re.compile(r"^\d{6}$")
DAY_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SCAN_TTL = 30.0
RELOAD_TTL = 1.5
MAX_BYTES = 8 * 1024 * 1024


MAX_NODES = 200_000


def _jsonable(value: Any, _stack: Optional[set] = None, _count: Optional[list] = None) -> Any:
    """YAML の値を JSON にできる形に直す（日付キー・日付・nan・循環）。循環と alias の爆発は例外。"""
    stack = _stack if _stack is not None else set()
    count = _count if _count is not None else [0]
    count[0] += 1
    if count[0] > MAX_NODES:
        raise ValueError(f"要素が多すぎます（{MAX_NODES} 超。大きすぎるか alias の展開）")
    if isinstance(value, (str, bool, int)) or value is None:
        return value
    if isinstance(value, float):
        return value if value == value and value not in (float("inf"), float("-inf")) else str(value)
    if isinstance(value, (dict, list, tuple, set)):
        if id(value) in stack:
            raise ValueError("循環した参照（alias）があります")
        stack.add(id(value))
        try:
            if isinstance(value, dict):
                return {_key_name(k): _jsonable(v, stack, count) for k, v in value.items()}
            return [_jsonable(v, stack, count) for v in value]
        finally:
            stack.discard(id(value))
    return str(value)  # date・datetime など


def _key_name(k: Any) -> str:
    """mapping のキーの表示名（YAML の語で。True/None を Python 風にしない）。"""
    if k is True:
        return "true"
    if k is False:
        return "false"
    if k is None:
        return "null"
    return str(k)


HARD_ERROR_PREFIXES = ("ファイルが大きすぎます", "要素が多すぎます")


def _read_yaml(path: Path, base: Optional[Path] = None) -> Any:
    if base is not None and not path.resolve().is_relative_to(base.resolve()):
        raise ValueError("置き場の外のファイル（symlink）は読みません")
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("ファイルが大きすぎます（8MB 超）")
    docs = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
    data = docs[0] if len(docs) == 1 else (None if not docs else docs)  # `---` で区切った複数のドキュメントは一覧にする
    return _jsonable(data)


def _err_text(exc: Exception) -> str:
    mark = getattr(exc, "problem_mark", None)
    problem = getattr(exc, "problem", None)
    if mark is not None and problem:
        return f"{type(exc).__name__}: {problem}（{mark.line + 1} 行目 {mark.column + 1} 文字目）"
    return f"{type(exc).__name__}: {str(exc)[:120]}"


def _stat_ns(path: Path) -> Optional[int]:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def _file_key(path: Path) -> Optional[tuple[int, int, int]]:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size, st.st_ino)


def _iso(ns: Optional[int]) -> Optional[str]:
    if ns is None:
        return None
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ns / 1e9))


# --- 置き場の探索 -----------------------------------------------------------

def registers_dir_of(path: Path) -> Optional[Path]:
    """渡されたパス（箱・Layer・registers フォルダのどれでも）から registers の置き場を決める。"""
    cands = [path, path / "Sheets", path / "Documents" / "aipm_project" / "registers", path / "registers"]
    for c in cands:
        if c.is_dir() and any((c / f"{f}.yaml").is_file() for f in REGISTER_FILES):
            return c
    return None


def layer_dir_of(path: Path) -> Optional[Path]:
    """渡されたパスから Layer（intent.yaml のあるフォルダ）を決める。registers から上へ辿る。"""
    p = path
    for _ in range(6):
        if (p / "intent.yaml").is_file():
            return p
        if p.parent == p:
            break
        p = p.parent
    return None


def _is_date_tree(flow_root: Path, folder: Path) -> bool:
    try:
        rel = folder.relative_to(flow_root).parts
    except ValueError:
        return False
    return len(rel) >= 2 and bool(MONTH_DIR.match(rel[0])) and bool(DAY_DIR.match(rel[1]))


def scan_flow(flow_root: Path, months: int = 3) -> list[Path]:
    """Flow の新しい月から months か月分の Layer（intent.yaml のあるフォルダ）を集める。"""
    if not flow_root.is_dir():
        return []
    month_dirs = sorted((d for d in flow_root.iterdir() if d.is_dir() and MONTH_DIR.match(d.name)), reverse=True)[:months]
    found: list[Path] = []
    for m in month_dirs:
        for dirpath, dirnames, filenames in os.walk(m, followlinks=False):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d.lower() not in PRUNE_DIRS]
            if "intent.yaml" in filenames:
                found.append(Path(dirpath))
    return found


# --- 読み込み ---------------------------------------------------------------

class YamlFile:
    """1つの YAML を、壊れていても最後の正常な状態を保って読む。"""

    def __init__(self, path: Path, base: Optional[Path] = None):
        self.path = path
        self.base = base
        self._key: Optional[tuple[int, int, int]] = None
        self._good: Any = None
        self._error: Optional[str] = None
        self._retry = True   # エラー中に同じ mtime でも読み直すか（大きすぎる・要素が多すぎる・深すぎるは読み直さない）
        self._checked = 0.0
        self._lock = threading.Lock()

    def read(self) -> dict:
        with self._lock:
            now = time.monotonic()
            key = _file_key(self.path)
            if now - self._checked >= RELOAD_TTL or key != self._key:
                self._checked = now
                if key is None:
                    self._key = None
                    self._error = "ファイルがありません" if self._good is None else "ファイルが見つかりません（最後の正常な状態を表示）"
                elif key != self._key or (self._error and self._retry):
                    try:
                        self._good = _read_yaml(self.path, self.base)
                        self._error, self._retry = None, True
                    except Exception as exc:  # 保存途中・不正 YAML・JSON にできない値
                        self._error = f"読めませんでした（{_err_text(exc)}）"
                        self._retry = not (isinstance(exc, RecursionError) or str(exc).startswith(HARD_ERROR_PREFIXES))
                    self._key = key
            return {"exists": key is not None, "data": self._good, "error": self._error, "mtime": _iso(key[0] if key else None)}


def _rows(data: Any, key: str) -> tuple[list[dict], Optional[str]]:
    """一覧の行と、形が契約と違うときの説明。空ファイル（None）は行なし・警告なし。"""
    if data is None:
        return [], None
    if not isinstance(data, dict):
        return [], f"形が契約と違います（最上位が {type(data).__name__} で、{key}: の mapping ではありません）"
    rows = data.get(key)
    if rows is None:
        return [], f"形が契約と違います（{key}: の欄がありません）"
    if not isinstance(rows, list):
        return [], f"形が契約と違います（{key} が一覧（list）ではありません）"
    bad = sum(1 for r in rows if not isinstance(r, dict))
    return [r for r in rows if isinstance(r, dict)], (f"{bad} 行が mapping ではないので飛ばしました" if bad else None)


class Source:
    """1つの置き場（箱と、あればその Layer。どちらでもないファイルは「一般の YAML」として1ファイルだけ）。"""

    def __init__(self, index: int, path: Path, repo_root: Path, origin: str):
        self.index = index
        self.origin = origin  # "path"（--path）/ "flow"
        self.plain: Optional[Path] = None
        self.opened: Optional[str] = None  # --path にファイルを渡したとき、そのファイル名（拡張子なし）
        if path.is_file():
            self.opened = path.stem
            parent = path.parent
            # 親が registers の置き場そのもの（5ファイルのどれかがある）か Layer の直下（intent.yaml がある）なら箱・Layer として扱い、
            # それ以外（Documents の中の YAML・設定ファイルなど）は一般の YAML
            # 「registers の5ファイルの1つで、隣に別の registers のファイルもある」か「intent/context/backlog の1つで、隣に intent.yaml がある」
            # ときだけ箱・Layer として開く。それ以外（variables.yaml・Sheets/meta.yaml・無関係な todo.yaml など）は一般の YAML
            others = [f for f in REGISTER_FILES if f != path.stem and (parent / f"{f}.yaml").is_file()]
            in_box_folder = parent.name in ("Sheets", "registers") and layer_dir_of(parent) is not None  # 1ファイルだけの箱
            as_register = path.stem in REGISTER_FILES and (bool(others) or in_box_folder)
            as_layer = path.stem in LAYER_FILES and (parent / "intent.yaml").is_file()
            if not as_register and not as_layer:
                self.plain = path
            path = parent
        self.registers = registers_dir_of(path)
        if self.registers is not None and not self.registers.resolve().is_relative_to(path.resolve()):
            self.registers = None  # 置き場の外を指すフォルダの symlink は箱なしと見る
        self.layer = layer_dir_of(path) if (path / "intent.yaml").is_file() or self.registers is None else layer_dir_of(self.registers)
        if self.layer is None and (path / "intent.yaml").is_file():
            self.layer = path
        self.repo_root = repo_root
        self._files: dict[str, YamlFile] = {}
        if self.plain is not None:
            self.registers = None; self.layer = None
            self._files["plain"] = YamlFile(self.plain, self.plain.parent)
        if self.registers is not None:
            for f in REGISTER_FILES:
                self._files[f] = YamlFile(self.registers / f"{f}.yaml", self.registers)
        if self.layer is not None:
            for f in LAYER_FILES:
                self._files[f] = YamlFile(self.layer / f"{f}.yaml", self.layer)

    def _rel(self, p: Optional[Path]) -> Optional[str]:
        if p is None:
            return None
        try:
            return str(p.relative_to(self.repo_root))
        except ValueError:
            return str(p)

    def head(self) -> dict:
        intent = self._files.get("intent")
        scope_id = display = None
        if intent is not None:
            d = intent.read()["data"]
            if isinstance(d, dict):
                scope_id = d.get("scope_id")
                display = d.get("display_name") or d.get("scope_name")
        form = None
        if self.registers is not None:
            form = "sheets" if self.registers.name == "Sheets" else "registers"
        elif self.plain is not None:
            form = "plain"
        return {
            "index": self.index, "origin": self.origin,
            "scope_id": scope_id, "display_name": display,
            "layer": self._rel(self.layer), "registers": self._rel(self.registers), "form": form,
            "plain": self._rel(self.plain), "opened": self.opened,
            "has_registers": self.registers is not None, "has_layer": self.layer is not None,
            "name": display or (self.layer.name if self.layer else (self.registers.parent.name if self.registers else (self.plain.name if self.plain else "?"))),
        }

    def state(self) -> dict:
        out = self.head()
        files: dict[str, dict] = {}
        for name, yf in self._files.items():
            r = yf.read()
            entry = {"exists": r["exists"], "error": r["error"], "mtime": r["mtime"]}
            if name in REGISTER_FILES:
                entry["rows"], shape = _rows(r["data"], LIST_KEYS[name])
                if shape and not entry["error"]:
                    entry["error"] = shape
                if name == "issues" and isinstance(r["data"], dict):
                    entry["charter"] = r["data"].get("charter")
            elif name == "plain":
                entry["data"] = r["data"]  # スカラーもそのまま
            else:
                entry["data"] = r["data"] if isinstance(r["data"], (dict, list)) else None
            files[name] = entry
        out["files"] = files
        out["generated_at"] = _iso(time.time_ns())
        return out


class Catalog:
    """--path で渡された置き場と、Flow から見つけた箱のある Layer の一覧。"""

    def __init__(self, paths: list[Path], flow_root: Optional[Path], repo_root: Path):
        self.repo_root = repo_root
        self.flow_root = flow_root
        self._lock = threading.Lock()
        self._fixed = [p.resolve() for p in paths]
        self._sources: dict[int, Source] = {}
        self._order: list[int] = []
        self._scanned = 0.0
        self._next = 0
        self._by_path: dict[str, int] = {}
        self._refresh(force=True)

    def _add(self, path: Path, origin: str) -> None:
        key = str(path)
        if key in self._by_path:
            return
        src = Source(self._next, path, self.repo_root, origin)
        if src.registers is None and src.layer is None and src.plain is None:
            return
        same = str(src.registers or src.layer or src.plain)  # Sheets を渡したときと Flow の走査で Layer を拾ったときを1つにする
        if same in self._by_path:
            self._by_path[key] = self._by_path[same]
            return
        self._by_path[same] = self._next
        self._by_path[key] = self._next
        self._sources[self._next] = src
        self._order.append(self._next)
        self._next += 1

    def _refresh(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._scanned < SCAN_TTL:
            return
        with self._lock:
            self._scanned = now
            for p in self._fixed:
                self._add(p, "path")
            if self.flow_root is not None:
                for layer in scan_flow(self.flow_root):
                    if registers_dir_of(layer) is not None:
                        self._add(layer, "flow")

    def list(self) -> dict:
        self._refresh()
        items = [self._sources[i].head() for i in self._order]
        # --path は渡した順、Flow のものは新しい日付が先に来るように（layer パスの降順）
        fixed = sorted((h for h in items if h["origin"] == "path"), key=lambda h: h["index"])
        flow = sorted((h for h in items if h["origin"] != "path"), key=lambda h: str(h["layer"] or ""), reverse=True)
        return {"ok": True, "items": fixed + flow, "flow_root": str(self.flow_root) if self.flow_root else None}

    def state(self, index: Optional[int]) -> dict:
        self._refresh()
        if index is None:
            index = self._order[0] if self._order else None
        if index is None or index not in self._sources:
            return {"ok": False, "error": "見つかりません。一覧から選んでください", "items": self.list()["items"]}
        out = self._sources[index].state()
        out["ok"] = True
        return out


# --- HTTP ------------------------------------------------------------------

def make_handler(catalog: Catalog):
    class Handler(BaseHTTPRequestHandler):
        server_version = "YamlViewer/0.1"

        def log_message(self, *_args):
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; connect-src 'self'; img-src 'self' data:; "
                             "frame-ancestors 'self'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, code: int, obj: dict) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False, allow_nan=False, default=str).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
            return host in ALLOWED_HOSTS

        def do_GET(self):
            try:
                self._get()
            except Exception as exc:  # 想定外でも接続を切らない
                try:
                    self._json(500, {"ok": False, "error": f"サーバの中で失敗しました（{type(exc).__name__}）"})
                except Exception:
                    pass

        def _get(self):
            if not self._host_ok():
                return self._json(403, {"ok": False, "error": "Host が許可されていません"})
            parts = urlsplit(self.path)
            path = parts.path
            if path == "/api/list":
                return self._json(200, catalog.list())
            if path == "/api/state":
                try:
                    qs = parse_qs(parts.query, keep_blank_values=False, max_num_fields=4)
                except ValueError:
                    return self._json(400, {"ok": False, "error": "クエリが多すぎます"})
                raw = (qs.get("i") or [None])[0]
                index: Optional[int] = None
                if raw is not None:
                    if not (raw.isascii() and raw.isdigit()) or len(raw) > 6:
                        return self._json(400, {"ok": False, "error": "番号が読めません"})
                    index = int(raw)
                return self._json(200, catalog.state(index))
            if path in STATIC_FILES:
                name, ctype = STATIC_FILES[path]
                return self._send(200, (STATIC / name).read_bytes(), ctype)
            return self._json(404, {"ok": False, "error": "not found"})

        do_HEAD = do_GET

        def _reject(self):
            self._json(405, {"ok": False, "error": "閲覧専用です"})

        do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _reject

    return Handler


def build_server(paths: list[Path], port: int, root: Path = REPO_ROOT, flow: bool = True) -> ThreadingHTTPServer:
    catalog = Catalog(paths, (root / "Flow") if flow else None, root)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(catalog))
    server.daemon_threads = True
    return server


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="AI-PLC の YAML を読みやすく見る（閲覧専用・127.0.0.1）")
    ap.add_argument("--path", action="append", default=[], help="箱・Layer・registers フォルダ、または YAML ファイル（複数可。箱・Layer でないファイルは一般の YAML として表示）")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"既定 {DEFAULT_PORT}。0 で空いている番号")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--no-flow", action="store_true", help="プロジェクトの Flow を走査しない（--path だけ）")
    ap.add_argument("--root", default=str(REPO_ROOT), help="リポジトリの場所（Flow の親）")
    a = ap.parse_args(argv)
    paths = [Path(p).expanduser() for p in a.path]
    for p in paths:
        if not p.is_dir() and not p.is_file():
            print(f"フォルダもファイルもありません: {p}", file=sys.stderr)
            return 2
    try:
        server = build_server(paths, a.port, Path(a.root).resolve(), flow=not a.no_flow)
    except OSError as exc:
        print(f"起動できません（port {a.port}）: {exc}", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"YamlViewer: {url}  （閲覧専用。止めるときは Ctrl-C）", flush=True)  # パイプ越しでもすぐ届くように
    if not a.no_browser:
        threading.Timer(0.3, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
