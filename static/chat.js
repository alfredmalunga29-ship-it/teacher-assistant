const form = document.getElementById("chat-form");
const input = document.getElementById("message-input");
const chatWindow = document.getElementById("chat-window");
const newChatBtn = document.getElementById("new-chat-btn");
const quickActionButtons = document.querySelectorAll(".quick-action");

// Renders assistant text as formatted markdown (headings, bold, lists, etc.)
// instead of showing raw ** and # characters. DOMPurify strips anything unsafe
// before it's inserted, since this text comes from an AI, not typed by hand.
function renderMarkdown(bubbleElement, rawText) {
    const html = DOMPurify.sanitize(marked.parse(rawText));
    bubbleElement.innerHTML = html;
}

function addMessage(role, content) {
    const emptyState = chatWindow.querySelector(".empty-state");
    if (emptyState) emptyState.remove();

    const messageDiv = document.createElement("div");
    messageDiv.className = `message ${role}`;
    const bubble = document.createElement("div");
    bubble.className = "bubble";

    if (role === "assistant") {
        renderMarkdown(bubble, content);
    } else {
        bubble.textContent = content; // user's own text stays plain, no markdown parsing
    }

    messageDiv.appendChild(bubble);
    chatWindow.appendChild(messageDiv);
    chatWindow.scrollTop = chatWindow.scrollHeight;
    return messageDiv;
}

async function sendMessage(message) {
    if (!message) return;

    addMessage("user", message);
    const thinkingDiv = addMessage("assistant", "Thinking...");
    thinkingDiv.querySelector(".bubble").innerHTML = "Thinking&hellip;"; // plain text, not parsed as markdown

    try {
        const res = await fetch("/send", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message })
        });
        const data = await res.json();
        thinkingDiv.remove();
        addMessage("assistant", data.reply || data.error || "Something went wrong.");
    } catch (err) {
        thinkingDiv.remove();
        addMessage("assistant", "Network error — please check your connection and try again.");
    }
}

form.addEventListener("submit", (e) => {
    e.preventDefault();
    const message = input.value.trim();
    if (!message) return;
    input.value = "";
    sendMessage(message);
});

quickActionButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
        const prompt = btn.getAttribute("data-prompt");
        sendMessage(prompt);
    });
});

newChatBtn.addEventListener("click", async () => {
    await fetch("/clear", { method: "POST" });
    chatWindow.innerHTML = '<div class="empty-state"><p>👋 Ask me to make a lesson plan, a quiz, or a report card comment.</p></div>';
});

// Re-render markdown for any messages already on the page from chat history
// (the server sends these as plain escaped text, so they need this same pass)
document.querySelectorAll(".message.assistant .bubble").forEach((bubble) => {
    const rawText = bubble.textContent;
    renderMarkdown(bubble, rawText);
});
