(() => {
  const form = document.getElementById('chat-form');
  const input = document.getElementById('message-input');
  const win = document.getElementById('chat-window');
  const send = document.getElementById('send-button');
  const err = document.getElementById('chat-error');
  const layout = document.getElementById('layout');
  const fileInput = document.getElementById('file-input');
  const attachButton = document.getElementById('attach-button');
  const selectedFiles = document.getElementById('selected-files');
  let pendingFiles = [];

  if (!form || !input || !win || !send || !err || !fileInput || !attachButton || !selectedFiles) return;

  function showError(message) {
    err.textContent = message || 'Something went wrong.';
    err.hidden = false;
  }
  function clearError() {
    err.textContent = '';
    err.hidden = true;
  }
  function resizeInput() {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 180) + 'px';
  }
  function addMessage(role, text) {
    const row = document.createElement('div');
    row.className = 'message ' + role;
    if (role === 'assistant') {
      const avatar = document.createElement('div');
      avatar.className = 'assistant-avatar';
      avatar.textContent = '✦';
      row.appendChild(avatar);
    }
    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.textContent = text;
    row.appendChild(bubble);
    win.appendChild(row);
    win.scrollTop = win.scrollHeight;
    return bubble;
  }
  function bindPromptButtons() {
    document.querySelectorAll('[data-prompt]').forEach(element => {
      if (element.dataset.promptBound === '1') return;
      element.dataset.promptBound = '1';
      element.addEventListener('click', () => {
        input.value = element.dataset.prompt || '';
        resizeInput();
        input.focus();
        layout?.classList.remove('mobile-open');
      });
    });
  }
  function renderFiles() {
    selectedFiles.replaceChildren();
    selectedFiles.hidden = pendingFiles.length === 0;
    pendingFiles.forEach((file, index) => {
      const chip = document.createElement('div');
      chip.className = 'selected-file';
      const icon = document.createElement('span');
      icon.className = 'file-chip-icon';
      icon.textContent = file.name.toLowerCase().endsWith('.pdf') ? 'PDF' : 'FILE';
      const name = document.createElement('span');
      name.className = 'selected-file-name';
      name.textContent = file.name;
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'remove-file';
      remove.textContent = '×';
      remove.setAttribute('aria-label', 'Remove ' + file.name);
      remove.addEventListener('click', () => {
        pendingFiles.splice(index, 1);
        renderFiles();
      });
      chip.append(icon, name, remove);
      selectedFiles.appendChild(chip);
    });
  }
  function resetWelcome() {
    // A page reload restores the server-rendered welcome state and avoids mismatched template URLs.
    window.location.href = window.location.pathname;
  }

  input.addEventListener('input', resizeInput);
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  bindPromptButtons();
  attachButton.addEventListener('click', () => fileInput.click());
  document.getElementById('welcome-import')?.addEventListener('click', () => fileInput.click());

  fileInput.addEventListener('change', () => {
    const allowed = /\.(pdf|docx|txt|pptx|xlsx|csv|png|jpe?g)$/i;
    const maxSize = 15 * 1024 * 1024;
    const chosen = Array.from(fileInput.files || []);
    const invalid = chosen.filter(file => !allowed.test(file.name));
    const tooLarge = chosen.filter(file => file.size > maxSize);
    if (invalid.length) showError('Unsupported file type: ' + invalid.map(file => file.name).join(', ') + '. Use PDF, DOCX, TXT, PPTX, XLSX, CSV, PNG or JPG.');
    else if (tooLarge.length) showError('Each file must be 15 MB or smaller: ' + tooLarge.map(file => file.name).join(', '));
    else clearError();

    chosen.forEach(file => {
      if (!allowed.test(file.name) || file.size > maxSize) return;
      const duplicate = pendingFiles.some(existing =>
        existing.name === file.name && existing.size === file.size && existing.lastModified === file.lastModified
      );
      if (!duplicate) pendingFiles.push(file);
    });
    renderFiles();
    fileInput.value = '';
  });

  document.getElementById('new-chat-btn')?.addEventListener('click', async () => {
    clearError();
    try {
      const response = await fetch('/clear', { method: 'POST' });
      if (!response.ok) throw new Error('Could not clear chat. Please refresh and try again.');
      pendingFiles = [];
      renderFiles();
      input.value = '';
      resizeInput();
      resetWelcome();
    } catch (error) {
      showError(error.message);
    }
  });

  document.getElementById('sidebar-toggle')?.addEventListener('click', () => {
    if (window.matchMedia('(max-width: 760px)').matches) {
      layout?.classList.toggle('mobile-open');
    } else {
      layout?.classList.toggle('collapsed');
    }
  });

  form.addEventListener('submit', async event => {
    event.preventDefault();
    const message = input.value.trim();
    if (!message && pendingFiles.length === 0) {
      showError('Type a message or attach a file first.');
      return;
    }

    clearError();
    const filesForRequest = pendingFiles.slice();
    const prompt = message || 'Please review the attached file(s) and explain what they contain.';
    addMessage('user', prompt + (filesForRequest.length ? '\n📎 ' + filesForRequest.map(file => file.name).join(', ') : ''));
    input.value = '';
    resizeInput();
    send.disabled = true;
    attachButton.disabled = true;
    const pending = addMessage('assistant', 'Thinking…');

    try {
      let response;
      if (filesForRequest.length) {
        const payload = new FormData();
        payload.append('message', prompt);
        filesForRequest.forEach(file => payload.append('files', file, file.name));
        response = await fetch('/send', { method: 'POST', body: payload });
      } else {
        response = await fetch('/send', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: prompt })
        });
      }

      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
      pending.textContent = data.reply || 'No reply was returned.';
      pendingFiles = [];
      renderFiles();
    } catch (error) {
      pending.textContent = error.message || 'Unable to contact the assistant.';
      showError('Message or upload failed. Check the Flask server logs for the specific error.');
    } finally {
      send.disabled = false;
      attachButton.disabled = false;
      input.focus();
      win.scrollTop = win.scrollHeight;
    }
  });
})();