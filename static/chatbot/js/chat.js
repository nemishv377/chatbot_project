// ---------------------------------------------------------------
// Simple vanilla‑JS client for the chat UI with session support
// ---------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("chat-form");
    const input = document.getElementById("question-input");
    const chatBox = document.getElementById("chat-box");
    const newChatBtn = document.getElementById("new-chat"); // optional button to start a new chat

    // Load session_id from localStorage if exists
    let sessionId = localStorage.getItem("general_chat_session_id") || null;

    // ------------------------------
    // 🔔 Toast Notification Function
    // ------------------------------
    const showToast = (message) => {
        const toast = document.getElementById("toast");
        if (!toast) return;

        toast.textContent = message;
        toast.classList.add("show");

        // Hide after 3 seconds
        setTimeout(() => {
            toast.classList.remove("show");
        }, 3000);
    };

    const appendMessage = (text, sender) => {
        const msgDiv = document.createElement("div");
        msgDiv.className = `msg ${sender}`;
        console.log(msgDiv.className)
        const bubble = document.createElement("div");
        bubble.className = "bubble";
        bubble.innerHTML = text;
        msgDiv.appendChild(bubble);
        chatBox.appendChild(msgDiv);
        chatBox.scrollTop = chatBox.scrollHeight;
    };

    const backBtn = document.getElementById("back-btn");
    if (backBtn) {
        backBtn.addEventListener("click", () => {
            // Clear session id
            sessionId = null;
            localStorage.removeItem("general_chat_session_id");
            window.location.href = "/chatbot/"; // redirect to home page
        });
    }

    const startNewChat = () => {
        sessionId = null;
        localStorage.removeItem("general_chat_session_id");
        chatBox.innerHTML = "";
    };

    // Optional: handle "New Chat" button click
    if (newChatBtn) {
        newChatBtn.addEventListener("click", startNewChat);
    }

    // ------------------------------
    // 1️⃣ Load chat history on page load
    // ------------------------------
    const loadChatHistory = async () => {
        if (!sessionId) return; // no session, nothing to load

        try {
            const resp = await fetch(`/chatbot/general/${sessionId}/`, { method: "GET" });
            if (!resp.ok) throw new Error("Failed to fetch history");

            const data = await resp.json();
            if (data.history && Array.isArray(data.history)) {
                data.history.forEach(msg => appendMessage(msg.message, msg.role));
            }
        } catch (err) {
            showToast("Failed to load chat history. Please try again.");
        }
    };

    loadChatHistory();

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const question = input.value.trim();
        if (!question) return;
        appendMessage(question, "user");
        const lastMsg = chatBox.lastElementChild;
        input.value = "";
        input.disabled = true;
        try {
            const resp = await fetch(`/chatbot/general/${sessionId}/`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    question: question,
                    session_id: sessionId  // send current session_id
                })
            });

            const data = await resp.json();

            if (resp.ok) {
                appendMessage(data.answer, "assistant");
                // Store session_id if returned by backend
                if (data.session_id) {
                    sessionId = data.session_id;
                    localStorage.setItem("general_chat_session_id", sessionId);
                }

            } else {
                //  Remove user message + restore input
                if (lastMsg) chatBox.removeChild(lastMsg);
                input.value = question;
                showToast("Failed to load chat history. Please try again.");
            }
        } catch (err) {
            console.error(err);
            // Remove user message + restore input
            if (lastMsg) chatBox.removeChild(lastMsg);
            input.value = question;
            showToast("Network error – try again later.");
        } finally {
            input.disabled = false;
            input.focus();
        }
    });
});
