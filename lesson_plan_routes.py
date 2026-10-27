"""Standalone lesson-plan routes for the Teacher Assistant Flask app.

This module uses the app's existing ask_ai(prompt) callback and python-docx.
It does not replace the existing lesson_routes.py module.
"""
from io import BytesIO
import re

from flask import Blueprint, jsonify, render_template, request, send_file
from docx import Document
from docx.shared import Inches, Pt

lesson_builder_bp = Blueprint("lesson_builder", __name__)
_ask_ai = None


def init_lesson_builder(app, ask_ai):
    """Register once, after the Flask app and ask_ai function are defined."""
    global _ask_ai
    _ask_ai = ask_ai
    if "lesson_builder.lesson_page" not in app.view_functions:
        app.register_blueprint(lesson_builder_bp)


@lesson_builder_bp.get("/lesson-plan")
def lesson_page():
    return render_template("lesson_plan.html")


@lesson_builder_bp.post("/lesson-plan/generate")
def generate_lesson_plan():
    if _ask_ai is None:
        return jsonify(error="The AI service has not been connected. Check init_lesson_builder(app, ask_ai) in app.py."), 500

    data = request.get_json(silent=True) or {}
    required = ("curriculum", "subject", "class_name", "duration", "topic")
    missing = [field for field in required if not str(data.get(field, "")).strip()]
    if missing:
        return jsonify(error="Please complete: " + ", ".join(missing)), 400

    objectives = str(data.get("learning_objectives", "")).strip() or "Suggest measurable learning objectives appropriate to the grade and topic."
    extra = str(data.get("additional_instructions", "")).strip() or "Use practical, age-appropriate examples and accessible teaching aids."
    prompt = f"""
Create a detailed, classroom-ready lesson plan. Use clear headings and practical steps.
Curriculum: {data['curriculum']}
Subject: {data['subject']}
Grade/class: {data['class_name']}
Topic: {data['topic']}
Duration: {data['duration']}
Learning objectives: {objectives}
Additional instructions: {extra}

Include: lesson information, prior knowledge, specific measurable objectives, teaching and learning materials,
introduction, step-by-step teacher activities and learner activities with realistic timings that add up to the
specified duration, assessment/checks for understanding, differentiation or learner support, conclusion,
homework/follow-up, and teacher reflection. Keep the plan suitable for the selected curriculum and grade.
Return the complete lesson plan as readable text with headings and bullet points.
"""
    try:
        result = _ask_ai(prompt)
        if isinstance(result, dict):
            result = result.get("content") or result.get("response") or result.get("text") or str(result)
        result = str(result).strip()
        if not result:
            return jsonify(error="The AI service returned an empty response."), 502
        return jsonify(content=result)
    except Exception:
        # Avoid exposing provider credentials or full internal tracebacks to the browser.
        return jsonify(error="Lesson-plan generation failed. Check the Flask terminal for the underlying error."), 500


@lesson_builder_bp.post("/lesson-plan/download")
def download_lesson_plan():
    data = request.get_json(silent=True) or {}
    content = str(data.get("content", "")).strip()
    if not content:
        return jsonify(error="Generate a lesson plan before downloading."), 400

    doc = Document()
    section = doc.sections[0]
    section.top_margin = Inches(0.7)
    section.bottom_margin = Inches(0.7)
    section.left_margin = Inches(0.8)
    section.right_margin = Inches(0.8)

    title = doc.add_heading("LESSON PLAN", level=0)
    title.alignment = 1
    metadata = [
        ("Curriculum", data.get("curriculum", "")),
        ("Subject", data.get("subject", "")),
        ("Grade / Class", data.get("class_name", "")),
        ("Topic", data.get("topic", "")),
        ("Duration", data.get("duration", "")),
    ]
    table = doc.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    for label, value in metadata:
        cells = table.add_row().cells
        cells[0].text = label
        cells[1].text = str(value)
    doc.add_paragraph()

    for line in content.splitlines():
        text = line.strip()
        if not text:
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", text)
        bold_heading = re.match(r"^\*\*(.+)\*\*$", text)
        bullet = re.match(r"^[-*•]\s+(.+)$", text)
        if heading:
            level = min(len(heading.group(1)), 3)
            doc.add_heading(heading.group(2).strip(), level=level)
        elif bold_heading and len(bold_heading.group(1)) < 100:
            doc.add_heading(bold_heading.group(1).strip(), level=2)
        elif bullet:
            doc.add_paragraph(bullet.group(1).strip(), style="List Bullet")
        else:
            doc.add_paragraph(text)

    for paragraph in doc.paragraphs:
        for run in paragraph.runs:
            run.font.name = "Arial"
            run.font.size = Pt(10)

    stream = BytesIO()
    doc.save(stream)
    stream.seek(0)
    topic = re.sub(r"[^A-Za-z0-9_-]+", "-", str(data.get("topic", "lesson-plan"))).strip("-")[:50] or "lesson-plan"
    return send_file(stream, as_attachment=True, download_name=f"{topic}-lesson-plan.docx",
                     mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
