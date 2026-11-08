#!/usr/bin/env python3
"""adhd-or-ocd: a safe, undoable file organizer. Pure standard library, Python 3.8+.

  scan    PATH            read-only report with a Chaos Score
  plan    PATH [options]  dry run: writes a plan file, moves nothing
  apply   PLAN            executes a plan and journals every single move
  undo    PATH            reverses the latest (or a chosen) journal
  history PATH            lists journals

Guarantees: nothing is deleted, nothing is overwritten, every move is undoable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

__version__ = "1.0.0"
STATE = ".adhd-or-ocd"

TYPE_EXTS = {
    "Documents": "pdf doc docx txt rtf odt md pages tex",
    "Spreadsheets": "xls xlsx xlsm csv tsv ods numbers",
    "Presentations": "ppt pptx odp key",
    "Images": "jpg jpeg png gif webp heic heif bmp tif tiff svg raw cr2 nef ico",
    "Videos": "mp4 mov avi mkv wmv flv webm m4v",
    "Audio": "mp3 wav flac aac m4a ogg opus wma",
    "Archives": "zip rar 7z tar gz tgz bz2 xz iso",
    "Installers": "exe msi dmg pkg deb rpm apk appimage msix",
    "Code": "py js ts jsx tsx html css json yml yaml xml sh bat ps1 c cpp h java go rs php rb sql ipynb",
    "Design": "psd ai fig sketch xd indd eps",
    "Ebooks": "epub mobi azw3 djvu",
    "Fonts": "ttf otf woff woff2",
    "Data": "db sqlite sqlite3 parquet pkl npy h5 mdb",
}
EXT2TYPE = {e: t for t, s in TYPE_EXTS.items() for e in s.split()}
MEDIA = {"Images", "Videos", "Audio"}
SHORTCUT_EXTS = {"lnk", "url", "ini", "webloc", "desktop"}
MANAGED = {"_Inbox", "_Sorted", "_Review", "00_Inbox", "10_Projects", "20_Areas",
           "30_Resources", "40_Media", "50_Software", "90_Archive", "99_Review"}
NEVER_DESCEND = {"node_modules", ".git", "__pycache__", ".venv", "venv", "$recycle.bin",
                 "system volume information", STATE}
PROJECT_FILES = {".git", "package.json", "pyproject.toml", "requirements.txt", "setup.py",
                 "cargo.toml", "go.mod", "pom.xml", "build.gradle", "makefile", "cmakelists.txt",
                 ".obsidian", "composer.json", "gemfile", "pubspec.yaml", "skill.md"}
PROJECT_SUFFIX = (".sln", ".csproj", ".xcodeproj", ".uproject")
SYSTEM_PREFIXES = ["c:\\windows", "c:\\program files", "c:\\programdata", "/usr", "/etc", "/bin",
                   "/sbin", "/var", "/system", "/library", "/boot", "/proc", "/dev", "/sys",
                   "/applications", "/opt", "/lib"]

# first match wins; edit freely or pass --rules your.json (see examples/rules.example.json)
DEFAULT_RULES = [
    ("20_Areas/Identity-and-Admin", r"\b(passport|aadhaar|aadhar|pan card|driving licen[sc]e|voter id|birth certificate|visa|id card)\b"),
    ("20_Areas/Finance", r"\b(invoice|receipt|bill|statement|payslip|salary|itr|gst|tax|emi|insurance|upi|bank)\b"),
    ("20_Areas/Education", r"\b(assignment|syllabus|lecture|semester|sem \d+|exam|question paper|marksheet|timetable|hall ticket|lab record|unit \d+|module \d+|notes)\b"),
    ("20_Areas/Career", r"\b(resume|cv|cover letter|offer letter|portfolio|internship|certificate|linkedin)\b"),
    ("20_Areas/Travel", r"\b(ticket|boarding pass|itinerary|booking|hotel|flight)\b"),
]

JUNK_RE = re.compile(r"(^~\$)|(\.(tmp|temp|crdownload|part|partial|download|swp)$)|(^(thumbs\.db|\.ds_store)$)", re.I)
SCREENSHOT_RE = re.compile(r"^(screenshot|screen[ _]?shot|screen[ _]?capture|snip|capture)\b", re.I)
DATE_RE = re.compile(r"(?<!\d)((?:19|20)\d\d)[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])(?!\d)")
ISSUES = [
    ("counter (1)", re.compile(r"\s\(\d{1,3}\)$")),
    ("copy marker", re.compile(r"(^copy of )|([ _-]copy( ?\(?\d+\)?)?$)", re.I)),
    ("final-final", re.compile(r"final.*final|final[ _-]?(v\d|\d)", re.I)),
    ("placeholder", re.compile(r"^(untitled|new folder|new document|document ?\d*)\b", re.I)),
    ("odd characters", re.compile(r"[^\w\s.\-()\[\],&'+@#]")),
    ("stray spaces", re.compile(r"\s{2,}|^\s|\s$")),
]


def out(*a):
    print(*a, flush=True)


def human(n):
    n = float(n)
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


def guard(p) -> Path:
    """Refuse to touch system folders, drive roots, or the bare home directory."""
    p = Path(p).expanduser().resolve()
    s = os.path.normcase(str(p)).rstrip("\\/")
    if p == Path(p.anchor) or p == Path.home().resolve():
        sys.exit(f"Refusing {p}: pick a specific folder (Desktop, Downloads, Documents, ...).")
    for q in SYSTEM_PREFIXES:
        q = os.path.normcase(q)
        if s == q or s.startswith(q + os.sep):
            sys.exit(f"Refusing {p}: that is a system location.")
    if "appdata" in s.split(os.sep):
        sys.exit(f"Refusing {p}: AppData belongs to your apps, not to you.")
    return p


def is_hidden(e) -> bool:
    if e.name.startswith("."):
        return True
    if os.name == "nt":
        try:
            return bool(e.stat(follow_symlinks=False).st_file_attributes & 6)  # hidden|system
        except (OSError, AttributeError):
            return False
    return False


def walk(root: Path, max_depth: int):
    """Return (files, dirs, projects). Files directly inside root have depth 1.
    Project folders (git repos, package.json, ...) and managed folders are never entered."""
    files, dirs, projects = [], [], []

    def rec(d, depth):
        nfiles = nsub = 0
        try:
            entries = list(os.scandir(d))
        except OSError:
            return 0, 0
        for e in entries:
            try:
                if e.is_symlink() or is_hidden(e) or e.name.lower() in NEVER_DESCEND:
                    continue
                if e.is_dir(follow_symlinks=False):
                    if depth == 1 and e.name in MANAGED:
                        dirs.append(dict(path=e.path, depth=depth, managed=True, nfiles=0, nsub=0))
                        continue
                    names = [n.lower() for n in os.listdir(e.path)]
                    if any(n in PROJECT_FILES or n.endswith(PROJECT_SUFFIX) for n in names):
                        projects.append(e.path)
                        continue
                    info = dict(path=e.path, depth=depth, managed=False, nfiles=0, nsub=0)
                    dirs.append(info)
                    nsub += 1
                    if depth < max_depth:
                        info["nfiles"], info["nsub"] = rec(e.path, depth + 1)
                elif e.is_file(follow_symlinks=False):
                    st = e.stat(follow_symlinks=False)
                    ext = os.path.splitext(e.name)[1].lstrip(".").lower()
                    files.append(dict(path=e.path, name=e.name, ext=ext, size=st.st_size,
                                      mtime=st.st_mtime, depth=depth, type=EXT2TYPE.get(ext, "Other")))
                    nfiles += 1
            except OSError:
                continue
        return nfiles, nsub

    rec(str(root), 1)
    return files, dirs, projects


def name_issues(name: str):
    stem = os.path.splitext(name)[0]
    return [label for label, rx in ISSUES if rx.search(stem)]


def is_junk(f) -> bool:
    return bool(JUNK_RE.search(f["name"])) or f["size"] == 0


def sha256_file(path, partial=False):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            if partial:
                h.update(fh.read(65536))
            else:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def find_dupes(files):
    """Exact duplicates only: same size, same first 64KB, same full SHA-256."""
    by_size = defaultdict(list)
    for f in files:
        if f["size"] > 0:
            by_size[f["size"]].append(f)
    groups = []
    for fs in by_size.values():
        if len(fs) < 2:
            continue
        by_head = defaultdict(list)
        for f in fs:
            k = sha256_file(f["path"], partial=True)
            if k:
                by_head[k].append(f)
        for cand in by_head.values():
            if len(cand) < 2:
                continue
            by_full = defaultdict(list)
            for f in cand:
                k = sha256_file(f["path"])
                if k:
                    by_full[k].append(f)
            groups.extend(g for g in by_full.values() if len(g) > 1)
    return groups


# ----------------------------------------------------------------------------- Chaos Score

WEIGHTS = dict(pile=.30, dupes=.15, names=.20, maze=.15, stale=.10, junk=.10)


def analyze(root: Path, depth: int = 12):
    files, dirs, projects = walk(root, depth)
    now = time.time()
    loose = [f for f in files if f["depth"] == 1 and f["ext"] not in SHORTCUT_EXTS]
    total = len(files)
    groups = find_dupes([f for f in files if f["size"] < 512 * 1048576]) if total <= 20000 else []
    dup_files = sum(len(g) - 1 for g in groups)
    dup_bytes = sum(x["size"] for g in groups for x in sorted(g, key=lambda y: y["mtime"])[1:])
    bad = sum(1 for f in files if name_issues(f["name"]))
    junk = sum(1 for f in files if is_junk(f))
    stale = sum(1 for f in loose if now - f["mtime"] > 365 * 86400)
    plain = [d for d in dirs if not d["managed"]]
    empty = sum(1 for d in plain if d["nfiles"] == 0 and d["nsub"] == 0)
    single = sum(1 for d in plain if d["nfiles"] == 1 and d["nsub"] == 0)
    deep = sum(1 for d in plain if d["depth"] > 4)
    c = dict(
        pile=min(1.0, len(loose) / 25),
        dupes=min(1.0, dup_files / max(total, 1) * 5),
        names=min(1.0, bad / max(total, 1) * 1.5),
        maze=min(1.0, (empty + single + deep) / len(plain)) if plain else 0.0,
        stale=stale / len(loose) if loose else 0.0,
        junk=min(1.0, junk / 10),
    )
    score = round(100 * sum(WEIGHTS[k] * c[k] for k in WEIGHTS))
    pile_idx = .7 * c["pile"] + .3 * c["stale"]
    maze_idx = .6 * c["maze"] + .4 * c["names"]
    if score < 15:
        verdict = "Already tidy. Show-off."
    elif pile_idx >= maze_idx:
        verdict = "ADHD-style chaos: big piles, very little structure"
    else:
        verdict = "OCD-style chaos: a maze of folders and fiddly file names"
    return dict(root=str(root), files=files, projects=projects, loose=len(loose), total=total,
                folders=len(plain), size=sum(f["size"] for f in files), dup_files=dup_files,
                dup_bytes=dup_bytes, bad_names=bad, junk=junk, stale=stale, empty=empty,
                single=single, deep=deep, score=score, parts=c, verdict=verdict)


def bar(score):
    n = round(score / 10)
    return "[" + "#" * n + "-" * (10 - n) + "]"


def cmd_scan(a):
    root = guard(a.path)
    r = analyze(root)
    if a.json:
        out(json.dumps({k: v for k, v in r.items() if k not in ("files", "parts")}, indent=2))
        return
    types = Counter(f["type"] for f in r["files"])
    out(f"\n== ADHD-or-OCD scan: {root}")
    out(f"Files: {r['total']}   Folders: {r['folders']}   Size: {human(r['size'])}   "
        f"Project folders (left alone): {len(r['projects'])}")
    out(f"Loose in root: {r['loose']}   Duplicates: {r['dup_files']} ({human(r['dup_bytes'])} wasted)   "
        f"Junk: {r['junk']}   Messy names: {r['bad_names']}   Stale loose (>1y): {r['stale']}")
    out(f"Empty folders: {r['empty']}   One-file folders: {r['single']}   Folders deeper than 4: {r['deep']}")
    out(f"\nChaos Score: {r['score']}/100 {bar(r['score'])}  (0 = zen, 100 = gremlin cave)")
    out(f"Verdict: {r['verdict']}")
    out("Top types: " + ", ".join(f"{t} {n}" for t, n in types.most_common(6)))


# ----------------------------------------------------------------------------- Planning

def clean_name(f) -> str:
    """Safe, idempotent normalisation: ISO date prefix, no copy markers, kebab-case, lowercase ext."""
    name = f["name"]
    stem, ext = os.path.splitext(name)
    ext = ext.lower()
    if re.match(r"^\d{4}-\d{2}-\d{2}_\d{6}_screenshot", name):
        return name
    if f["type"] == "Images" and SCREENSHOT_RE.match(name):
        return f"{datetime.fromtimestamp(f['mtime']):%Y-%m-%d_%H%M%S}_screenshot{ext}"
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", stem)
    s = re.sub(r"\s\(\d{1,3}\)$", "", s)
    s = re.sub(r"(?i)^copy of\s+", "", s)
    s = re.sub(r"(?i)[ _-]copy( ?\(?\d+\)?)?$", "", s)
    prefix = ""
    m = DATE_RE.search(s)
    if m:
        prefix = f"{m.group(1)}-{m.group(2)}-{m.group(3)}_"
        s = s[:m.start()] + " " + s[m.end():]
    s = re.sub(r"[\s_]+", "-", s.strip()).lower()
    s = re.sub(r"-{2,}", "-", s).strip("-. ")
    return f"{prefix}{(s or 'untitled')[:100]}{ext}"


def load_rules(path):
    if not path:
        return [(to, re.compile(rx, re.I)) for to, rx in DEFAULT_RULES]
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [(r["to"].strip("/\\"), re.compile(r["match"], re.I)) for r in data]


def norm_stem(name):
    return re.sub(r"\s+", " ", re.sub(r"[_\-.()\[\],]+", " ", os.path.splitext(name)[0].lower())).strip()


def destination(f, mode, o, rules, is_dupe):
    """Return (relative destination folder, reason)."""
    adhd = mode == "adhd"
    review = "_Review" if adhd else "99_Review"
    if is_junk(f):
        return f"{review}/Junk-Candidates", "junk"
    if is_dupe:
        return f"{review}/Duplicates", "exact duplicate"
    t = f["type"]
    stem = norm_stem(f["name"])
    if rules is not None and (not adhd or o.rules):
        for to, rx in rules:
            if rx.search(stem):
                return to, f"rule: {to.split('/')[-1]}"
    shot = t == "Images" and bool(SCREENSHOT_RE.match(f["name"]))
    if adhd:
        return "_Sorted/" + ("Screenshots" if shot else t), "type"
    d = datetime.fromtimestamp(f["mtime"])
    if shot:
        return f"40_Media/Screenshots/{d:%Y-%m}", "screenshot"
    if t in ("Images", "Videos"):
        return f"40_Media/{t}/{d:%Y}", "media"
    if t == "Audio":
        return "40_Media/Audio", "media"
    if t not in MEDIA and (time.time() - f["mtime"]) > o.archive_days * 86400:
        return f"90_Archive/{d:%Y}/{t}", f"older than {o.archive_days}d"
    if t in ("Installers", "Archives"):
        return f"50_Software/{t}", "software"
    return f"30_Resources/{t}", "reference"


def build_plan(src: Path, dest: Path, mode: str, o):
    files, dirs, projects = walk(src, o.depth)
    if dest != src:
        files = [f for f in files if not Path(f["path"]).resolve().is_relative_to(dest)] \
            if hasattr(Path, "is_relative_to") else [f for f in files if not f["path"].startswith(str(dest))]
    now = time.time()
    skipped, cand = Counter(), []
    for f in files:
        if f["ext"] in SHORTCUT_EXTS:
            skipped["shortcuts/.ini files (left where they are)"] += 1
        elif now - f["mtime"] < o.min_age * 60:
            skipped["modified in the last %d min (maybe in use)" % o.min_age] += 1
        else:
            cand.append(f)
    dup_of = {}
    if not o.no_dupes:
        for g in find_dupes([f for f in cand if f["size"] <= o.max_hash_mb * 1048576]):
            g.sort(key=lambda x: (x["mtime"], len(x["path"])))
            for x in g[1:]:
                dup_of[x["path"]] = g[0]["path"]
    rules = load_rules(o.rules)
    rename = (mode == "ocd" and not o.keep_names) or o.rename
    moves = []
    for f in cand:
        folder, reason = destination(f, mode, o, rules, f["path"] in dup_of)
        name = f["name"]
        if reason not in ("junk", "exact duplicate"):
            if rename:
                name = clean_name(f)
            if f["depth"] > 1 and not o.flatten:
                ctx = re.sub(r'[<>:"/\\|?*]', "", os.path.relpath(f["path"], src).split(os.sep)[0]).strip()
                folder = f"{folder}/{ctx}"
        target = dest.joinpath(*folder.split("/")) / name
        if os.path.normcase(str(target)) == os.path.normcase(f["path"]):
            skipped["already in the right place"] += 1
            continue
        m = dict(src=f["path"], dst_dir=folder, name=name, reason=reason, size=f["size"], mtime=f["mtime"])
        if f["path"] in dup_of:
            m["dup_of"] = dup_of[f["path"]]
        moves.append(m)
    return dict(version=__version__, created=datetime.now().isoformat(timespec="seconds"), mode=mode,
                src_root=str(src), dest_root=str(dest), prune_empty=bool(o.prune_empty),
                projects=projects, skipped=dict(skipped), moves=moves)


def cmd_plan(a):
    src = guard(a.path)
    dest = guard(a.dest) if a.dest else src
    plan = build_plan(src, dest, a.mode, a)
    before = analyze(src)
    plan["score_before"] = before["score"]
    state = src / STATE
    state.mkdir(exist_ok=True)
    pth = Path(a.out) if a.out else state / f"plan-{datetime.now():%Y%m%d-%H%M%S}.json"
    pth.write_text(json.dumps(plan, indent=1, ensure_ascii=False), encoding="utf-8")
    groups = defaultdict(list)
    for m in plan["moves"]:
        groups[m["dst_dir"]].append(m)
    out(f"\n== DRY RUN ({a.mode.upper()} mode): {src}  ->  {dest}")
    out(f"Chaos Score now: {before['score']}/100 {bar(before['score'])}  {before['verdict']}")
    out(f"\n{len(plan['moves'])} files would move into {len(groups)} folders:\n")
    for folder in sorted(groups):
        ms = groups[folder]
        sample = ", ".join(m["name"] for m in ms[:3])
        out(f"  {folder:<44} {len(ms):>4} files  {human(sum(m['size'] for m in ms)):>9}   e.g. {sample}")
    renamed = sum(1 for m in plan["moves"] if os.path.basename(m["src"]) != m["name"])
    if renamed:
        out(f"\n{renamed} files get cleaner names (ISO dates, no 'copy'/'(1)', kebab-case).")
    for why, n in plan["skipped"].items():
        out(f"Skipped {n}: {why}")
    if plan["projects"]:
        out(f"Left alone (looks like projects): {len(plan['projects'])} folders")
    out(f"\nNothing was moved. Plan saved: {pth}")
    out(f'To execute:  python "{Path(__file__).resolve()}" apply "{pth}"')


# ----------------------------------------------------------------------------- Apply / Undo

def inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def unique_path(p: Path) -> Path:
    if not p.exists():
        return p
    n = 2
    while True:
        cand = p.with_name(f"{p.stem}-{n}{p.suffix}")
        if not cand.exists():
            return cand
        n += 1


def ensure_dir(d: Path):
    """mkdir -p, returning the directories that did not exist before (shallowest first)."""
    new = []
    cur = d
    while not cur.exists():
        new.append(cur)
        cur = cur.parent
    d.mkdir(parents=True, exist_ok=True)
    return list(reversed(new))


def prune_empty(src: Path, projects, log):
    n = 0
    for dp, dns, _ in os.walk(src, topdown=False):
        p = Path(dp)
        if p == src:
            continue
        rel = p.relative_to(src).parts
        if rel[0] in MANAGED or any(x.startswith(".") or x.lower() in NEVER_DESCEND for x in rel):
            continue
        if any(inside(p, Path(pr)) for pr in projects):
            continue
        try:
            if not os.listdir(dp):
                p.rmdir()
                log({"op": "rmdir", "path": str(p)})
                n += 1
        except OSError:
            pass
    return n


def cmd_apply(a):
    plan = json.loads(Path(a.plan).read_text(encoding="utf-8"))
    src_root, dest_root = guard(plan["src_root"]), guard(plan["dest_root"])
    state = src_root / STATE
    state.mkdir(exist_ok=True)
    jpath = state / f"journal-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    moved = skipped = 0
    with open(jpath, "a", encoding="utf-8") as jf:
        def log(rec):
            jf.write(json.dumps(rec, ensure_ascii=False) + "\n")
            jf.flush()

        for m in plan["moves"]:
            s = Path(m["src"])
            try:
                if not s.is_file() or not inside(s, src_root):
                    skipped += 1
                    continue
                st = s.stat()
                if st.st_size != m["size"] or abs(st.st_mtime - m["mtime"]) > 1:
                    skipped += 1  # changed since the plan was made: do not touch
                    continue
                dst_dir = dest_root.joinpath(*m["dst_dir"].split("/"))
                if not inside(dst_dir, dest_root) or "/" in m["name"] or "\\" in m["name"]:
                    skipped += 1
                    continue
                for d in ensure_dir(dst_dir):
                    log({"op": "mkdir", "path": str(d)})
                final = unique_path(dst_dir / m["name"])
                shutil.move(str(s), str(final))
                log({"op": "move", "src": str(s), "dst": str(final)})
                moved += 1
            except OSError as err:
                skipped += 1
                out(f"  skipped {s.name}: {err}")
        pruned = prune_empty(src_root, plan.get("projects", []), log) if plan.get("prune_empty") else 0
    after = analyze(src_root)
    out(f"\nMoved {moved} files, skipped {skipped}" + (f", removed {pruned} empty folders" if pruned else "") + ".")
    out(f"Chaos Score: {plan.get('score_before', '?')} -> {after['score']}/100 {bar(after['score'])}")
    out(f"Undo anytime:  python \"{Path(__file__).resolve()}\" undo \"{src_root}\"")


def cmd_undo(a):
    root = guard(a.path)
    js = sorted((root / STATE).glob("journal-*.jsonl"))
    j = Path(a.journal) if a.journal else (js[-1] if js else None)
    if not j or not j.exists():
        sys.exit("No journal found. Nothing to undo.")
    recs = [json.loads(x) for x in j.read_text(encoding="utf-8").splitlines() if x.strip()]
    restored = conflicts = 0
    for r in reversed(recs):
        if r["op"] == "move":
            s, d = Path(r["src"]), Path(r["dst"])
            if d.exists() and not s.exists():
                s.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(d), str(s))
                restored += 1
            else:
                conflicts += 1
                out(f"  left alone (changed since): {d}")
        elif r["op"] == "mkdir":
            try:
                Path(r["path"]).rmdir()
            except OSError:
                pass
        elif r["op"] == "rmdir":
            Path(r["path"]).mkdir(parents=True, exist_ok=True)
    j.rename(j.with_suffix(".undone"))
    out(f"Restored {restored} files" + (f", {conflicts} left alone" if conflicts else "") + f". Journal: {j.name}")


def cmd_history(a):
    root = guard(a.path)
    for j in sorted((root / STATE).glob("journal-*")):
        n = sum(1 for x in j.read_text(encoding="utf-8").splitlines() if '"op": "move"' in x)
        out(f"{j.name:<36} {n:>5} moves  {'(undone)' if j.suffix == '.undone' else ''}")


# ----------------------------------------------------------------------------- CLI

def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="organize.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="read-only report + Chaos Score")
    s.add_argument("path")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_scan)
    p = sub.add_parser("plan", help="dry run, writes a plan, moves nothing")
    p.add_argument("path")
    p.add_argument("--mode", choices=["adhd", "ocd"], default="adhd")
    p.add_argument("--dest", help="organize INTO this folder instead of in place")
    p.add_argument("--depth", type=int, default=1, help="1 = only loose files in PATH (default); 3 = dig 3 levels")
    p.add_argument("--rules", help="JSON file: [{\"match\": regex, \"to\": \"20_Areas/Name\"}]")
    p.add_argument("--archive-days", type=int, default=365, help="OCD mode: older files go to 90_Archive")
    p.add_argument("--min-age", type=int, default=30, help="skip files modified in the last N minutes")
    p.add_argument("--max-hash-mb", type=int, default=2048)
    p.add_argument("--no-dupes", action="store_true")
    p.add_argument("--rename", action="store_true", help="clean names in ADHD mode too")
    p.add_argument("--keep-names", action="store_true", help="never rename (OCD mode)")
    p.add_argument("--flatten", action="store_true", help="drop original subfolder names when digging")
    p.add_argument("--prune-empty", action="store_true", help="remove folders left empty (undoable)")
    p.add_argument("--out", help="where to save the plan")
    p.set_defaults(fn=cmd_plan)
    ap_ = sub.add_parser("apply", help="execute a plan")
    ap_.add_argument("plan")
    ap_.set_defaults(fn=cmd_apply)
    u = sub.add_parser("undo", help="reverse the latest journal")
    u.add_argument("path")
    u.add_argument("--journal")
    u.set_defaults(fn=cmd_undo)
    h = sub.add_parser("history", help="list journals")
    h.add_argument("path")
    h.set_defaults(fn=cmd_history)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
