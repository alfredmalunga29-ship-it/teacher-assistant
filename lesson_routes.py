"""Lesson plan routes. Wire this into app.py with:

    from lesson_routes import init_lesson_plan
    init_lesson_plan(app, ask_ai)

where ask_ai(prompt: str) -> str calls your existing AI model and returns its text.
"""
import json
import os
import re
import traceback

from flask import Blueprint, jsonify, redirect, render_template, request, send_file, session

from curriculum import CURRICULA, DURATIONS, SUBJECTS, TOPICS
from lesson_docx import (CBC_FIELDS, CBC_STAGE_KEYS, CBC_STAGES, META_KEYS, OLD_FIELDS,
                         OLD_STAGE_KEYS, OLD_STAGES, build_docx, safe_filename, schema, stage_times)

lesson_bp = Blueprint("lesson", __name__)
_ask_ai = None
MAX_FIELD = 4000


def _reference_files():
    base = os.path.dirname(os.path.abspath(__file__))
    refs = {}
    for folder_name in ["School Material", "Tests"]:
        folder = os.path.join(base, folder_name)
        if os.path.isdir(folder):
            refs[folder_name] = sorted(os.listdir(folder))[:20]
    return refs


def _reference_hint(subject, topic, document_type):
    refs = _reference_files()
    names = []
    for folder_name, files in refs.items():
        names.extend(f"{folder_name}: {name}" for name in files)
    hint = ", ".join(names[:25]) if names else "No local reference file was found for this topic."
    return (
        f"Use the following school resource references as guidance for style and scope: {hint}. "
        f"Keep the {document_type} aligned to subject '{subject}' and topic '{topic}'."
    )


def init_lesson_plan(app, ask_ai):
    global _ask_ai
    _ask_ai = ask_ai
    app.register_blueprint(lesson_bp)


def _logged_in():
    # Adjust if your login code stores a different session key.
    return bool(session.get("full_name") or session.get("email") or session.get("user_id"))


def _text(v):
    if isinstance(v, list):
        v = "\n".join(str(x) for x in v)
    return str(v or "").strip()[:MAX_FIELD]


def _offline_lesson_plan_from_request(layout, subject, class_name, topic, subtopic, duration):
    topic = topic or "Computer Basics"
    subtopic = subtopic or "Core concept"
    subject = subject or "ICT"
    class_name = class_name or "Form 1"
    duration = int(duration or 40)
    return {
        "topic": topic,
        "subtopic": subtopic,
        "general_competences": "Critical thinking, Collaboration, Communication",
        "lesson_goal": f"By the end of the lesson, learners will be able to explain the key ideas behind {topic.lower()} and apply them in a classroom activity.",
        "specific_competences": "- Identify the main parts or ideas related to the topic.\n- Explain the concept in their own words.\n- Apply the concept to a short classroom activity.",
        "rationale": "The lesson helps learners build practical understanding of the topic and connect classroom learning to everyday use.",
        "prior_knowledge": "Learners know how to participate in classroom discussion and use basic classroom materials.",
        "references": "Teacher's notes, textbook, classroom examples.",
        "learning_environment": "Normal classroom with chalkboard or whiteboard and simple visual aids.",
        "materials": "Board, markers, charts, learner notebooks, projector if available.",
        "expected_standard": "Learners can describe the key idea and answer a simple question about it correctly.",
        "stages": {
            "introduction": {
                "teacher": "Ask learners what they already know about the topic and connect it to real life.",
                "learners": "Share prior knowledge and respond to simple questions.",
                "assessment": "Ask 2-3 quick oral questions to check understanding."
            },
            "development": {
                "teacher": "Explain the main idea clearly with examples and a short demonstration.",
                "learners": "Listen, take notes, and ask questions where needed.",
                "assessment": "Check whether learners can explain the key idea in their own words."
            },
            "exercise": {
                "teacher": "Give a short class task or exercise based on the topic.",
                "learners": "Work individually or in pairs to complete the activity.",
                "assessment": "Review learner answers and correct misconceptions."
            },
            "homework": {
                "teacher": "Assign a brief follow-up task to reinforce the concept.",
                "learners": "Complete the written task in their notebooks.",
                "assessment": "Check the homework for accuracy and understanding."
            },
            "conclusion": {
                "teacher": "Summarise the lesson and reinforce the key points.",
                "learners": "State one thing they learned and one question they still have.",
                "assessment": "Use a brief exit question to confirm learning."
            }
        }
    }


def _normalise(layout, meta, content):
    """Guarantees every field exists and is plain text, so the document never breaks."""
    fields, stages, stage_keys = (
        (CBC_FIELDS, CBC_STAGES, CBC_STAGE_KEYS) if layout == "cbc" else (OLD_FIELDS, OLD_STAGES, OLD_STAGE_KEYS)
    )
    content = content if isinstance(content, dict) else {}
    out = {k: _text(content.get(k)) for k, _ in fields}
    out["stages"] = {}
    raw_stages = content.get("stages") if isinstance(content.get("stages"), dict) else {}
    for sk, _ in stages:
        s = raw_stages.get(sk) if isinstance(raw_stages.get(sk), dict) else {}
        out["stages"][sk] = {k: _text(s.get(k)) for k, _ in stage_keys}
    meta = meta if isinstance(meta, dict) else {}
    clean_meta = {k: _text(meta.get(k)) for k in META_KEYS}
    clean_meta["duration"] = clean_meta["duration"] or "40"
    return {"layout": layout, "meta": clean_meta, "content": out}


def _fill_missing_lesson_plan(layout, subject, class_name, topic, subtopic, duration, data):
    fallback = _offline_lesson_plan_from_request(layout, subject, class_name, topic, subtopic, duration)
    if not isinstance(data, dict):
        return fallback

    fields, stages, stage_keys = (
        (CBC_FIELDS, CBC_STAGES, CBC_STAGE_KEYS) if layout == "cbc" else (OLD_FIELDS, OLD_STAGES, OLD_STAGE_KEYS)
    )
    cleaned = dict(data)
    for key, _ in fields:
        if not cleaned.get(key):
            cleaned[key] = fallback.get(key, "")

    raw_stages = cleaned.get("stages") if isinstance(cleaned.get("stages"), dict) else {}
    cleaned["stages"] = {}
    for sk, _ in stages:
        src = raw_stages.get(sk) if isinstance(raw_stages.get(sk), dict) else {}
        default_stage = fallback.get("stages", {}).get(sk, {})
        item = {}
        for key, _ in stage_keys:
            item[key] = src.get(key) or default_stage.get(key) or ""
        cleaned["stages"][sk] = item

    return cleaned


def _build_prompt(layout, subject, topic, class_name, duration, document_type="lesson_plan", detail_level="Brief overview", note_format="Bullet points", completion_window=None, due_date=None):
    t = stage_times(duration)
    reference_hint = _reference_hint(subject, topic, document_type)
    common = (
        f"You are an experienced Zambian secondary school teacher writing a {document_type.replace('_', ' ')}.\n"
        f"Subject: {subject}\nClass: {class_name}\nTopic / sub-topic: {topic}\n"
        f"Lesson length: {duration} minutes.\n"
        f"Desired detail: {detail_level}.\n"
        f"Preferred format: {note_format}.\n"
        f"{reference_hint}\n"
        "Rules: keep it practical for a Zambian classroom with limited resources. Use the School Material folder as a style guide for clean, readable notes with clear headings, concise explanations, and a polished school-textbook feel. If the topic includes syllabus numbers "
        "(like 2.1.1), keep them; otherwise do NOT invent syllabus codes. Do not invent specific syllabus document years. "
        "Use \\n for line breaks inside a value, and **double stars** around words that should be bold. Return ONLY one JSON object, no markdown fences.\n"
    )
    if document_type == "notes":
        return common + (
            "Create polished, classroom-ready NOTES that look like neat school notes: concise, clean headings, short explanations, and simple learner-friendly examples. Use the chosen detail level and format. Return JSON with keys: "
            '{"title": "", "summary": "", "main_points": "one per line", "key_terms": "one per line", "teacher_notes": ""}'
        )
    if document_type == "assignment":
        completion_window = completion_window or "not specified"
        due_date = due_date or "not specified"
        return common + (
            f"Completion window: {completion_window}.\nDue date: {due_date}.\n"
            "Create a practical ASSIGNMENT with tasks and marking guide. Return JSON with keys: "
            '{"title": "", "instructions": "", "questions": "one per line", "rubric": ""}'
        )
    if document_type == "test":
        return common + (
            "Create a school-style TEST with short answer and longer questions. Return JSON with keys: "
            '{"title": "", "instructions": "", "questions": "one per line", "marking_guide": ""}'
        )
    if layout == "cbc":
        return common + (
            "Curriculum: Zambia Competence-Based Curriculum (CBC), written for a Form class.\n"
            'Split the teacher\'s input into "topic" and "subtopic". JSON keys:\n'
            '{"topic": "", "subtopic": "", "general_competences": "", "lesson_goal": "By the end of the lesson, '
            'learners will be able to ...", "specific_competences": "one per line", "rationale": "", '
            '"prior_knowledge": "", "references": "", "learning_environment": "", "materials": "", '
            '"expected_standard": "", "stages": {"introduction": {"teacher": "", "learners": "", "assessment": ""}, '
            '"development": {...}, "exercise": {...}, "homework": {...}, "conclusion": {...}}}\n'
            f"Time plan: introduction {t['introduction']} min, development {t['development']} min, "
            f"exercise {t['exercise']} min, conclusion {t['conclusion']} min. "
            "Introduction starts with a **Scenario:** question. Development lists numbered steps with a learner task. "
            "Assessment criteria for development should include methods (Question and Answer / Group discussion / "
            "note taking / presentation) and what a correct result looks like. Exercise is an individual task. "
            "General competences usually: Critical thinking, Collaboration, Creativity, Innovation, and Communication."
        )
    return common + (
        "Curriculum: old Zambian curriculum, written for a Grade class (LSBAT = Learners Should Be Able To).\n"
        'Split the teacher\'s input into "topic" and "subtopic". JSON keys:\n'
        '{"topic": "", "subtopic": "", "outcomes": "one per line, starting with a verb", "knowledge": "", '
        '"skills": "", "values": "", "teaching_aids": "", "stages": {"introduction": {"content": "", '
        '"methodology": "", "activity": ""}, "development": {...}, "application": {...}, "conclusion": {...}}}\n'
        "Introduction is usually a recap (methodology Q/A). Development holds the real lesson content with "
        "short notes. Application is a CLASS EXERCISE with 3-5 questions (methodology Questions and Answers). "
        "Conclusion recaps the main points."
    )


def _extract_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("The AI did not return a lesson plan. Please try again.")
    return json.loads(text[start:end + 1])


def _render_document_page(template_name, title, document_type):
    if not _logged_in():
        return redirect("/")
    cfg = {"curricula": CURRICULA, "subjects": SUBJECTS, "durations": DURATIONS, "topics": TOPICS, "schema": schema()}
    return render_template(
        template_name,
        cfg=cfg,
        full_name=session.get("full_name", ""),
        curricula=CURRICULA,
        subjects=SUBJECTS,
        durations=DURATIONS,
        topics=TOPICS,
        title=title,
        document_type=document_type,
    )


@lesson_bp.route("/lesson-plan")
def lesson_page():
    return _render_document_page("lesson_plan.html", "Lesson Plan", "lesson_plan")


@lesson_bp.route("/notes")
def notes_page():
    return _render_document_page("notes.html", "Notes", "notes")


@lesson_bp.route("/assignment")
def assignment_page():
    return _render_document_page("assignment.html", "Assignment", "assignment")


@lesson_bp.route("/test")
def test_page():
    return _render_document_page("test.html", "Test", "test")


@lesson_bp.route("/lesson-plan/generate", methods=["POST"])
def lesson_generate():
    if not _logged_in():
        return jsonify(error="Please log in again."), 401

    d = request.get_json(silent=True) or {}

    layout = (d.get("curriculum") or "").strip().lower()
    document_type = (d.get("document_type") or "lesson_plan").strip().lower()
    subject = (d.get("subject") or "").strip()
    class_name = (d.get("class_name") or "").strip()
    topic = (d.get("topic") or d.get("topics") or "").strip()
    subtopic = (d.get("subtopic") or "").strip()
    detail_level = (d.get("detail_level") or "Brief overview").strip()
    note_format = (d.get("note_format") or "Bullet points").strip()
    completion_window = (d.get("duration_to_complete") or "").strip()
    due_date = (d.get("due_date") or "").strip()

    try:
        duration = int(d.get("duration") or 80)
    except (TypeError, ValueError):
        return jsonify(error="Duration must be a number in minutes."), 400

    if document_type not in {"lesson_plan", "notes", "assignment", "test"}:
        return jsonify(error="Please choose a valid document type."), 400

    if layout not in CURRICULA:
        return jsonify(error="Please choose a valid curriculum."), 400

    if document_type == "notes":
        if not subject:
            return jsonify(error="Please enter a subject."), 400
    elif subject not in SUBJECTS:
        return jsonify(error=f"Please choose a valid subject. Got: {subject!r}"), 400

    if document_type != "notes" and class_name not in CURRICULA[layout]["classes"]:
        return jsonify(error=f"Please choose a valid class for {layout}. Got: {class_name!r}"), 400

    if duration not in DURATIONS:
        return jsonify(error="Please choose a valid duration."), 400

    if not topic:
        return jsonify(error="Please enter a topic."), 400

    if _ask_ai is None:
        return jsonify(error="AI is not connected to the lesson plan tool yet."), 500

    try:
        prompt = _build_prompt(layout, subject, topic, class_name, duration, document_type, detail_level, note_format, completion_window, due_date)
        ai_response = _ask_ai(prompt)
        data = _extract_json(ai_response)
    except Exception as e:
        traceback.print_exc()
        if document_type == "lesson_plan":
            data = _offline_lesson_plan_from_request(layout, subject, class_name, topic, subtopic, duration)
        else:
            user_topic = topic or (d.get("topics") or "") or "the selected topic"
            completion_window = completion_window or f"{duration} minutes"
            due_date_text = due_date or "Not specified"
            if document_type == "assignment":
                data = {
                    "title": f"{subject or 'Assignment'}: {user_topic}",
                    "summary": f"{subject or 'This subject'} assignment based on {user_topic} for {class_name or 'the class'}.",
                    "main_points": "- Read the instructions carefully.\n- Complete every task in full.\n- Present your work clearly and show your reasoning.",
                    "key_terms": "topic\nresearch\nanalysis\nsubmission\nassessment",
                    "teacher_notes": f"Completion window: {completion_window}. Due date: {due_date_text}.",
                    "instructions": f"Answer all parts of the task on {due_date_text}. Work independently and use relevant examples from {user_topic}.",
                    "questions": f"1. Explain the main idea behind {user_topic}.\n2. Give one practical example.\n3. Complete the task using clear steps and correct terminology.",
                    "rubric": "Understanding 5 marks, Application 3 marks, Presentation 2 marks.",
                    "marking_guide": "Award marks for accuracy, relevance, clarity, and completion.",
                }
            else:
                data = {
                    "title": f"{subject or 'Document'} - {user_topic}",
                    "summary": f"{subject or 'This subject'} task based on {user_topic} for {class_name or 'the class'}.",
                    "main_points": "- Review the topic carefully.\n- Complete the required response in full.\n- Present the final work clearly.",
                    "key_terms": "topic\nanswer\ncheck\nsubmission",
                    "teacher_notes": f"Completion window: {completion_window}. Due date: {due_date_text}.",
                    "instructions": "Follow the guidelines and respond clearly using good school presentation.",
                    "questions": f"1. Describe the key idea of {user_topic}.\n2. Give a short example.\n3. Present your final answer in a neat format.",
                    "rubric": "Content 5 marks, Accuracy 3 marks, Presentation 2 marks.",
                    "marking_guide": "Award marks for correctness, structure, and completion.",
                }

    if document_type == "lesson_plan":
        data = _fill_missing_lesson_plan(layout, subject, class_name, topic, subtopic, duration, data)

    meta = {
        "teacher": session.get("full_name", ""),
        "date": "",
        "class_name": class_name,
        "duration": (completion_window or str(duration)) if document_type == "assignment" else str(duration),
        "ts_number": "",
        "subject": subject,
        "topic": topic if document_type != "lesson_plan" else ((data.get("topic") if isinstance(data, dict) else None) or topic or (d.get("topics") or "") or "the selected topic"),
        "subtopic": (data.get("subtopic") if isinstance(data, dict) else None) or subtopic or "",
        "boys": "",
        "girls": "",
        "total": "",
    }

    if document_type == "lesson_plan":
        return jsonify(plan=_normalise(layout, meta, data), document_type=document_type)
    return jsonify(plan={"document_type": document_type, "meta": meta, "content": data}, document_type=document_type)


@lesson_bp.route("/lesson-plan/download", methods=["POST"])
def lesson_download():
    if not _logged_in():
        return jsonify(error="Please log in again."), 401
    d = request.get_json(silent=True) or {}
    layout = d.get("layout")
    if layout not in CURRICULA:
        return jsonify(error="Unknown layout."), 400
    plan = _normalise(layout, d.get("meta"), d.get("content"))
    if plan["meta"]["subject"] not in SUBJECTS:
        return jsonify(error="Unknown subject."), 400
    buf = build_docx(plan)
    return send_file(buf, as_attachment=True, download_name=safe_filename(plan),
                     mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
