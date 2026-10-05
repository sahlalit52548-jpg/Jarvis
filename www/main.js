$(document).ready(function () {

    console.log("Jarvis main.js started");

    // =====================================
    // CLEAR PREVIOUS QUESTION + ANSWER
    // =====================================

    function clearPreviousAnswer() {

        $(".siri-question").text("");

        $(".siri-message")
            .stop(true, true)
            .text("")
            .removeClass("animated bounceIn bounceOut fadeInUp fadeOutUp")
            .css({
                display: "block",
                opacity: 1,
                visibility: "visible",
                animation: "none",
                transition: "none"
            });
    }

    // =====================================
    // SHOW JARVIS ANSWER (called from Python)
    // =====================================

    function DisplayMessage(message) {

        console.log("Jarvis received:", message);

        $(".siri-message")
            .stop(true, true)
            .removeClass("animated bounceIn bounceOut fadeInUp fadeOutUp")
            .text(message)
            .css({
                display: "block",
                opacity: 1,
                visibility: "visible",
                animation: "none",
                transition: "none"
            });
    }

    eel.expose(DisplayMessage);

    // =====================================
    // SHOW USER QUESTION (called from Python)
    // =====================================

    function DisplayQuestion(question) {
        $(".siri-question").text(question);
    }

    eel.expose(DisplayQuestion);

    // =====================================
    // SPEAKING STATE (called from Python)
    // While Jarvis talks, the wake word is ignored,
    // so he cannot interrupt himself by hearing his own name.
    // You can still interrupt by talking, or with Stop / Esc.
    // =====================================

    window.jarvisSpeaking = false;

    function SetSpeaking(flag) {
        window.jarvisSpeaking = !!flag;

        $("#StopBtn")
            .toggleClass("btn-danger", !!flag)
            .toggleClass("btn-outline-danger", !flag);
    }

    eel.expose(SetSpeaking);

    // =====================================
    // TEXTILLATE (heading only)
    // =====================================

    if ($(".text").length > 0) {

        $(".text").textillate({
            loop: true,
            sync: true,
            in: { effect: "bounceIn" },
            out: { effect: "bounceOut" }
        });

    }

    // =====================================
    // SIRI WAVE (initialize only once)
    // =====================================

    const siriContainer = document.getElementById("siri-container");

    if (siriContainer && !siriContainer.dataset.initialized) {

        siriContainer.dataset.initialized = "true";

        new SiriWave({
            container: siriContainer,
            width: 800,
            height: 200,
            style: "ios9",
            amplitude: 1,
            speed: 0.3,
            autostart: true
        });

        console.log("Siri Wave initialized once");
    }

    // =====================================
    // SHOW LISTENING SCREEN
    // =====================================

    function showListeningScreen() {

        // Cancel the pending "return to hood" timer from controller.js
        clearTimeout(window.hoodTimer);

        clearPreviousAnswer();

        $("#Oval").prop("hidden", true);
        $("#SiriWave").prop("hidden", false);
    }

    // =====================================
    // MICROPHONE BUTTON
    // =====================================

    $("#MicBtn").click(function () {

        console.log("Microphone clicked");

        showListeningScreen();

        eel.allCommands();
    });

    // =====================================
    // AUTOMATIC STARTUP (greeting, then listen)
    // =====================================

    setTimeout(function () {

        console.log("Jarvis startup greeting");

        showListeningScreen();

        $(".siri-message").first().text("Hello, I am J.A.R.V.I.S");

        try {
            if (typeof eel.startupGreeting === "function") {
                eel.startupGreeting();
            } else {
                console.warn("startupGreeting not found, listening directly");
                eel.allCommands();
            }
        } catch (err) {
            console.error("Startup error:", err);
            eel.allCommands();
        }

    }, 2000);

    // =====================================
    // SEND TYPED MESSAGE
    // =====================================

    window.PlayAssistant = function (message) {

        message = message.trim();

        if (message === "") {
            return;
        }

        console.log("Sending message:", message);

        showListeningScreen();

        eel.allCommands(message);

        $("#chatbox").val("");

        $("#MicBtn").prop("hidden", false);
        $("#SendBtn").prop("hidden", true);
    };

    // =====================================
    // MIC / SEND BUTTON TOGGLE
    // =====================================

    function ShowHideButton(message) {

        if (message.trim().length === 0) {

            $("#MicBtn").prop("hidden", false);
            $("#SendBtn").prop("hidden", true);

        } else {

            $("#MicBtn").prop("hidden", true);
            $("#SendBtn").prop("hidden", false);
        }
    }

    $("#chatbox").on("input", function () {
        ShowHideButton($(this).val());
    });

    // =====================================
    // SEND BUTTON
    // =====================================

    $("#SendBtn").click(function (e) {

        e.preventDefault();

        PlayAssistant($("#chatbox").val());
    });

    // =====================================
    // ENTER KEY
    // =====================================

    $("#chatbox").on("keydown", function (e) {

        if (e.key === "Enter") {

            e.preventDefault();

            PlayAssistant($(this).val());
        }
    });

    // =====================================
    // JARVIS WAKE SHORTCUT (CTRL + SHIFT + J)
    // Sent automatically by the hotword detector
    // =====================================

    document.addEventListener("keydown", function (e) {

        if (
            e.ctrlKey &&
            e.shiftKey &&
            e.key.toLowerCase() === "j"
        ) {

            // Jarvis' own voice can trigger the wake word: ignore it while he talks
            if (window.jarvisSpeaking) {
                console.log("Wake word ignored (Jarvis is speaking)");
                return;
            }

            console.log("Jarvis wake shortcut detected");

            if (typeof eel.playAssistantSound === "function") {
                eel.playAssistantSound();
            }

            showListeningScreen();

            eel.allCommands();
        }
    });

    // =====================================
    // STOP SPEAKING (button or Esc key)
    // Jarvis stops talking and goes straight
    // to listening for your next question
    // =====================================

    $("#StopBtn").click(function () {
        console.log("Stop pressed");
        eel.stopSpeaking();
    });

    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape") {
            console.log("Esc pressed, stopping speech");
            eel.stopSpeaking();
        }
    });

});