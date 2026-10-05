import os
import re
import shutil
import sqlite3
from pathlib import Path

import eel

from engine.command import speak, takecommand


HOME = Path.home()
DB_PATH = "jarvis.db"

# Remembers the last file/folder you worked on, so "move it to documents" works
context = {"last": None}


# ==========================================
# FOLDER NAMES (defaults + the "folders" table in jarvis.db)
# ==========================================

def _known(name):
    """Finds Desktop/Documents/... even when OneDrive moved them."""
    for base in (HOME / "OneDrive", HOME):
        p = base / name
        if p.exists():
            return p
    return HOME / name


def load_folders():
    folders = {
        "home":      HOME,
        "desktop":   _known("Desktop"),
        "documents": _known("Documents"),
        "downloads": _known("Downloads"),
        "pictures":  _known("Pictures"),
        "photos":    _known("Pictures"),
        "music":     _known("Music"),
        "videos":    _known("Videos"),
    }

    try:
        con = sqlite3.connect(DB_PATH)
        rows = con.execute("SELECT name, path FROM folders").fetchall()
        con.close()

        for name, path in rows:
            if name and path and Path(path).exists():
                folders[name.strip().lower()] = Path(path)
    except Exception:
        pass     # table not created yet: defaults are enough

    return folders


def save_folder(name, path):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "CREATE TABLE IF NOT EXISTS folders("
        "id INTEGER PRIMARY KEY, name VARCHAR(100) UNIQUE, path VARCHAR(1000))"
    )
    con.execute("INSERT OR REPLACE INTO folders(name, path) VALUES (?, ?)", (name, str(path)))
    con.commit()
    con.close()


# ==========================================
# HELPERS
# ==========================================

def say(message):
    try:
        eel.DisplayMessage(message)
        eel.receiverText(message)
    except Exception:
        pass
    speak(message)


def ask(question):
    say(question)
    return clean(takecommand())


def ask_yes(question):
    answer = ask(question)
    return bool(re.search(r"\b(yes|yeah|yep|sure|okay|ok|confirm|do it|go ahead|haan)\b", answer))


FILLERS = ["jarvis", "please", "can you", "could you", "would you", "for me", "hey"]


def clean(q):
    q = (q or "").lower()
    for f in FILLERS:
        q = re.sub(rf"\b{re.escape(f)}\b", " ", q)
    q = re.sub(r"\s+dot\s+", ".", q)          # "notes dot txt" -> "notes.txt"
    return re.sub(r"\s+", " ", q).strip(" .")


def clean_name(name):
    name = re.sub(r"^(?:the|a|an)\s+", "", name.strip())
    name = re.sub(r"^(?:file|folder|directory)\s+", "", name)
    return re.sub(r'[<>:"/\\|?*]', "", name).strip()


def is_safe(path):
    """Only work inside your home folder or folders saved in the database."""
    p = Path(path).resolve()

    blocked = [
        os.environ.get("WINDIR", "C:\\Windows"),
        os.environ.get("ProgramFiles", "C:\\Program Files"),
        os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"),
    ]
    if any(b and str(p).lower().startswith(b.lower()) for b in blocked):
        return False

    roots = [HOME] + list(load_folders().values())
    return any(p == r.resolve() or r.resolve() in p.parents for r in roots)


def unique_path(p):
    """Never overwrite: report.pdf -> report (1).pdf"""
    p = Path(p)
    if not p.exists():
        return p
    i = 1
    while True:
        candidate = p.with_name(f"{p.stem} ({i}){p.suffix}")
        if not candidate.exists():
            return candidate
        i += 1


def _child_dir(base, name):
    try:
        dirs = [d for d in os.listdir(base) if (Path(base) / d).is_dir()]
    except Exception:
        return None
    low = name.lower()
    for d in dirs:
        if d.lower() == low:
            return Path(base) / d
    for d in dirs:
        if low in d.lower():
            return Path(base) / d
    return None


def find_folder_anywhere(name, max_depth=3, max_scan=6000):
    low = name.lower()
    scanned = 0
    roots = {str(p): p for p in load_folders().values()}

    for root in roots.values():
        root_depth = len(Path(root).parts)
        for current, dirs, _ in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            scanned += 1
            if scanned > max_scan:
                return None
            if len(Path(current).parts) - root_depth >= max_depth:
                dirs[:] = []
            for d in dirs:
                if d.lower() == low:
                    return Path(current) / d
    return None


def resolve_folder(text):
    """'documents', 'projects in documents', 'd drive', 'my study folder' ..."""
    if not text:
        return None

    text = re.sub(r"^(?:the|my|a)\s+", "", text.strip(" ."))
    text = re.sub(r"\s+(?:folder|directory)$", "", text)

    folders = load_folders()

    if text in folders:
        return folders[text]

    drive = re.match(r"^([a-z])\s*drive$", text)
    if drive and Path(f"{drive.group(1).upper()}:\\").exists():
        return Path(f"{drive.group(1).upper()}:\\")

    nested = re.match(r"^(.+?)\s+(?:in|inside|of|under)\s+(.+)$", text)
    if nested:
        base = resolve_folder(nested.group(2))
        if base:
            return _child_dir(base, nested.group(1))

    for name, path in folders.items():
        if name.startswith(text) and len(text) >= 3:
            return path

    return find_folder_anywhere(text)


def _match_in_dir(folder, name):
    try:
        entries = os.listdir(folder)
    except Exception:
        return None

    low = name.lower()

    for e in entries:
        if e.lower() == low:
            return Path(folder) / e
    for e in entries:
        if Path(e).stem.lower() == low:
            return Path(folder) / e
    for e in entries:
        if e.lower().startswith(low):
            return Path(folder) / e
    if len(low) >= 3:
        for e in entries:
            if low in e.lower():
                return Path(folder) / e
    return None


def find_item(name, folder=None):
    name = clean_name(name)

    if name in ("it", "that", "this", "that file", "this file", "that folder", "this folder"):
        last = context["last"]
        return Path(last) if last and Path(last).exists() else None

    if folder:
        return _match_in_dir(folder, name)

    search = []
    if context["last"]:
        search.append(Path(context["last"]).parent)
    search += list(load_folders().values())

    seen = set()
    for d in search:
        if str(d) in seen:
            continue
        seen.add(str(d))
        hit = _match_in_dir(d, name)
        if hit:
            return hit
    return None


def split_where(text):
    """'notes.txt in documents' -> ('notes.txt', 'documents')"""
    m = re.match(r"^(?:(.*)\s+)?(?:in|inside|into|on|at|under|within)\s+(?:the\s+)?(.+)$", text)
    if m:
        return (m.group(1) or "").strip(), m.group(2).strip()
    return text.strip(), None


# ==========================================
# COMMAND DETECTION
# ==========================================

CREATE_RE = (
    r"^(?:create|make|new)\s+(?:a\s+|an\s+|new\s+)*"
    r"(file|folder|directory)\b\s*(?:named\s+|called\s+|name\s+)?(.*)$"
)


def isFileCommand(query):
    q = clean(query)
    has_ext = re.search(r"\b[\w-]+\.[a-z0-9]{2,5}\b", q)

    if re.match(CREATE_RE, q):
        return True
    if re.match(r"^(?:add|save|remember)\s+folder\s+.+\s+(?:as|at|path)\s+.+", q):
        return True
    if re.search(r"\b(?:which|what)\b.*\bfolders\b.*\b(?:know|saved|have)\b", q):
        return True
    if re.match(r"^open\s+(?:the\s+)?(?:file|folder|directory)\b", q):
        return True
    if re.match(r"^(?:list|show)\b.*\b(?:files|folders|items)\b", q) or re.match(r"^what (?:files|folders)\b", q):
        return True
    if re.match(r"^(?:find|search for|locate)\s+(?:the\s+)?(?:file|folder)\b", q):
        return True
    if re.match(r"^(?:move|copy|rename|delete|remove|transfer|shift)\b", q):
        if re.search(r"\b(?:file|folder|directory)\b", q) or has_ext:
            return True
        if context["last"] and re.search(r"\b(?:it|that|this)\b", q):
            return True

    # "move report from downloads to documents" (no word "file", no extension):
    # only treat it as a file command if the destination folder really exists
    mv = re.match(r"^(?:move|copy|transfer|shift)\s+(?:the\s+)?(.+)\s+(?:to|into)\s+(.+)$", q)
    if mv and resolve_folder(mv.group(2)) is not None:
        return True

    # "rename todo list to shopping": only if that item exists
    rn = re.match(r"^rename\s+(?:the\s+)?(.+?)\s+(?:to|as)\s+(.+?)(?:\s+in\s+.+)?$", q)
    if rn and find_item(rn.group(1)) is not None:
        return True

    # "delete old notes": only if that item exists (and Jarvis always asks to confirm)
    dl = re.match(r"^(?:delete|remove)\s+(?:the\s+)?(.+)$", q)
    if dl and find_item(re.sub(r"\s+(?:from|in)\s+.+$", "", dl.group(1))) is not None:
        return True

    return False


# ==========================================
# ACTIONS
# ==========================================

def do_create(q):
    m = re.match(CREATE_RE, q)
    kind = "folder" if m.group(1) in ("folder", "directory") else "file"

    name, where = split_where(m.group(2).strip())
    name = clean_name(name)

    if not name:
        name = clean_name(ask(f"What should I name the {kind}?"))
    if not name:
        return say("I didn't catch a name, so I cancelled.")

    if not where:
        where = ask("In which folder should I create it?")
    if not where:
        return say("I didn't catch the folder, so I cancelled.")

    folder = resolve_folder(where)

    if folder is None:
        if not ask_yes(f"I couldn't find a folder called {where}. Should I create it in Documents?"):
            return say("Okay, I cancelled.")
        folder = load_folders()["documents"] / clean_name(where)
        folder.mkdir(parents=True, exist_ok=True)

    if kind == "file" and "." not in name:
        name += ".txt"

    target = unique_path(Path(folder) / name)

    if not is_safe(target):
        return say("Sorry, I'm not allowed to create things there.")

    if kind == "folder":
        target.mkdir(parents=True)
    else:
        target.touch()

    context["last"] = str(target)
    say(f"Done. I created the {kind} {target.name} in {Path(folder).name}.")


def do_move_copy(q, verb):
    m = re.match(
        r"^(?:move|copy|transfer|shift)\s+(?:the\s+)?(?:file\s+|folder\s+)?(.+)\s+(?:to|into)\s+(.+)$", q
    )
    if not m:
        return say(f"Please say it like: {verb} report.pdf from downloads to documents.")

    src_text, dest_text = m.group(1).strip(), m.group(2).strip()

    src_folder = None
    frm = re.match(r"^(.*?)\s+from\s+(.+)$", src_text)
    if frm:
        src_text = frm.group(1)
        src_folder = resolve_folder(frm.group(2))
        if src_folder is None:
            return say(f"I couldn't find the folder {frm.group(2)}.")

    src = find_item(src_text, src_folder)
    if src is None:
        return say(f"I couldn't find {clean_name(src_text)}.")

    dest = resolve_folder(dest_text)
    if dest is None:
        if not ask_yes(f"I couldn't find a folder called {dest_text}. Should I create it in Documents?"):
            return say("Okay, I cancelled.")
        dest = load_folders()["documents"] / clean_name(dest_text)
        dest.mkdir(parents=True, exist_ok=True)

    dest = Path(dest)

    if not (is_safe(src) and is_safe(dest)):
        return say("Sorry, I'm not allowed to touch that location.")

    if src.resolve() == dest.resolve() or src.resolve() in dest.resolve().parents:
        return say("I can't put a folder inside itself.")

    target = unique_path(dest / src.name)

    if verb == "move":
        shutil.move(str(src), str(target))
        past = "moved"
    else:
        if src.is_dir():
            shutil.copytree(src, target)
        else:
            shutil.copy2(src, target)
        past = "copied"

    context["last"] = str(target)
    say(f"Done. I {past} {src.name} to {dest.name}.")


def do_rename(q):
    rest = re.sub(r"^rename\s+(?:the\s+)?(?:file\s+|folder\s+)?", "", q)

    folder = None
    in_match = re.match(r"^(.*)\s+in\s+(.+)$", rest)
    if in_match:
        rest = in_match.group(1)
        folder = resolve_folder(in_match.group(2))

    m = re.match(r"^(.+?)\s+(?:to|as)\s+(.+)$", rest)
    if not m:
        return say("Please say it like: rename old.txt to new.txt in documents.")

    src = find_item(m.group(1), folder)
    if src is None:
        return say(f"I couldn't find {clean_name(m.group(1))}.")

    new_name = clean_name(m.group(2))
    if src.is_file() and "." not in new_name:
        new_name += src.suffix

    if not is_safe(src):
        return say("Sorry, I'm not allowed to touch that location.")

    target = unique_path(src.with_name(new_name))
    src.rename(target)

    context["last"] = str(target)
    say(f"Done. {src.name} is now {target.name}.")


def do_delete(q):
    rest = re.sub(r"^(?:delete|remove|trash)\s+(?:the\s+)?(?:file\s+|folder\s+)?", "", q)

    folder = None
    frm = re.match(r"^(.*?)\s+(?:from|in)\s+(.+)$", rest)
    if frm:
        rest = frm.group(1)
        folder = resolve_folder(frm.group(2))

    src = find_item(rest, folder)
    if src is None:
        return say(f"I couldn't find {clean_name(rest)}.")

    if not is_safe(src):
        return say("Sorry, I'm not allowed to delete that.")

    if not ask_yes(f"Are you sure you want to delete {src.name}? Say yes to confirm."):
        return say("Okay, I did not delete anything.")

    try:
        from send2trash import send2trash
    except ImportError:
        return say("For safe deleting, please install send2trash first.")

    send2trash(str(src))
    context["last"] = None
    say(f"Done. {src.name} is in the recycle bin, so you can restore it.")


def do_open(q):
    m = re.match(r"^open\s+(?:the\s+)?(file|folder|directory)\s+(.+)$", q)
    kind, rest = m.group(1), m.group(2)

    if kind in ("folder", "directory"):
        folder = resolve_folder(rest)
        if folder is None:
            return say(f"I couldn't find the folder {rest}.")
        os.startfile(str(folder))
        context["last"] = str(folder)
        return say(f"Opening {Path(folder).name}.")

    name, where = split_where(rest)
    folder = resolve_folder(where) if where else None
    item = find_item(name, folder)
    if item is None:
        return say(f"I couldn't find {clean_name(name)}.")
    os.startfile(str(item))
    context["last"] = str(item)
    say(f"Opening {item.name}.")


def do_list(q):
    m = re.search(r"\b(?:in|inside|of)\s+(?:the\s+)?(.+)$", q)
    where = m.group(1) if m else ask("Which folder?")
    folder = resolve_folder(where)

    if folder is None:
        return say(f"I couldn't find the folder {where}.")

    items = sorted(os.listdir(folder), key=str.lower)
    items = [i for i in items if not i.startswith(".")]

    if not items:
        return say(f"The folder {Path(folder).name} is empty.")

    eel.DisplayMessage(", ".join(items[:15]) + (" ..." if len(items) > 15 else ""))
    speak(f"There are {len(items)} items in {Path(folder).name}. For example: " + ", ".join(items[:5]))


def do_find(q):
    m = re.match(r"^(?:find|search for|locate)\s+(?:the\s+)?(?:file\s+|folder\s+)?(.+)$", q)
    name, where = split_where(m.group(1))
    name = clean_name(name).lower()

    roots = [resolve_folder(where)] if where else list(load_folders().values())
    roots = [r for r in roots if r]

    results, scanned, seen = [], 0, set()

    for root in roots:
        if str(root) in seen:
            continue
        seen.add(str(root))
        for current, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            scanned += 1
            if scanned > 6000 or len(results) >= 5:
                break
            for entry in dirs + files:
                if name in entry.lower():
                    results.append(Path(current) / entry)

    if not results:
        return say(f"I couldn't find anything named {name}.")

    context["last"] = str(results[0])
    eel.DisplayMessage(" | ".join(str(r) for r in results[:3]))
    speak(f"I found {results[0].name} in {results[0].parent.name}. Say move it, or open it, if you want.")


def do_add_alias(q):
    m = re.match(r"^(?:add|save|remember)\s+folder\s+(.+?)\s+(?:as|at|path)\s+(.+)$", q)
    name, path = clean_name(m.group(1)), m.group(2).strip().strip('"')

    if not Path(path).exists():
        return say("That path does not exist, so I did not save it.")

    save_folder(name.lower(), path)
    say(f"Okay, I will remember {name} as that folder.")


def do_list_aliases():
    names = sorted(load_folders().keys())
    say("I know these folders: " + ", ".join(names))


# ==========================================
# MAIN ENTRY (called from command.py)
# ==========================================

def handleFileCommand(query):
    q = clean(query)

    try:
        if re.match(r"^(?:add|save|remember)\s+folder\s+", q):
            do_add_alias(q)
        elif re.search(r"\b(?:which|what)\b.*\bfolders\b.*\b(?:know|saved|have)\b", q):
            do_list_aliases()
        elif re.match(CREATE_RE, q):
            do_create(q)
        elif re.match(r"^(?:move|transfer|shift)\b", q):
            do_move_copy(q, "move")
        elif q.startswith("copy"):
            do_move_copy(q, "copy")
        elif q.startswith("rename"):
            do_rename(q)
        elif re.match(r"^(?:delete|remove)\b", q):
            do_delete(q)
        elif q.startswith("open"):
            do_open(q)
        elif re.match(r"^(?:find|search for|locate)\b", q):
            do_find(q)
        else:
            do_list(q)

    except PermissionError:
        say("Sorry, Windows did not give me permission for that.")
    except Exception as e:
        print("File command error:", type(e).__name__, e)
        say("Sorry, I couldn't do that file operation.")

    return True