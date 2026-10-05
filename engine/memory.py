"""
Jarvis long-term memory.

- Facts about you are saved in jarvis.db (table "memories") and survive restarts.
- Recent chat messages are saved too (table "chat_log"), so he continues where you stopped.
- Small settings such as rough mode are saved (table "settings").
"""

import json
import re
import sqlite3
import threading

DB_PATH = "jarvis.db"

# True  = Jarvis decides by himself which things you say are worth remembering
# False = he only remembers when you say "remember that ..."
AUTO_MEMORY = True

# How many saved facts are given to the AI in every conversation
MAX_FACTS_IN_PROMPT = 40

# Never saved, even if you say them
SENSITIVE = re.compile(
    r"\b(password|passcode|otp|pin|cvv|card number|aadhaar|aadhar|ssn|passport)\b|\d{9,}",
    re.IGNORECASE,
)


# ==========================================
# DATABASE
# ==========================================

def _connect():
    return sqlite3.connect(DB_PATH, timeout=10)


def init():
    try:
        con = _connect()
        con.execute(
            "CREATE TABLE IF NOT EXISTS memories("
            "id INTEGER PRIMARY KEY, fact TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
        con.execute(
            "CREATE TABLE IF NOT EXISTS chat_log("
            "id INTEGER PRIMARY KEY, role TEXT, content TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
        con.execute("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)")
        con.commit()
        con.close()
    except Exception as e:
        print("[memory] could not prepare the database:", e)


init()


# ==========================================
# FACTS
# ==========================================

def add_fact(fact):
    fact = re.sub(r"\s+", " ", str(fact)).strip(" .\n")

    if len(fact) < 4 or len(fact) > 300:
        return False
    if SENSITIVE.search(fact):
        return False

    try:
        con = _connect()
        exists = con.execute(
            "SELECT 1 FROM memories WHERE LOWER(fact) = LOWER(?)", (fact,)
        ).fetchone()

        if not exists:
            con.execute("INSERT INTO memories(fact) VALUES (?)", (fact,))
            con.commit()

        con.close()
        return not exists
    except Exception as e:
        print("[memory] could not save a fact:", e)
        return False


def get_facts(limit=MAX_FACTS_IN_PROMPT):
    try:
        con = _connect()
        rows = con.execute(
            "SELECT fact FROM memories ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        con.close()
        return [r[0] for r in reversed(rows)]
    except Exception:
        return []


def forget_matching(phrase):
    stop = {"the", "that", "about", "and", "for", "you", "your", "my", "me"}
    words = [w for w in re.findall(r"\w+", phrase.lower()) if len(w) >= 3 and w not in stop]

    if not words:
        return 0

    try:
        con = _connect()
        where = " AND ".join(["LOWER(fact) LIKE ?"] * len(words))
        cur = con.execute(f"DELETE FROM memories WHERE {where}", [f"%{w}%" for w in words])
        con.commit()
        count = cur.rowcount
        con.close()
        return count
    except Exception:
        return 0


def clear_all():
    try:
        con = _connect()
        con.execute("DELETE FROM memories")
        con.execute("DELETE FROM chat_log")
        con.commit()
        con.close()
    except Exception as e:
        print("[memory] could not clear memory:", e)


# ==========================================
# SAVED CHAT HISTORY
# ==========================================

def log_message(role, content):
    try:
        con = _connect()
        con.execute("INSERT INTO chat_log(role, content) VALUES (?, ?)", (role, content))
        con.commit()
        con.close()
    except Exception as e:
        print("[memory] could not save chat:", e)


def recent_messages(n=10):
    try:
        con = _connect()
        rows = con.execute(
            "SELECT role, content FROM chat_log ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
        con.close()
        return [{"role": r, "content": c} for r, c in reversed(rows)]
    except Exception:
        return []


# ==========================================
# SETTINGS (rough mode ...)
# ==========================================

def get_setting(key, default=None):
    try:
        con = _connect()
        row = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        con.close()
        return row[0] if row else default
    except Exception:
        return default


def set_setting(key, value):
    try:
        con = _connect()
        con.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (key, value))
        con.commit()
        con.close()
    except Exception as e:
        print("[memory] could not save setting:", e)


# ==========================================
# AUTOMATIC MEMORY (runs in the background, adds no waiting time)
# ==========================================

_EXTRACT_PROMPT = (
    "You extract long-term memory about the USER from one conversation turn. "
    "Return ONLY a JSON array of up to 3 short strings. Each string is a lasting fact worth "
    "remembering about the user: name, age, studies, job, hobbies, family, friends, goals, "
    "preferences, problems they are going through, or upcoming events with dates. "
    "Write each as a short sentence that starts with 'The user'. "
    "Skip small talk, questions, and facts that are not about the user. "
    "Never include passwords, OTPs, card, bank or ID numbers. "
    "If nothing is worth remembering, return []."
)


def parse_facts(text):
    match = re.search(r"\[.*\]", text or "", re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except Exception:
        return []
    return [str(x) for x in data if isinstance(x, str)][:3]


def _extract_and_store(client, model, user_text, reply_text):
    try:
        messages = [
            {"role": "system", "content": _EXTRACT_PROMPT},
            {"role": "user", "content": f"User said: {user_text}\nAssistant replied: {reply_text}"},
        ]

        try:
            response = client.chat.completions.create(
                model=model, messages=messages, max_tokens=300,
                extra_body={"reasoning_effort": "low"},
            )
        except Exception:
            response = client.chat.completions.create(
                model=model, messages=messages, max_tokens=300,
            )

        for fact in parse_facts(response.choices[0].message.content):
            if add_fact(fact):
                print("[memory] saved:", fact)

    except Exception as e:
        print("[memory] auto-memory skipped:", e)


def remember_async(client, model, user_text, reply_text):
    if not AUTO_MEMORY:
        return

    # Only talk about yourself is worth checking (saves API calls)
    words = user_text.split()
    if len(words) < 4 or not re.search(r"\b(i|i'm|im|i've|my|me|mine|we|our)\b", user_text.lower()):
        return

    threading.Thread(
        target=_extract_and_store,
        args=(client, model, user_text, reply_text),
        daemon=True,
    ).start()


# ==========================================
# VOICE COMMANDS
# Returns (spoken_text, shown_text, memory_was_cleared) or None
# ==========================================

def handle_command(query, confirm):
    q = re.sub(r"\b(jarvis|please)\b", " ", query.lower())
    q = re.sub(r"\s+", " ", q).strip(" .")

    # ---- rough mode on / off ----
    if re.search(
        r"\b(?:rough|casual swearing)\s+(?:mode|words?|language|talk|style)\b"
        r"|\b(?:use|allow|say|speak with|talk with)\s+(?:some\s+)?(?:rough|bad|curse)\s+words?\b",
        q,
    ):
        off = re.search(r"\b(off|disable|stop|no|don't|do not|without|quit|never)\b", q)
        if off:
            set_setting("style", "friendly")
            msg = "Okay, rough mode is off. Back to being the polite friend."
        else:
            set_setting("style", "rough")
            msg = "Alright, rough mode is on. Let's talk like proper friends, no filter."
        return msg, msg, False

    # ---- what do you remember ----
    if re.match(
        r"^(?:what do you (?:remember|know)(?: about me)?|what have i told you|tell me what you remember)\b", q
    ):
        facts = get_facts(200)
        if not facts:
            msg = "I don't know much about you yet. Tell me about yourself!"
            return msg, msg, False
        spoken = f"I remember {len(facts)} things. For example: " + ". ".join(facts[-4:])
        shown = " | ".join(facts[-12:])
        return spoken, shown, False

    # ---- forget everything ----
    if re.match(
        r"^(?:forget (?:everything|all|all of it|everything about me)"
        r"|(?:clear|delete|wipe|reset) (?:your |my )?memory)$",
        q,
    ):
        if confirm("Do you really want me to forget everything about you? Say yes to confirm."):
            clear_all()
            msg = "Done. My memory is clean."
            return msg, msg, True
        msg = "Okay, I kept everything."
        return msg, msg, False

    # ---- forget one thing ----
    m = re.match(r"^forget(?: about| that)?\s+(.+)$", q)
    if m:
        count = forget_matching(m.group(1))
        msg = "Okay, I forgot it." if count else "I don't remember anything like that."
        return msg, msg, False

    # ---- call me ... ----
    m = re.match(r"^call me\s+(.+)$", q)
    if m:
        name = m.group(1).strip()
        add_fact(f"The user wants to be called {name}")
        msg = f"Okay, I will call you {name}."
        return msg, msg, False

    # ---- remember that ... ----
    m = re.match(r"^(?:remember|note|save|keep in mind)(?: that| this)?\s+(.+)$", q)
    if m and not q.startswith(("remember folder", "save folder")):
        fact = m.group(1).strip()
        if SENSITIVE.search(fact):
            msg = "I won't save passwords or ID numbers, it's not safe. Everything else I'm happy to remember."
        else:
            add_fact(f"The user told you: {fact}")
            msg = "Got it, I will remember that."
        return msg, msg, False

    return None