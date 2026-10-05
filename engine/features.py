
import datetime
import os
import queue
import re
import sqlite3
import struct
import subprocess
import threading
import time
import urllib.parse
import webbrowser

from pathlib import Path

from playsound import playsound
import eel
import pyaudio
import pyautogui
import pvporcupine

from dotenv import load_dotenv
from huggingface_hub import InferenceClient

from engine.command import speak, current_language, speech
from engine.config import ASSISTANT_NAME, DEVELOPER_NAME, DEVELOPER_INFO
from engine.helper import extract_yt_term, remove_words
from engine import memory


# ==========================================
# HUGGING FACE API CONFIGURATION
# ==========================================

load_dotenv()

HF_TOKEN = os.getenv("HF_TOKEN")

if not HF_TOKEN:
    print("Warning: Hugging Face token not found in .env")

client = InferenceClient(
    api_key=HF_TOKEN
)


# ==========================================
# DATABASE CONNECTION
# ==========================================

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "jarvis.db"

con = sqlite3.connect(
    str(DB_PATH),
    check_same_thread=False
)

cursor = con.cursor()


# ==========================================
# PLAY ASSISTANT SOUND
# ==========================================

@eel.expose
def playAssistantSound():

    music_dir = str(
        BASE_DIR / "www" / "asserts" / "audio"
        / "www_assets_audio_start_sound.mp3"
    )

    try:
        playsound(music_dir)

    except Exception as e:
        print("Assistant sound error:", e)


# ==========================================
# OPEN APPLICATION OR WEBSITE
# ==========================================

def openCommand(query):

    query = query.replace(ASSISTANT_NAME, "")
    query = query.replace("open", "")
    query = query.lower().strip()

    app_name = query

    if app_name == "":
        speak("Not found")
        return

    try:

        cursor.execute(
            "SELECT path FROM sys_command WHERE LOWER(name) = ?",
            (app_name,)
        )

        results = cursor.fetchall()

        if results:
            speak("Opening " + app_name)
            os.startfile(results[0][0])
            return

        cursor.execute(
            "SELECT url FROM web_command WHERE LOWER(name) = ?",
            (app_name,)
        )

        results = cursor.fetchall()

        if results:
            speak("Opening " + app_name)
            webbrowser.open(results[0][0])
            return

        speak("Opening " + app_name)
        os.system("start " + app_name)

    except Exception as e:
        print("Error:", e)
        speak("Something went wrong")


# ==========================================
# PLAY YOUTUBE
# ==========================================

def PlayYoutube(query):

    search_term = extract_yt_term(query)

    if not search_term:

        search_term = query

        for word in ["play", "song", "music"]:

            search_term = re.sub(
                rf"\b{word}\b",
                "",
                search_term,
                flags=re.IGNORECASE
            )

        search_term = search_term.strip()

    if search_term:

        print("YouTube search term:", search_term)

        try:

            speak(f"Searching YouTube for {search_term}")

            search_url = (
                "https://www.youtube.com/results?search_query="
                + urllib.parse.quote_plus(search_term)
            )

            webbrowser.open(search_url)

        except Exception as e:
            print("YouTube error:", e)
            speak("Unable to open YouTube.")

    else:
        speak("Please tell me what song to play.")


# ==========================================
# HOTWORD DETECTION
# ==========================================

def hotword(stop_event=None):

    porcupine = None
    paud = None
    audio_stream = None

    try:

        porcupine = pvporcupine.create(
            keywords=["jarvis", "alexa"]
        )

        paud = pyaudio.PyAudio()

        audio_stream = paud.open(
            rate=porcupine.sample_rate,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=porcupine.frame_length
        )

        while not (
            stop_event is not None
            and stop_event.is_set()
        ):

            keyword = audio_stream.read(
                porcupine.frame_length,
                exception_on_overflow=False
            )

            keyword = struct.unpack_from(
                "h" * porcupine.frame_length,
                keyword
            )

            keyword_index = porcupine.process(keyword)

            if keyword_index >= 0:

                print("JARVIS DETECTED!")

                pyautogui.hotkey("ctrl", "shift", "j")

                print("Ctrl + Shift + J sent")

                time.sleep(2)

    except Exception as e:
        print("Hotword error:", e)

    finally:

        if audio_stream is not None:
            audio_stream.close()

        if paud is not None:
            paud.terminate()

        if porcupine is not None:
            porcupine.delete()


# ==========================================
# FIND CONTACT
# ==========================================

def findContact(query):

    words_to_remove = [
        ASSISTANT_NAME,
        "make",
        "a",
        "to",
        "phone",
        "call",
        "send",
        "message",
        "whatsapp",
        "wahtsapp",
        "video"
    ]

    query = remove_words(query, words_to_remove)

    try:

        query = query.strip().lower()

        cursor.execute(
            "SELECT mobile_no FROM contacts "
            "WHERE LOWER(name) LIKE ? OR LOWER(name) LIKE ?",
            ('%' + query + '%', query + '%')
        )

        results = cursor.fetchall()

        if not results:
            raise ValueError("Contact not found")

        mobile_number_str = str(results[0][0])

        if not mobile_number_str.startswith("+977"):
            mobile_number_str = "+977" + mobile_number_str

        return mobile_number_str, query

    except Exception as e:

        print("Contact error:", e)

        speak("Contact does not exist")

        return 0, 0


# ==========================================
# WHATSAPP
# ==========================================

def whatsApp(mobile_no, message, flag, name):

    if flag == "message":

        target_tab = 12

        jarvis_message = (
            "Message sent successfully to " + name
        )

    elif flag == "call":

        target_tab = 7
        message = ""

        jarvis_message = "Calling " + name

    else:

        target_tab = 6
        message = ""

        jarvis_message = (
            "Starting video call with " + name
        )

    encoded_message = urllib.parse.quote(message)

    print(encoded_message)

    whatsapp_url = (
        f"whatsapp://send?phone={mobile_no}"
        f"&text={encoded_message}"
    )

    full_command = f'start "" "{whatsapp_url}"'

    subprocess.run(full_command, shell=True)

    time.sleep(5)

    subprocess.run(full_command, shell=True)

    pyautogui.hotkey("ctrl", "f")

    for i in range(1, target_tab):
        pyautogui.hotkey("tab")

    pyautogui.hotkey("enter")

    speak(jarvis_message)


# ==========================================
# CHATBOT CONFIGURATION
# ==========================================

developer_mode = {
    "on": False
}

MAX_HISTORY = 20

chat_history = memory.recent_messages(MAX_HISTORY)

chat_state = {
    "interrupted": False
}

LLM_MODEL = "openai/gpt-oss-120b"

SENTENCE_END = re.compile(
    r"(?<=[.!?।॥。！？؟])\s+"
)


# ==========================================
# STREAMING WORKER
# ==========================================

def _stream_worker(messages, q, state):

    def emit(text):

        text = text.strip()

        if text:
            q.put(text)
            state["sent"] += 1

    try:

        try:

            stream = client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                max_tokens=500,
                stream=True,
                extra_body={
                    "reasoning_effort": "low"
                }
            )

        except Exception:

            stream = client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                max_tokens=500,
                stream=True
            )

        buf = ""

        for chunk in stream:

            if state["cancel"]:
                break

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta.content or ""

            if not delta:
                continue

            buf += delta

            parts = SENTENCE_END.split(buf)

            for p in parts[:-1]:
                emit(p)

            buf = parts[-1]

            limit = 70 if state["sent"] == 0 else 160

            if len(buf) > limit:

                cut = max(
                    buf.rfind(", "),
                    buf.rfind("; ")
                )

                if cut > 30:

                    emit(buf[:cut + 1])

                    buf = buf[cut + 2:]

        if not state["cancel"]:
            emit(buf)

    except Exception as e:

        state["error"] = e

    finally:

        q.put(None)


# ==========================================
# SYSTEM PROMPT
# ==========================================

def build_system_prompt():

    lang = current_language["name"].title()

    facts = memory.get_facts()

    saved_facts = "\n".join(
        f"- {fact}" for fact in facts
    )

    if not saved_facts:
        saved_facts = "No saved facts yet."

    style = memory.get_setting(
        "style",
        "friendly"
    )

    prompt = (

        f"You are Jarvis, the user's AI best friend "
        f"and voice assistant, created by {DEVELOPER_NAME}. "

        f"{DEVELOPER_INFO} "

        "Personality: warm, caring, respectful, playful "
        "and natural. "

        "You are allowed to use casual words like bro, "
        "dude, and buddy. "

        "Always answer what the user actually asked. "

        "This is a spoken conversation. "

        "Normally reply in 1 to 3 natural sentences. "

        "Avoid unnecessary lists and markdown during "
        "voice conversations. "

        "If the user asks a technical question, explain "
        "it clearly using beginner-friendly language "
        "and simple examples. "

        "Remember relevant information from the saved "
        "user facts. "

        "Use personal information naturally when it helps "
        "answer the question. "

        "Never pretend to remember something that is "
        "not in your memory. "

        "If information is missing, ask the user instead "
        "of guessing. "

        "If the user changes topic or interrupts you, "
        "follow the new topic. "

        "Never claim to be human or invent human experiences. "

        "If the user shares a personal problem, respond "
        "with empathy. "

        "If the user is in serious distress, respond "
        "with care and encourage them to seek support "
        "from someone they trust. "

        f"Reply in {lang}, unless the user clearly uses "
        "another language. "

        "Here are the user's saved memories:\n"
        f"{saved_facts}"
    )

    if style == "rough":

        prompt += (

            " The user has enabled casual rough mode. "

            "Speak like a close friend. "

            "You may occasionally use mild swear words "
            "naturally, such as damn, hell, or crap. "

            "Do not overuse profanity. "

            "Never insult, humiliate, threaten, or demean "
            "the user. "

            "Keep the conversation warm, supportive, "
            "and playful."
        )

    else:

        prompt += (
            " Use friendly, polite, natural language. "
            "Avoid profanity."
        )

    if developer_mode["on"]:

        prompt += (

            f" You are talking with your developer, "
            f"{DEVELOPER_NAME}. "

            "Address him respectfully as boss when natural. "

            "Be warm and supportive."
        )

    if chat_state["interrupted"]:

        prompt += (

            " Your previous reply was interrupted because "
            "the user started speaking. "

            "Respond directly to the new message and do not "
            "repeat the unfinished answer."
        )

    return prompt


# ==========================================
# CHATBOT
# ==========================================

def chatBot(query, show_user=True):

    t0 = time.time()

    try:

        print("User question:", query)

        if show_user:
            eel.senderText(query)

        messages = [
            {
                "role": "system",
                "content": build_system_prompt()
            }
        ]

        messages += chat_history

        messages.append({
            "role": "user",
            "content": query
        })

        if show_user:
            chat_state["interrupted"] = False

        q = queue.Queue()

        state = {
            "cancel": False,
            "error": None,
            "sent": 0
        }

        threading.Thread(
            target=_stream_worker,
            args=(messages, q, state),
            daemon=True
        ).start()

        full = ""

        finished = False
        first_logged = False

        while not finished:

            try:
                item = q.get(timeout=0.1)

            except queue.Empty:
                eel.sleep(0.03)
                continue

            if item is None:
                break

            if not first_logged:

                print(
                    f"[timing] first words ready after "
                    f"{time.time() - t0:.1f}s"
                )

                first_logged = True

            batch = [item]

            while not q.empty():

                nxt = q.get_nowait()

                if nxt is None:
                    finished = True
                    break

                batch.append(nxt)

            text = " ".join(batch).strip()

            if not text:
                continue

            full = (full + " " + text).strip()

            eel.DisplayMessage(full)

            speak(text)

            if speech["stop"]:

                state["cancel"] = True

                break

        if not full:

            raise RuntimeError(
                state["error"] or "Empty answer"
            )

        print("Jarvis Answer:", full)

        if show_user:

            chat_state["interrupted"] = bool(
                speech["stop"]
            )

            memory.log_message("user", query)

            memory.log_message("assistant", full)

            chat_history.append({
                "role": "user",
                "content": query
            })

            chat_history.append({
                "role": "assistant",
                "content": full
            })

            del chat_history[:-MAX_HISTORY]

            memory.remember_async(
                client,
                LLM_MODEL,
                query,
                full
            )

        eel.receiverText(full)

        return full

    except Exception as e:

        print("Hugging Face Error:", e)

        error_message = (
            "Sorry, I am unable to answer right now. "
            "Please check my AI connection."
        )

        eel.DisplayMessage(error_message)

        speak(error_message)

        return error_message


# ==========================================
# DEVELOPER MODE
# ==========================================

def isDeveloperIntro(query):

    q = query.lower()

    name = DEVELOPER_NAME.lower()

    return (

        "i am your developer" in q

        or "i'm your developer" in q

        or "i am your creator" in q

        or "i'm your creator" in q

        or (
            name in q
            and (
                "i am" in q
                or "i'm" in q
                or "this is" in q
            )
        )
    )


def greetDeveloper():

    developer_mode["on"] = True

    hour = datetime.datetime.now().hour

    part = (
        "morning" if hour < 12
        else "afternoon" if hour < 17
        else "evening"
    )

    chatBot(
        f"It is {part}. Your developer {DEVELOPER_NAME} just arrived. "
        "Greet him warmly, say you are proud he built you, "
        "and ask how you can help.",
        show_user=False
    )