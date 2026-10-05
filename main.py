import eel

from engine.features import *
from engine.command import *
from engine.command import shutdown_jarvis


def start():
    eel.init("www")

    playAssistantSound()

    eel.start(
        "index.html",
        mode="edge",
        host="localhost",
        port=8000,
        block=True,
        close_callback=shutdown_jarvis   # stops speech and exits when the window closes
    )