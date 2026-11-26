#!/usr/bin/env python3
"""AI-PLC Registry DB の場所を決める共通の関数。

探す順番（最初に見つかったもの）:
  1. 環境変数 AIPLC_DB（テスト・OSS 用。明示なので DB_NOT_MAIN で止めない）
  2. <root>/.ai-plc/config.yaml の id_allocation.db_path（相対パスは本体の作業ツリーから）
  3. id_allocation.mode が local-db / git-ref のとき: git-common-dir から本体の作業ツリーを求め、
     <本体>/<db のフォルダ>/ai_plc.db（サブモジュールは /.git/modules/ の手前を本体とみなす）
  4. 今までどおり <root>/<db のフォルダ>/ai_plc.db（設定が無いとき・mode: solo。既定）
<db のフォルダ> はこのファイルのあるフォルダ（Claude Code は .claude/db、Cursor は .cursor/db）。

書き込みの前に check_write() を呼ぶ。決まった DB が linked worktree の中の写しなら DB_NOT_MAIN で止める。
本番の書き込み口は main_db_for() で本体の DB を決め、書く前に check_main_write() を呼ぶ（AIPLC_DB は見ない）。
読むだけのときは warn_read() で警告だけ出す。open_ro() は読み取り専用で開く（sqlite3 error 14 のときは query_only の普通の接続で開き直す）。
make_query_only() は接続を読むだけにする（plc_query の sql の読み取りにも使う）。
`python3 .claude/db/aiplc_paths.py` で、決まった場所と理由を表示する（Cursor は .cursor/db/）。
"""
import json
import os
import sqlite3
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import NamedTuple

ENV = "AIPLC_DB"
_HERE = Path(__file__).resolve().parent
REL_DB = Path(_HERE.parent.name) / _HERE.name / "ai_plc.db"  # .claude/db/ai_plc.db・.cursor/db/ai_plc.db
CONFIG_REL = Path(".ai-plc") / "config.yaml"
MODES = ("solo", "local-db", "git-ref")
ROOT = _HERE.parents[1]


class DbNotMain(RuntimeError):
    code = "DB_NOT_MAIN"


class Resolution(NamedTuple):
    path: Path
    source: str  # env | config | git-common-dir | script
    mode: str


def _warn(msg):
    print(f"[WARN] {msg}", file=sys.stderr)


def _git_dirs(start):
    """(git-dir, git-common-dir) の絶対パス。git の外なら None"""
    cwd = Path(start)
    while not cwd.is_dir() and cwd != cwd.parent:
        cwd = cwd.parent
    for args in (["--path-format=absolute"], []):  # --path-format は git 2.31 から
        try:
            p = subprocess.run(["git", "-C", str(cwd), "rev-parse", *args, "--git-dir",
                                "--git-common-dir"], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return None
        lines = p.stdout.strip().splitlines()[-2:]
        if p.returncode != 0 or len(lines) != 2:
            return None
        if all(os.path.isabs(x) for x in lines) or not args:
            return tuple(Path(os.path.join(str(cwd), x)).resolve() for x in lines)
    return None


def main_root(start=ROOT):
    """本体（main worktree）の作業ツリー。git の外・bare なら None"""
    dirs = _git_dirs(start)
    if dirs is None:
        return None
    common = dirs[1].as_posix()
    if "/.git/modules/" in common:  # サブモジュールとその worktree
        return Path(common.split("/.git/modules/")[0])
    return dirs[1].parent if dirs[1].name == ".git" else None


def is_worktree_copy(db_path):
    """db_path が linked worktree（git-dir と common-dir が違う）の中にあれば True"""
    dirs = _git_dirs(Path(os.path.abspath(db_path)).parent)
    return dirs is not None and dirs[0] != dirs[1]


def load_config(root=ROOT):
    """<root>/.ai-plc/config.yaml の id_allocation（無い・読めないときは {}）"""
    path = Path(root) / CONFIG_REL
    if not path.is_file():
        return {}
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # PyYAML が無い・形が壊れている
        _warn(f"{path} を読めないので設定なしとして扱います: {exc}")
        return {}
    alloc = data.get("id_allocation") if isinstance(data, dict) else None
    if alloc is not None and not isinstance(alloc, dict):
        _warn(f"{path}: id_allocation は mapping にしてください（無視します）")
        return {}
    alloc = dict(alloc or {})
    if alloc.get("mode", "solo") not in MODES:
        _warn(f"{path}: id_allocation.mode={alloc.get('mode')!r} は {MODES} のどれか（solo とみなします）")
        alloc["mode"] = "solo"
    return alloc


def resolve_db(root=ROOT, env=None):
    env = os.environ if env is None else env
    if env.get(ENV):
        return Resolution(Path(os.path.abspath(os.path.expanduser(env[ENV]))), "env", "env")
    git_main = main_root(root)  # サブモジュールなど、設定が無い所から呼ばれたら本体の設定を読む
    cfg = load_config(root if (Path(root) / CONFIG_REL).is_file() or git_main is None else git_main)
    mode = cfg.get("mode") or "solo"
    main = git_main if mode != "solo" else None
    if cfg.get("db_path"):
        p = Path(os.path.expanduser(str(cfg["db_path"])))
        return Resolution(p if p.is_absolute() else (main or Path(root)) / p, "config", mode)
    if main is not None and (main / REL_DB).is_file():
        return Resolution(main / REL_DB, "git-common-dir", mode)
    return Resolution(Path(root) / REL_DB, "script", mode)


def db_path(root=ROOT):
    return str(resolve_db(root).path)


def main_db(root=ROOT):
    """本番の書き込み口（init_db など）が基準にする本体の DB。
    AIPLC_DB は見ない（試験の一時 DB を「本番」と取り違えないため。
    試験は今までどおり --db や patch で一時 DB を渡す）。フォルダは実パスにする"""
    p = Path(os.path.abspath(resolve_db(root, env={}).path))
    return p.parent.resolve() / p.name


def main_db_for(caller_file):
    """本番の書き込み口（init_db など）が既定にする本体の DB。caller_file の作業ツリー（db のフォルダの
    2 つ上）から main_db() で決める（AIPLC_DB は見ない）"""
    return main_db(Path(caller_file).resolve().parents[2])


def repo_root(root=ROOT):
    """DB を持つ作業ツリー"""
    p = resolve_db(root).path
    return p.parents[2] if p.parent.as_posix().endswith(REL_DB.parent.as_posix()) else Path(root)


def _explicit(path, env):
    value = env.get(ENV)
    return bool(value) and os.path.abspath(os.path.expanduser(value)) == os.path.abspath(path)


def check_write(path, env=None):
    """書き込む前に呼ぶ。worktree の写しなら DbNotMain（AIPLC_DB で明示したときは通す）"""
    env = os.environ if env is None else env
    if _explicit(path, env) or not is_worktree_copy(path):
        return
    main = main_root(Path(os.path.abspath(path)).parent)
    raise DbNotMain(
        f"DB_NOT_MAIN: {path} は worktree の中の写しです。書き込みを止めました。"
        f" 本体: {main / REL_DB if main else '(不明)'}。"
        f" 本体に DB があれば、.ai-plc/config.yaml の id_allocation.mode: local-db で本体の DB を使います。"
        f" この DB に書くなら {ENV}=<path> で明示してください")


def same_db(a, b):
    """a と b が同じ DB ファイルを指すか（init_db.is_production_db_path と同じ考え方）。
    realpath でそろえて（相対パス・symlink・/tmp と /private/tmp・..）比べ、両方あるときは samefile
    （ハードリンク）も見る。比べられないときは同じとみなす（確かめる側に倒す）"""
    try:
        ra = os.path.realpath(os.path.abspath(os.fspath(a)))
        rb = os.path.realpath(os.path.abspath(os.fspath(b)))
        if ra == rb or os.path.normcase(ra).casefold() == os.path.normcase(rb).casefold():
            return True
        if os.path.exists(ra) and os.path.exists(rb):
            return os.path.samefile(ra, rb)
        return False
    except (OSError, ValueError, TypeError):
        return True


def check_main_write(path):
    """本番の書き込み口が既定の本体の DB に書く前に呼ぶ。check_write と同じく、
    worktree の中の写しなら DbNotMain。書き込み口は AIPLC_DB を見ない（試験の一時 DB を本番と取り違えないため）ので、AIPLC_DB で同じパスを
    明示していても通さない。symlink や相対パスで渡されても、realpath でそろえた実体の場所で確かめる"""
    check_write(os.path.realpath(os.path.abspath(os.fspath(path))), env={})


def warn_read(path, env=None):
    env = os.environ if env is None else env
    if not _explicit(path, env) and is_worktree_copy(path):
        _warn(f"DB_NOT_MAIN: {path} は worktree の写しです（読むだけなので続けます。中身は古いかもしれません）")


# 値を付けると DB ファイルや接続の設定を変える PRAGMA（query_only でも止まらないものがある。
# 例: PRAGMA journal_mode=delete は query_only=ON でも通る）
_WRITE_PRAGMAS_WITH_VALUE = {"journal_mode", "user_version", "application_id", "schema_version",
                             "writable_schema", "auto_vacuum", "page_size", "query_only",
                             "locking_mode", "max_page_count"}
_WRITE_PRAGMAS_ALWAYS = {"wal_checkpoint", "incremental_vacuum", "optimize"}


def _deny_writes(action, arg1, arg2, _db, _source):
    """set_authorizer 用。query_only で止まらない書き込み（ATTACH・設定を変える PRAGMA）を断る"""
    if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH):
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_PRAGMA:
        name = (arg1 or "").lower()
        if name in _WRITE_PRAGMAS_ALWAYS or (arg2 is not None and name in _WRITE_PRAGMAS_WITH_VALUE):
            return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def make_query_only(conn):
    """接続を読むだけにする。INSERT・UPDATE・DELETE などは PRAGMA query_only=ON で SQLite が断り
    （attempt to write a readonly database）、ATTACH や設定を変える PRAGMA は authorizer で断る"""
    conn.execute("PRAGMA query_only=ON")
    conn.set_authorizer(_deny_writes)
    return conn


def is_write_refusal(exc):
    """make_query_only した接続で、書き込みとして断られた例外なら True"""
    text = str(exc)
    return isinstance(exc, sqlite3.DatabaseError) and (
        "readonly database" in text or "not authorized" in text)


def _check_open(conn):
    conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchall()
    return conn


def open_ro(path):
    """読み取り専用で開く。

    1. まず mode=ro で開く（今までどおり。無いファイルはここで失敗する）。make_query_only() も付ける。
    2. WAL の DB で -shm が無いと、古い SQLite（macOS 標準の 3.43 など）は mode=ro では -shm を
       作れず error 14（unable to open）になる。そのときは普通の（読み書きできる）接続を開いて
       make_query_only() で読むだけにする。ロックと WAL を使うので、別の書き手がまだ checkpoint
       していない内容も読める。この接続が最後の接続だと、閉じるときに SQLite が WAL を DB ファイルへ
       書き戻す（中身は変わらないがファイルの hash が変わる）。Python 3.12 以上では
       SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE でこれを止める。3.9 など setconfig の無い
       Python では止められないので、DB を比べるときはファイルの hash ではなく中身で比べる。
    3. それでも開けない（DB のあるフォルダに書けない等）ときだけ、最後の手段として immutable=1 で
       開く。immutable はロックと WAL を無視するので、-wal が残っている（未 checkpoint の内容が
       あるかもしれない）ときは使わず、2 の error をそのまま上げる。
    """
    quoted = urllib.parse.quote(os.path.abspath(path))
    conn = sqlite3.connect("file:%s?mode=ro" % quoted, uri=True)
    try:
        make_query_only(_check_open(conn))  # ATTACH などもここで断る
    except sqlite3.DatabaseError as exc:  # 壊れた DB などは、今までどおり後の読み取りで失敗させる
        if "unable to open" in str(exc) and os.path.isfile(path):
            conn.close()
            conn = _open_query_only(path, quoted)
    conn.row_factory = sqlite3.Row
    return conn


def no_checkpoint_on_close(conn):
    """閉じるときに WAL を DB ファイルへ書き戻さない（Python 3.12 以上・SQLite 3.16 以上）。できたら True"""
    flag = getattr(sqlite3, "SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE", None)
    if flag is None or not hasattr(conn, "setconfig"):
        return False
    try:
        conn.setconfig(flag, True)
    except sqlite3.Error:
        return False
    return True


def _open_query_only(path, quoted):
    conn = sqlite3.connect("file:%s?mode=rw" % quoted, uri=True)  # rw は無いファイルを作らない
    no_checkpoint_on_close(conn)  # 読むだけの接続が DB ファイルを書き換えない
    try:
        return _check_open(make_query_only(conn))
    except sqlite3.OperationalError:
        conn.close()
        wal = f"{path}-wal"
        if os.path.exists(wal) and os.path.getsize(wal) > 0:
            raise  # 未 checkpoint の内容を見落とすので immutable にはしない
    _warn(f"{path} を普通の接続で開けないので immutable=1 で読みます（ロックを使いません）")
    return _check_open(make_query_only(sqlite3.connect("file:%s?mode=ro&immutable=1" % quoted, uri=True)))


if __name__ == "__main__":
    r = resolve_db()
    print(json.dumps({"db": str(r.path), "source": r.source, "mode": r.mode,
                      "worktree_copy": is_worktree_copy(r.path),
                      "main_root": str(main_root() or "")}, ensure_ascii=False))
