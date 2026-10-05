import multiprocessing
import time


def startJarvis():
    print("Jarvis application is starting...")

    from main import start
    start()


def listenHotword(stop_event):
    print("Hotword listener is starting...")

    from engine.features import hotword
    hotword(stop_event)


if __name__ == "__main__":

    multiprocessing.freeze_support()

    stop_event = multiprocessing.Event()

    p1 = multiprocessing.Process(
        target=startJarvis,
        name="JarvisApp"
    )

    p2 = multiprocessing.Process(
        target=listenHotword,
        args=(stop_event,),
        name="HotwordListener"
    )

    try:
        p1.start()
        time.sleep(2)

        if p1.is_alive():
            p2.start()

        p1.join()

    except KeyboardInterrupt:
        print("Stopping Jarvis...")

    finally:
        stop_event.set()

        for process in (p1, p2):

            if process.is_alive():
                process.terminate()
                process.join(timeout=3)

        print("Jarvis stopped successfully.")