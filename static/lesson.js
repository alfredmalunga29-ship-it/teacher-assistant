(() => {
    const cfg = JSON.parse(document.getElementById("cfg").textContent);
    const $ = (id) => document.getElementById(id);
    const form = $("lesson-form"), preview = $("preview"), body = $("preview-body");
    let plan = null;

    const questionInput = document.getElementById("question_count");
    const stepButtons = document.querySelectorAll(".step-btn");
    const selectedTagsWrap = document.getElementById("selected-tags");
    const questionTypeSelect = document.getElementById("question_type_select");

    if (questionInput) {
        stepButtons.forEach((button) => {
            button.addEventListener("click", () => {
                const current = Number(questionInput.value || 1);
                const step = Number(button.dataset.step || 1);
                const next = Math.min(50, Math.max(1, current + step));
                questionInput.value = next;
            });
        });
    }

    if (selectedTagsWrap && questionTypeSelect) {
        const selectedValues = new Set([
            "Multiple Choice",
            "Structured / Short Answer"
        ]);

        function renderTags() {
            selectedTagsWrap.innerHTML = "";
            selectedValues.forEach((value) => {
                const tag = document.createElement("span");
                tag.className = "selected-tag";
                tag.dataset.value = value;
                const label = document.createTextNode(value);
                const remove = document.createElement("button");
                remove.type = "button";
                remove.setAttribute("aria-label", `Remove ${value}`);
                remove.textContent = "×";
                remove.addEventListener("click", () => {
                    selectedValues.delete(value);
                    renderTags();
                });
                tag.appendChild(label);
                tag.appendChild(remove);
                selectedTagsWrap.appendChild(tag);
            });
        }

        renderTags();

        questionTypeSelect.addEventListener("change", (event) => {
            const value = event.target.value;
            if (!value) return;
            selectedValues.add(value);
            renderTags();
            event.target.value = "";
        });
    }

    // ---- Curriculum choice changes the Class / Grade list ----
    function docTypeLabel() {
        const v = $("document_type").value || "lesson_plan";
        return v.replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
    }

    function fillClasses() {
        const curriculum = $("curriculum");
        const classLabelEl = $("class-label");
        const classNameEl = $("class_name");
        if (!curriculum || !classLabelEl || !classNameEl) return;
        const c = cfg.curricula[curriculum.value];
        classLabelEl.textContent = c.class_label;
        classNameEl.innerHTML = c.classes.map((x) => `<option>${x}</option>`).join("");
    }
    const curriculumElement = $("curriculum");
    if (curriculumElement) {
        curriculumElement.addEventListener("change", () => { fillClasses(); preview.hidden = true; });
        fillClasses();
    }

    function el(tag, attrs = {}, ...kids) {
        const n = document.createElement(tag);
        Object.entries(attrs).forEach(([k, v]) => (k === "class" ? (n.className = v) : n.setAttribute(k, v)));
        kids.forEach((k) => n.append(k));
        return n;
    }
    function grow(t) { t.style.height = "auto"; t.style.height = t.scrollHeight + 2 + "px"; }
    function field(label, value, onInput, multiline = true) {
        const id = "f" + Math.random().toString(36).slice(2, 8);
        const input = multiline ? el("textarea", { id, rows: 1 }) : el("input", { id, type: "text" });
        input.value = value || "";
        input.addEventListener("input", () => { onInput(input.value); if (multiline) grow(input); });
        return [el("label", { for: id }, label), input];
    }

    // ---- Editable preview ----
    function renderPreview() {
        body.innerHTML = "";
        const docType = plan.document_type || "lesson_plan";

        if (docType !== "lesson_plan") {
            const title = el("div", { class: "group" }, el("h2", {}, plan.content.title || (docType.charAt(0).toUpperCase() + docType.slice(1))));
            const pairs = [
                ["Subject", plan.meta.subject || ""],
                ["Class", plan.meta.class_name || ""],
                ["Topic", plan.meta.topic || ""],
                ["Duration", plan.meta.duration || ""],
            ];
            pairs.forEach(([label, value]) => title.append(...field(label, value, () => {}, false)));
            body.append(title);

            const contentBlock = el("div", { class: "group" }, el("h2", {}, "Content"));
            const fields = [
                ["Summary", plan.content.summary || ""],
                ["Main points", plan.content.main_points || ""],
                ["Key terms", plan.content.key_terms || ""],
                ["Instructions", plan.content.instructions || ""],
                ["Questions", plan.content.questions || ""],
                ["Rubric", plan.content.rubric || ""],
                ["Teacher notes", plan.content.teacher_notes || ""],
                ["Marking guide", plan.content.marking_guide || ""],
            ];
            fields.filter(([, value]) => value).forEach(([label, value]) => contentBlock.append(...field(label, value, () => {}, true)));
            body.append(contentBlock);
            preview.hidden = false;
            return;
        }

        const s = cfg.schema[plan.layout];
        const meta = el("div", { class: "group" }, el("h2", {}, "Lesson details"));
        const rows = [
            ["Name of teacher", "teacher"], ["Date", "date"], ["TS Number", "ts_number"],
            ["Topic", "topic"], ["Sub-topic", "subtopic"],
        ];
        if (plan.layout === "old") rows.push(["Boys", "boys"], ["Girls", "girls"], ["Total of pupils", "total"]);
        rows.forEach(([label, key]) => meta.append(...field(label, plan.meta[key], (v) => (plan.meta[key] = v), false)));
        body.append(meta);

        const main = el("div", { class: "group" }, el("h2", {}, "Lesson content"));
        s.fields.forEach(([key, label]) => main.append(...field(label, plan.content[key], (v) => (plan.content[key] = v))));
        body.append(main);

        const prog = el("div", { class: "group" }, el("h2", {}, plan.layout === "cbc" ? "Lesson progression" : "Lesson table"));
        s.stages.forEach(([sk, slabel]) => {
            prog.append(el("h2", { style: "margin-top:18px;font-size:16px;color:#2E7D6B" }, slabel));
            s.stage_keys.forEach(([k, l]) =>
                prog.append(...field(l, plan.content.stages[sk][k], (v) => (plan.content.stages[sk][k] = v))));
        });
        body.append(prog);

        preview.hidden = false;
        body.querySelectorAll("textarea").forEach(grow);
        preview.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    function showError(id, msg) { const e = $(id); e.textContent = msg; e.hidden = !msg; }

    // ---- Generate ----
    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        showError("form-error", "");
        const btn = $("generate-btn");
        btn.disabled = true; btn.textContent = `Generating ${docTypeLabel()}...`;
        try {
            const subjectValue = $("subject").value.trim();
            const topicValue = ($("topic") ? $("topic").value.trim() : "") || ($("topics") ? $("topics").value.trim() : "");
            const durationText = ($("duration_to_complete") ? $("duration_to_complete").value.trim() : "") || "";
            const dueDateValue = ($("due_date") ? $("due_date").value.trim() : "") || "";
            const durationNumber = Number($("duration").value || 80);
            const payload = {
                document_type: $("document_type").value,
                curriculum: $("curriculum").value || "cbc",
                subject: subjectValue,
                class_name: ($("class_name") ? $("class_name").value.trim() : "Form 1") || "Form 1",
                topic: topicValue,
                subtopic: $("subtopic") ? $("subtopic").value.trim() : "",
                duration: Number.isFinite(durationNumber) ? durationNumber : 80,
                detail_level: $("detail_level") ? $("detail_level").value : "Brief overview",
                note_format: $("note_format") ? $("note_format").value : "Bullet points",
                duration_to_complete: durationText,
                due_date: dueDateValue,
            };

            const res = await fetch("/lesson-plan/generate", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || "Something went wrong.");
            plan = data.plan;
            renderPreview();
        } catch (err) {
            showError("form-error", err.message || "Network error. Please try again.");
        } finally {
            btn.disabled = false; btn.textContent = `Generate ${docTypeLabel()}`;
        }
    });

    // ---- Download .docx ----
    $("download-btn").addEventListener("click", async () => {
        showError("download-error", "");
        const btn = $("download-btn");
        btn.disabled = true;
        try {
            if ((plan && plan.document_type) !== "lesson_plan") {
                throw new Error("Word download is available for lesson plans only. The generated notes, assignment, or test can still be reviewed in the preview.");
            }
            const res = await fetch("/lesson-plan/download", {
                method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(plan),
            });
            if (!res.ok) throw new Error((await res.json()).error || "Download failed.");
            const blob = await res.blob();
            const m = /filename="?([^";]+)"?/.exec(res.headers.get("Content-Disposition") || "");
            const a = el("a", { href: URL.createObjectURL(blob), download: m ? m[1] : "Lesson_Plan.docx" });
            document.body.append(a); a.click(); a.remove();
        } catch (err) {
            showError("download-error", err.message);
        } finally {
            btn.disabled = false;
        }
    });
})();
