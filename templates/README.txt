TEACHER ASSISTANT — LESSON PLAN DROPDOWN PACKAGE
================================================

FILES
- templates/lesson_plan.html
- static/lesson_plan.css
- static/lesson_plan.js
- chat_quick_actions.html

INSTALL
1. Back up your project.
2. Copy templates/lesson_plan.html into:
   D:\Programs\Web Development\Teacher Assistant\templates\
3. Copy lesson_plan.css and lesson_plan.js into:
   D:\Programs\Web Development\Teacher Assistant\static\
4. Open templates/chat.html. Replace the existing Lesson Plan, Notes,
   Assignment and Quiz/Test buttons with the links in chat_quick_actions.html.
   Do not replace the entire chat.html file.
5. In app.py, ensure the lesson blueprint is registered exactly once after
   the Flask app and ask_ai function exist:
       from lesson_routes import init_lesson_plan
       init_lesson_plan(app, ask_ai)
6. Ensure lesson_routes.py defines the page endpoints and these POST routes:
       /lesson-plan/generate
       /lesson-plan/download
7. Run:
       cd "D:\Programs\Web Development\Teacher Assistant"
       python app.py
   Then sign in and open /lesson-plan using the local URL/port printed by Flask.

BACKEND COMPATIBILITY
The form sends JSON to /lesson-plan/generate with keys:
document_type, curriculum, subject, class_name, duration, topic,
learning_objectives, additional_instructions.
The download route receives those fields plus generated and plan containing
the generated response. Your existing lesson_routes.py must accept these keys.
This package intentionally does not replace app.py, lesson_routes.py,
curriculum.py or lesson_docx.py because those contain project-specific logic.
If the page opens but generation fails, send the route code and terminal error
so the request/response format can be matched exactly.

SECURITY
Do not put .env in a ZIP or commit it to Git. A previously shared .env included
API/database credentials. Rotate/revoke those credentials in the provider
dashboards, update local .env and Render environment variables, and keep .env
excluded by .gitignore.
