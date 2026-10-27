TEACHER ASSISTANT — BLUE THEME FRONTEND

Files:
- templates/chat.html
- static/chat.css
- static/chat.js

Install:
1. Back up your current three files.
2. Copy these files into the matching folders in your Flask project.
3. Keep your existing teacher-logo.png in static/.
4. Restart Flask and refresh the browser.

Important:
- This is a frontend update with colors matching the blue-gradient login screen.
- The browser sends uploads to POST /send using multipart FormData, with the user's message under "message" and each attachment under "files".
- Your Flask /send route must read request.files.getlist("files") and extract/analyze each file. This frontend alone cannot add backend document processing.
- If your actual Flask endpoint names differ, update the links in chat.html to match your routes.
- Do not replace app.py with a frontend file.


BUILDERROR FIX
Your app.py registers chat_page directly (endpoint name: chat_page), not chat.chat_page. The template has been corrected to use url_for('chat_page').

INSTALL
Copy templates/chat.html to your project templates folder and static/chat.css and static/chat.js to your project static folder. Back up existing files first. Restart Flask and hard-refresh with Ctrl+F5.

NOTE
These are the chat UI files. Keep your existing app.py and other route files. If another BuildError appears, the endpoint name in the error must be matched to the route registered in your app.py.
