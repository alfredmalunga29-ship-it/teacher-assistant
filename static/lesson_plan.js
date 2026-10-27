(() => {
  const form = document.getElementById("lesson-form");
  const generateButton = document.getElementById("generate-btn");
  const formError = document.getElementById("form-error");
  const previewPanel = document.getElementById("preview-panel");
  const previewContent = document.getElementById("preview-content");
  const downloadButton = document.getElementById("download-btn");
  const downloadError = document.getElementById("download-error");
  let generatedText = "";

  function message(node, text) {
    node.textContent = text || "";
    node.hidden = !text;
  }

  function safeRender(text) {
    previewContent.replaceChildren();
    const lines = String(text || "").split(/\r?\n/);
    let currentList = null;
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) { currentList = null; continue; }
      const headingMatch = trimmed.match(/^(#{1,3}\s+|\*\*[^*]+\*\*$)(.*)$/);
      if (/^#{1,3}\s+/.test(trimmed) || (/^\*\*.*\*\*$/.test(trimmed) && trimmed.length < 100)) {
        currentList = null;
        const h = document.createElement("h3");
        h.textContent = trimmed.replace(/^#{1,3}\s+/, "").replace(/^\*\*|\*\*$/g, "");
        previewContent.appendChild(h);
      } else if (/^[-*•]\s+/.test(trimmed)) {
        if (!currentList) { currentList = document.createElement("ul"); previewContent.appendChild(currentList); }
        const li = document.createElement("li"); li.textContent = trimmed.replace(/^[-*•]\s+/, ""); currentList.appendChild(li);
      } else {
        currentList = null;
        const p = document.createElement("p"); p.textContent = trimmed; previewContent.appendChild(p);
      }
    }
  }

  form.addEventListener("submit", async event => {
    event.preventDefault();
    message(formError, "");
    message(downloadError, "");
    if (!form.reportValidity()) return;
    generateButton.disabled = true;
    generateButton.textContent = "Generating…";
    downloadButton.disabled = true;
    try {
      const response = await fetch("/lesson-plan/generate", {
        method: "POST",
        headers: {"Content-Type": "application/json", "Accept": "application/json"},
        body: JSON.stringify(Object.fromEntries(new FormData(form).entries()))
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || data.message || `Request failed (${response.status}).`);
      generatedText = String(data.content || data.lesson_plan || data.text || "");
      if (!generatedText) throw new Error("The server returned an empty lesson plan.");
      safeRender(generatedText);
      previewPanel.hidden = false;
      downloadButton.disabled = false;
      previewPanel.scrollIntoView({behavior:"smooth", block:"start"});
    } catch (err) {
      message(formError, `${err.message || "Could not generate the lesson plan."} Check the Flask terminal for details.`);
    } finally {
      generateButton.disabled = false;
      generateButton.innerHTML = 'Generate lesson plan <span aria-hidden="true">→</span>';
    }
  });

  downloadButton.addEventListener("click", async () => {
    message(downloadError, "");
    if (!generatedText) return;
    downloadButton.disabled = true;
    downloadButton.textContent = "Preparing Word document…";
    try {
      const fields = Object.fromEntries(new FormData(form).entries());
      const response = await fetch("/lesson-plan/download", {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({...fields, content:generatedText})
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || data.message || `Download failed (${response.status}).`);
      }
      const blob = await response.blob();
      const disposition = response.headers.get("Content-Disposition") || "";
      const match = disposition.match(/filename="?([^"]+)"?/i);
      const filename = match ? match[1] : "lesson-plan.docx";
      const objectUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = objectUrl; a.download = filename; document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(objectUrl);
    } catch (err) {
      message(downloadError, err.message || "Could not download the document.");
    } finally {
      downloadButton.disabled = false;
      downloadButton.textContent = "Download Word (.docx)";
    }
  });
})();
