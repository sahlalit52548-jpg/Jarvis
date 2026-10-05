
import array
import collections
from fileinput import filename
import math
import os
import re
import sys
import threading
import uuid

import eel
import gtts
import speech_recognition as sr


import edge_tts
import asyncio

from engine import memory

# ==========================================
# WINDOWS UTF-8 SUPPORT
# ==========================================

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ==========================================
# OPTIONAL LANGUAGE DETECTION
# ==========================================

try:
    from langdetect import detect_langs, DetectorFactory
    DetectorFactory.seed = 0
except Exception:
    detect_langs = None


# ==========================================
# SETTINGS
# ==========================================

CONTINUOUS_CONVERSATION = True
LISTEN_IN_SELECTED_LANGUAGE = True
VOICE_INTERRUPT = True

INTERRUPT_MIN_LEVEL = 1000
DEBUG_INTERRUPT = False

ENGLISH_VOICE_HINT = ""


# ==========================================
# LANGUAGES
# ==========================================

LANGUAGES = {
    "english": {"code": "en", "recog": "en-IN"},
    "hindi": {"code": "hi", "recog": "hi-IN"},
    "kannada": {"code": "kn", "recog": "kn-IN"},
    "tamil": {"code": "ta", "recog": "ta-IN"},
    "telugu": {"code": "te", "recog": "te-IN"},
    "malayalam": {"code": "ml", "recog": "ml-IN"},
    "marathi": {"code": "mr", "recog": "mr-IN"},
    "bengali": {"code": "bn", "recog": "bn-IN"},
    "gujarati": {"code": "gu", "recog": "gu-IN"},
    "punjabi": {"code": "pa", "recog": "pa-Guru-IN"},
    "urdu": {"code": "ur", "recog": "ur-IN"},
    "nepali": {"code": "ne", "recog": "ne-NP"},
    "sinhala": {"code": "si", "recog": "si-LK"},
    "spanish": {"code": "es", "recog": "es-ES"},
    "french": {"code": "fr", "recog": "fr-FR"},
    "german": {"code": "de", "recog": "de-DE"},
    "italian": {"code": "it", "recog": "it-IT"},
    "portuguese": {"code": "pt", "recog": "pt-BR"},
    "russian": {"code": "ru", "recog": "ru-RU"},
    "japanese": {"code": "ja", "recog": "ja-JP"},
    "korean": {"code": "ko", "recog": "ko-KR"},
    "chinese": {"code": "zh-CN", "recog": "zh"},
    "arabic": {"code": "ar", "recog": "ar-SA"},
    "turkish": {"code": "tr", "recog": "tr-TR"},
    "dutch": {"code": "nl", "recog": "nl-NL"},
    "thai": {"code": "th", "recog": "th-TH"},
    "vietnamese": {"code": "vi", "recog": "vi-VN"},
    "indonesian": {"code": "id", "recog": "id-ID"},
    "greek": {"code": "el", "recog": "el-GR"},
    "polish": {"code": "pl", "recog": "pl-PL"},
    "swahili": {"code": "sw", "recog": "sw-KE"},
}

ENGLISH_ALIASES = [
    "english",
    "इंग्लिश",
    "अंग्रेजी",
    "ಇಂಗ್ಲಿಷ್",
    "ஆங்கிலம்",
    "ఇంగ్లీష్"
]

current_language = {"name": "english"}

speech = {
    "stop": False,
    "busy": False
}

session = {"id": 0}

recognizer = sr.Recognizer()
calibration = {"done": False}

file_module_warning = {"shown": False}

_sapi = {
    "voice": None,
    "failed": False
}


# ==========================================
# VOICE INTERRUPTION
# ==========================================

def _rms(data):
    samples = array.array("h", data)

    if not samples:
        return 0.0

    return math.sqrt(
        sum(s * s for s in samples) / len(samples)
    )


class _Detector:

    def __init__(self, calib_frames=14, ratio=1.8, need=4):
        self.calib_frames = calib_frames
        self.ratio = ratio
        self.need = need

        self.levels = []
        self.baseline = None
        self.threshold = INTERRUPT_MIN_LEVEL
        self.loud = 0

    def feed(self, level):

        if self.baseline is None:

            self.levels.append(level)

            if len(self.levels) >= self.calib_frames:

                ordered = sorted(self.levels)

                self.baseline = ordered[
                    max(0, int(len(ordered) * 0.9) - 1)
                ]

                self.threshold = max(
                    self.baseline * self.ratio,
                    INTERRUPT_MIN_LEVEL
                )

            return False

        if level > self.threshold:
            self.loud += 1
        else:
            self.loud = max(0, self.loud - 1)

        return self.loud >= self.need


class BargeIn:

    RATE = 16000
    CHUNK = 1024

    def __init__(self):

        self.triggered = threading.Event()
        self.done = threading.Event()

        self.audio = None

        self._stop = threading.Event()
        self._thread = None

    def reset(self):

        self.triggered.clear()
        self.done.clear()

        self.audio = None

        self._stop.clear()

    def start(self):

        if not VOICE_INTERRUPT:
            return

        if self._thread is not None and self._thread.is_alive():
            return

        self.reset()

        self._thread = threading.Thread(
            target=self._run,
            daemon=True
        )

        self._thread.start()

    def stop(self):

        self._stop.set()

        t = self._thread

        if (
            t is not None
            and t.is_alive()
            and not self.triggered.is_set()
        ):
            t.join(timeout=0.6)

    def take(self):

        if not self.triggered.is_set():
            return False, None

        while not self.done.is_set():
            eel.sleep(0.05)

        audio = self.audio

        self.reset()

        return True, audio

    def _run(self):

        pa = None
        stream = None

        try:

            import pyaudio

            pa = pyaudio.PyAudio()

            stream = pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.RATE,
                input=True,
                frames_per_buffer=self.CHUNK
            )

            detector = _Detector()
            preroll = collections.deque(maxlen=4)

            while not self._stop.is_set():

                data = stream.read(
                    self.CHUNK,
                    exception_on_overflow=False
                )

                level = _rms(data)

                if DEBUG_INTERRUPT:
                    print(
                        f"[mic] level={level:6.0f} "
                        f"limit={detector.threshold:6.0f}"
                    )

                if detector.feed(level):

                    print("[interrupt] you started talking")

                    self.triggered.set()

                    self._record_utterance(
                        stream,
                        preroll,
                        data,
                        detector.threshold
                    )

                    return

                preroll.append(data)

        except Exception as e:
            print("[interrupt] microphone monitor error:", e)

        finally:

            try:

                if stream is not None:
                    stream.stop_stream()
                    stream.close()

                if pa is not None:
                    pa.terminate()

            except Exception:
                pass

            self.done.set()

    def _record_utterance(
        self,
        stream,
        preroll,
        first,
        trigger_level
    ):

        frames = list(preroll) + [first]

        end_level = max(trigger_level * 0.5, 300)

        speech_frames = 4
        silent = 0
        abandoned = False

        for _ in range(950):

            data = stream.read(
                self.CHUNK,
                exception_on_overflow=False
            )

            frames.append(data)

            if _rms(data) > end_level:
                speech_frames += 1
                silent = 0
            else:
                silent += 1

            if speech_frames >= 6 and silent >= 20:
                break

            if speech_frames < 6 and silent >= 45:
                abandoned = True
                break

        if not abandoned:

            self.audio = sr.AudioData(
                b"".join(frames),
                self.RATE,
                2
            )


barge = BargeIn()


# ==========================================
# STOP SPEAKING
# ==========================================

@eel.expose
def stopSpeaking():

    speech["stop"] = True

    voice = _sapi.get("voice")

    if voice is not None:

        try:
            voice.Speak("", 3)
        except Exception:
            pass

    try:

        import pygame

        if pygame.mixer.get_init():
            pygame.mixer.music.stop()

    except Exception:
        pass


def _notify_speaking(flag):

    try:
        eel.SetSpeaking(flag)
    except Exception:
        pass


# ==========================================
# CLEAN SHUTDOWN
# ==========================================

def shutdown_jarvis(route=None, websockets=None):

    print("Jarvis window closed, shutting down...")

    session["id"] += 1

    barge._stop.set()

    stopSpeaking()

    try:
        import pygame
        pygame.quit()
    except Exception:
        pass

    os._exit(0)


# ==========================================
# SPEECH
# ==========================================

def clean_for_speech(text):

    text = re.sub(r"[*#`_>]+", "", text)

    return re.sub(r"\s+", " ", text).strip()


def pick_language(text):

    current = current_language["name"]

    code, prob = None, 0.0

    if detect_langs is not None:

        try:
            best = detect_langs(text)[0]
            code, prob = best.lang, best.prob
        except Exception:
            pass

    if current != "english":

        if code == "en" and prob > 0.9:
            return "english"

        return current

    non_ascii = (
        sum(1 for c in text if ord(c) > 127)
        / max(len(text), 1)
    )

    if code and (
        non_ascii > 0.4
        or (len(text) > 40 and prob > 0.95 and code != "en")
    ):

        for name, info in LANGUAGES.items():

            if info["code"].lower() == code.lower():
                return name

    return "english"


def _get_sapi_voice():

    if _sapi["failed"]:
        return None

    if _sapi["voice"] is None:

        try:

            import comtypes.client

            voice = comtypes.client.CreateObject("SAPI.SpVoice")

            if ENGLISH_VOICE_HINT:

                try:

                    for token in voice.GetVoices():

                        if (
                            ENGLISH_VOICE_HINT.lower()
                            in token.GetDescription().lower()
                        ):
                            voice.Voice = token
                            break

                except Exception:
                    pass

            voice.Rate = 1
            voice.Volume = 100

            _sapi["voice"] = voice

        except Exception as e:

            print(
                "[TTS] Windows voice not available, "
                "using pyttsx3 instead:",
                e
            )

            _sapi["failed"] = True
            return None

    return _sapi["voice"]



# ==========================================
# ENGLISH SPEECH FALLBACK
# ==========================================

def _speak_english_fallback(text):

    try:
        import pyttsx3

        engine = pyttsx3.init("sapi5")

        voices = engine.getProperty("voices")

        if voices:
            engine.setProperty("voice", voices[0].id)

        engine.setProperty("rate", 185)

        engine.say(text)
        engine.runAndWait()

    except Exception as e:
        print("[TTS] pyttsx3 error:", e)


# ==========================================
# ENGLISH SPEECH
# ==========================================

def speak_english(text):

    voice = _get_sapi_voice()

    if voice is None:
        _speak_english_fallback(text)
        return

    try:

        speech["busy"] = True

        voice.Speak(text, 1)

        while True:

            if voice.WaitUntilDone(20):
                break

            if speech["stop"] or barge.triggered.is_set():

                stopSpeaking()
                break

            eel.sleep(0.01)

    except Exception as e:

        print("[TTS] English voice error:", e)

        _speak_english_fallback(text)

    finally:

        speech["busy"] = False


# ==========================================
# MULTILINGUAL SPEECH
# ==========================================

def speak_other(text, lang_code):

    filename = f"voice_{uuid.uuid4().hex}.mp3"

    try:
        import pygame

        # Generate audio at normal speed
        asyncio.run(
            _generate_edge_audio(
                text,
                lang_code,
                filename,
            )
        )

        if speech["stop"] or barge.triggered.is_set():
            return

        _play_audio(filename)

    except Exception as e:
        print("[TTS] Other-language TTS error:", e)

        if lang_code == "en":
            _speak_english_fallback(text)

    finally:
        try:
            if os.path.exists(filename):
                os.remove(filename)
        except Exception as e:
            print("[TTS] Cleanup error:", e)


# ==========================================
# EDGE TTS VOICE SYSTEM
# ==========================================

_edge_voice_cache = {}


async def _get_edge_voice(lang_code):

    if lang_code in _edge_voice_cache:
        return _edge_voice_cache[lang_code]

    voices = await edge_tts.list_voices()

    # Preferred English voices
    if lang_code == "en":

        preferred = [
            "en-US-AriaNeural",
            "en-US-JennyNeural",
            "en-GB-SoniaNeural"
        ]

        for preferred_voice in preferred:

            for item in voices:

                if item["ShortName"] == preferred_voice:

                    _edge_voice_cache[lang_code] = preferred_voice

                    return preferred_voice

    # Exact locale match
    for item in voices:

        if item.get("Locale", "").lower() == lang_code.lower():

            voice = item["ShortName"]

            _edge_voice_cache[lang_code] = voice

            return voice

    # Match language variants
    for item in voices:

        locale = item.get("Locale", "").lower()

        if locale.startswith(lang_code.lower() + "-"):

            voice = item["ShortName"]

            _edge_voice_cache[lang_code] = voice

            return voice

    return None


async def _generate_edge_audio(text, lang_code, filename):

    voice = await _get_edge_voice(lang_code)

    if voice is None:
        raise RuntimeError(
            f"No Edge TTS voice found for {lang_code}"
        )

    communicate = edge_tts.Communicate(
        text=text,
        voice=voice
    )

    await communicate.save(filename)


# ==========================================
# ENGLISH FALLBACK
# ==========================================

def _speak_english_fallback(text):

    try:

        import pyttsx3

        engine = pyttsx3.init("sapi5")

        engine.setProperty("rate", 180)

        engine.say(text)

        engine.runAndWait()

    except Exception as e:

        print("[TTS] Windows fallback error:", e)


# ==========================================
# AUDIO PLAYBACK
# ==========================================

def _play_audio(filename):

    import pygame

    if not pygame.mixer.get_init():

        pygame.mixer.init(
            frequency=24000,
            size=-16,
            channels=2,
            buffer=512
        )

    pygame.mixer.music.load(os.path.abspath(filename))

    pygame.mixer.music.play()

    while pygame.mixer.music.get_busy():

        if speech["stop"] or barge.triggered.is_set():

            pygame.mixer.music.stop()

            break

        eel.sleep(0.02)

    try:
        pygame.mixer.music.unload()
    except Exception:
        pass


# ==========================================
# MAIN EDGE SPEECH
# ==========================================

def speak_edge(text, lang_code):

    filename = f"voice_{uuid.uuid4().hex}.mp3"

    try:

        if speech["stop"] or barge.triggered.is_set():
            return

        asyncio.run(
            _generate_edge_audio(
                text,
                lang_code,
                filename
            )
        )

        if speech["stop"] or barge.triggered.is_set():
            return

        _play_audio(filename)

    except Exception as e:

        print("[TTS] Edge TTS error:", e)

        if lang_code == "en":
            _speak_english_fallback(text)

    finally:

        try:

            if os.path.exists(filename):
                os.remove(filename)

        except Exception as e:

            print("[TTS] Cleanup error:", e)


# ==========================================
# ENGLISH SPEECH
# ==========================================

def speak_english(text):

    speak_edge(text, "en")


# ==========================================
# MULTILINGUAL SPEECH
# ==========================================

def speak_other(text, lang_code):

    speak_edge(text, lang_code)


# ==========================================
# MAIN SPEAK FUNCTION
# ==========================================

def speak(text):

    text = clean_for_speech(str(text))

    if not text:
        return

    if speech["stop"]:

        print("[TTS] Skipped because speech was stopped")
        return

    lang = pick_language(text)

    print(
        f"[TTS] Speaking ({lang}): {text[:70]}"
    )

    _notify_speaking(True)

    barge.start()

    try:

        if lang == "english":

            speak_english(text)

        else:

            lang_code = LANGUAGES[lang]["code"]

            speak_other(text, lang_code)

    except Exception as e:

        print("[TTS] Speech error:", e)

    finally:

        speech["busy"] = False

        _notify_speaking(False)

# ==========================================
# CHANGE LANGUAGE
# ==========================================

def changeLanguage(query):

    triggers = [
        "speak in",
        "talk in",
        "language to",
        "switch to",
        "change language",
        "reply in",
        "answer in",
        "listen in"
    ]

    chosen = None

    if any(t in query for t in triggers):

        for name in LANGUAGES:

            if name in query:
                chosen = name
                break

    elif (
        current_language["name"] != "english"
        and len(query.split()) <= 4
    ):

        if any(alias in query for alias in ENGLISH_ALIASES):
            chosen = "english"

    if not chosen:
        return False

    current_language["name"] = chosen

    from engine.features import chatBot

    chatBot(
        f"Tell the user in one short sentence that from now on "
        f"you will talk in {chosen.title()}.",
        show_user=False
    )

    return True


# ==========================================
# LISTEN
# ==========================================

def takecommand():

    r = recognizer

    if LISTEN_IN_SELECTED_LANGUAGE:
        recog_lang = LANGUAGES[current_language["name"]]["recog"]
    else:
        recog_lang = "en-IN"

    try:

        interrupted, audio = barge.take()

        if interrupted:

            eel.DisplayQuestion("")
            eel.DisplayMessage("Listening...")

            if audio is None:
                return ""

        else:

            with sr.Microphone() as source:

                print("Listening...")

                eel.DisplayQuestion("")
                eel.DisplayMessage("Listening...")

                r.pause_threshold = 1.3
                r.non_speaking_duration = 0.5
                r.dynamic_energy_threshold = True   

                if not calibration["done"]:

                    r.adjust_for_ambient_noise(
                        source,
                        duration=0.6
                    )

                    calibration["done"] = True

                audio = r.listen(
                    source,
                    timeout=10,
                    phrase_time_limit=60
                )

        print("Recognizing...")

        eel.DisplayMessage("Recognizing...")

        query = r.recognize_google(
            audio,
            language=recog_lang
        )

        print("User said:", query)

        eel.DisplayQuestion(query)
        eel.DisplayMessage("Thinking...")

        return query.lower()

    except sr.WaitTimeoutError:

        print("Listening timeout")
        return ""

    except sr.UnknownValueError:

        print("Could not understand audio")
        return ""

    except sr.RequestError as e:

        print("Speech recognition service error:", e)
        return ""

    except Exception as e:

        print("Microphone error:", type(e).__name__, e)
        return ""


# ==========================================
# STARTUP GREETING
# ==========================================

@eel.expose
def startupGreeting():

    speech["stop"] = False

    _get_sapi_voice()

    try:
        from engine.config import DEVELOPER_NAME as _name
    except Exception:
        _name = ""

    greeting = (
        f"Hello {_name}, I am Jarvis. "
        "How are you feeling today?"
    )

    try:

        eel.DisplayMessage(greeting)
        speak(greeting)

    except Exception as e:
        print("Greeting error:", e)

    allCommands()


# ==========================================
# MEMORY CLEAR CONFIRMATION
# ==========================================

def confirm_memory_clear(prompt):

    speak(prompt)

    answer = takecommand()

    return answer.lower().strip() in [
        "yes",
        "yes jarvis",
        "yes confirm",
        "confirm"
    ]


# ==========================================
# HANDLE ONE COMMAND
# ==========================================

def handle_query(query):

    try:

        # Change language
        if changeLanguage(query):
            return True

        # Developer mode off
        if "stop developer mode" in query:

            from engine.features import developer_mode

            developer_mode["on"] = False

            speak("Okay, developer mode is off.")

            return True

        # Developer greeting
        from engine.features import isDeveloperIntro

        if isDeveloperIntro(query):

            from engine.features import greetDeveloper

            greetDeveloper()

            return True

        # File commands
        try:

            from engine.files import (
                isFileCommand,
                handleFileCommand
            )

        except ImportError as e:

            if not file_module_warning["shown"]:

                print(
                    "[files] File commands are off, "
                    "engine/files.py could not be loaded:",
                    e
                )

                file_module_warning["shown"] = True

            isFileCommand = None
            handleFileCommand = None

        if (
            isFileCommand is not None
            and isFileCommand(query)
        ):

            handleFileCommand(query)

            return True

        # YouTube
        if (
            "on youtube" in query
            or query.startswith("play ")
            or query.startswith("song ")
        ):

            from engine.features import PlayYoutube

            PlayYoutube(query)

            return False

        # Open applications
        if "open" in query:

            from engine.features import openCommand

            openCommand(query)

            return False

        if query in ["notepad", "calculator", "word", "excel"]:

            from engine.features import openCommand

            openCommand("open " + query)

            return False

        # WhatsApp
        if (
            "send message" in query
            or "phone call" in query
            or "video call" in query
        ):

            from engine.features import findContact, whatsApp

            contact_no, name = findContact(query)

            if contact_no != 0:

                if "send message" in query:

                    action = "message"

                    speak("What message should I send?")

                    message_text = takecommand()

                elif "phone call" in query:

                    action = "call"
                    message_text = query

                else:

                    action = "video call"
                    message_text = query

                whatsApp(
                    contact_no,
                    message_text,
                    action,
                    name
                )

            return False

        # ==========================================
        # PERSONAL MEMORY COMMANDS
        # ==========================================

        memory_result = memory.handle_command(
            query,
            confirm_memory_clear
        )

        if memory_result:

            spoken_text, shown_text, memory_cleared = memory_result

            if memory_cleared:

                from engine.features import chat_history

                chat_history.clear()

            eel.DisplayMessage(shown_text)

            speak(spoken_text)

            eel.receiverText(shown_text)

            return True

        # ==========================================
        # GENERAL CONVERSATION
        # ==========================================

        from engine.features import chatBot

        chatBot(query)

        return True

    except Exception as e:

        print("Command error:", type(e).__name__, e)

        speak("Sorry, something went wrong.")

        return False


# ==========================================
# EXIT PHRASES
# ==========================================

def is_exit(query):

    q = query.strip().lower()

    words = re.findall(r"\w+", q)

    if q in ("stop", "end", "sleep"):
        return True

    phrases = [
        "stop conversation",
        "end conversation",
        "stop listening",
        "go to sleep",
        "that's all",
        "that is all"
    ]

    if any(p in q for p in phrases):
        return True

    return (
        len(words) <= 4
        and any(
            w in ("bye", "goodbye", "exit", "quit")
            for w in words
        )
    )


# ==========================================
# MAIN LOOP
# ==========================================

@eel.expose
def allCommands(message=1):

    session["id"] += 1

    my_id = session["id"]

    stopSpeaking()

    voice_mode = message == 1

    typed = (
        None
        if voice_mode
        else str(message).lower().strip()
    )

    silent_rounds = 0
    superseded = False

    try:

        while True:

            barge.stop()

            _notify_speaking(False)

            if typed is not None:

                query = typed
                typed = None

                eel.DisplayQuestion(query)
                eel.DisplayMessage("Thinking...")

            else:

                query = takecommand()

            if my_id != session["id"]:

                superseded = True
                return

            speech["stop"] = False

            print("Recognized:", query)

            if not query:

                silent_rounds += 1

                if (
                    not (voice_mode and CONTINUOUS_CONVERSATION)
                    or silent_rounds >= 2
                ):
                    break

                continue

            silent_rounds = 0

            if is_exit(query):

                speak("Okay, goodbye. Call me when you need me.")

                break

            keep_going = handle_query(query)

            if my_id != session["id"]:

                superseded = True
                return

            if not (
                voice_mode
                and CONTINUOUS_CONVERSATION
                and keep_going
            ):
                break

            eel.sleep(0.1)

    except Exception as e:

        print("Loop error:", type(e).__name__, e)

    finally:

        if not superseded:

            barge.stop()
            barge.reset()

            _notify_speaking(False)

            eel.ShowHood()