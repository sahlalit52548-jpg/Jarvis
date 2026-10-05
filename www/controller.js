$(document).ready(function () {



    // // Display Speak Message
    // eel.expose(DisplayMessage)
    // function DisplayMessage(message) {
    //     // Replace the hidden textillate <li>
    //     $(".siri-message .texts li").text(message);
    // }



    // Display hood
    eel.expose(ShowHood)
    function ShowHood() {
        window.hoodTimer = setTimeout(function () {
            $("#Oval").attr("hidden", false);
            $("#SiriWave").attr("hidden", true);
        }, 4000);
    }


    eel.expose(senderText)
    function senderText(message) {
        var chatBox = document.getElementById("chat-canvas-body");
        if (message.trim() !== "") {
            chatBox.innerHTML += `<div class="row justify-content-end mb-4">
            <div class = "width-size">
            <div class="sender_message">${message}</div>
        </div>`;

            // Scroll to the bottom of the chat box
            chatBox.scrollTop = chatBox.scrollHeight;
        }
    }

    eel.expose(receiverText)
    function receiverText(message) {

        var chatBox = document.getElementById("chat-canvas-body");
        if (message.trim() !== "") {
            chatBox.innerHTML += `<div class="row justify-content-start mb-4">
            <div class = "width-size">
            <div class="receiver_message">${message}</div>
            </div>
        </div>`;

            // Scroll to the bottom of the chat box
            chatBox.scrollTop = chatBox.scrollHeight;
        }

    }

});