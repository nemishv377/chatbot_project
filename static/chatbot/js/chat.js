// ---------------------------------------------------------------
// Simple vanilla‑JS client for the chat UI with session support
// ---------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("chat-form");
    const input = document.getElementById("question-input");
    const chatBox = document.getElementById("chat-box");
    const newChatBtn = document.getElementById("new-chat");
    const backBtn = document.getElementById("back-btn");

    // Determine chat mode based on URL path or another heuristic
    // Example assumes URL path contains either '/assistant/' or '/general/'
    let chatMode = null;
    if (window.location.pathname.includes("/assistant/")) {
        chatMode = "assistant";
    } else if (window.location.pathname.includes("/general/")) {
        chatMode = "general";
    } else {
        // Default mode or handle error
        chatMode = "assistant"; // fallback or set null and disable chat
    }

    // Keys and endpoints based on mode
    const sessionStorageKey = chatMode === "assistant" ? "assistant_chat_session_id" : "general_chat_session_id";
    const apiBasePath = chatMode === "assistant" ? "/chatbot/assistant/" : "/chatbot/general/";

    // Load session id from localStorage
    let sessionId = localStorage.getItem(sessionStorageKey) || null;

    // Toast notification function
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

    // Append message to chat box
    const appendMessage = (text, sender) => {
        const msgDiv = document.createElement("div");
        msgDiv.className = `msg ${sender}`;
        const bubble = document.createElement("div");
        bubble.className = "bubble";
        bubble.innerHTML = text;
        msgDiv.appendChild(bubble);
        chatBox.appendChild(msgDiv);
        chatBox.scrollTop = chatBox.scrollHeight;
    };

    // Back button clears session and redirects home
    if (backBtn) {
        backBtn.addEventListener("click", () => {
            // Clear session id
            sessionId = null;
            localStorage.removeItem(sessionStorageKey);
            window.location.href = "/chatbot/"; // redirect to home page
        });
    }

    const startNewChat = () => {
        sessionId = null;
        localStorage.removeItem(sessionStorageKey);
        chatBox.innerHTML = "";
    };

    if (newChatBtn) {
        newChatBtn.addEventListener("click", startNewChat);
    }

    // Load chat history from backend if session exists
    const loadChatHistory = async () => {
        if (!sessionId) return;
        try {
            const resp = await fetch(`${apiBasePath}${sessionId}/`, { method: "GET" });
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
            const resp = await fetch(`${apiBasePath}${sessionId}/`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    question: question,
                    session_id: sessionId,
                }),
            });

            const data = await resp.json();

            if (resp.ok) {
                appendMessage(data.answer, "assistant");
                // Save new session_id if returned
                if (data.session_id) {
                    sessionId = data.session_id;
                    localStorage.setItem(sessionStorageKey, sessionId);
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
