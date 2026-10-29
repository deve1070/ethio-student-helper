"""Grade-12 ESSLCE past-exam practice. Mirrors practice_flow.py's shape (Screen/FlowError, a stateful
session held in context.user_data, a short callback_data prefix dispatched in .handle()) - a DIFFERENT
content type from QuizQuestion practice (see esh-system-boundaries in project memory), so its own flow,
but reusing the plain presentation helpers (Screen, FlowError, clip, pretty_subject) rather than
duplicating them.

The backend endpoint (/v1/esslce/answer) always grades immediately and returns the full result - "practice,
one question at a time" vs "full exam, results only at the end" is decided ENTIRELY here: in exam mode,
on_answer silently records the already-returned grading into exam_results instead of showing it, until the
whole paper is done.
"""

from telegram_bot.practice_flow import FlowError, Screen, clip, pretty_subject

LETTERS = ("A", "B", "C", "D")
BATCH = 5


class EsslceSession:
    def __init__(self, api, user_id: int):
        self.api, self.user_id = api, user_id
        self.mode = None  # "practice" | "exam"
        self.subjects, self.papers = [], []
        self.subject = None
        self.paper_id = None  # set only when scoped to one specific year (exam mode, or practice "pick a year")
        self.paper_year = None
        self.units: list = []
        self.unit = self.unit_grade = None  # set only when scoped to one unit (practice "pick a unit")
        self.skills: list = []
        self.skill = None  # set only when scoped to one skill strand (practice "pick a skill" - English/SAT)
        self.incorrect_only = False  # set only in practice "review my mistakes"
        self._recommendation = None  # the weakest-area suggestion shown by _progress_screen, if any
        self.asking_question_id = None  # set only while mid-conversation in "Ask about this" chat
        self.chat_history: list = []  # [{"role": "user"|"assistant", "content": str}], capped, client-held
        self.queue, self.current = [], None
        self.answered_ids: set[int] = set()
        self.answered = self.correct = 0
        self.exam_results: list[dict] = []  # exam mode only: accumulated grading, revealed at the end

    # ---- entry -----------------------------------------------------------------------------------------------
    def start(self) -> Screen:
        return Screen(
            "ESSLCE Grade 12 practice — how do you want to practice?",
            [
                [("One question at a time", "em|practice")],
                [("Full exam — results at the end", "em|exam")],
                [("📋 Take a Diagnostic Test", "em|diagnostic")],
            ],
        )

    def handle(self, data: str):
        """Dispatch one button press. Returns a Screen, or None to ignore (e.g. a double tap)."""
        kind, *rest = data.split("|")
        if kind == "em" and rest:
            return self.on_mode(rest[0])
        if kind == "es" and rest:
            return self.on_subject(int(rest[0]))
        if kind == "ep" and rest:
            return self.on_paper(int(rest[0]))
        if kind == "epc" and rest:
            return self.on_practice_choice(rest[0])
        if kind == "eu" and rest:
            return self.on_unit(int(rest[0]))
        if kind == "ek" and rest:
            return self.on_skill(int(rest[0]))
        if kind == "er":
            return self.on_recommendation()
        if kind == "ea" and len(rest) == 2:
            return self.on_answer(int(rest[0]), int(rest[1]))
        if kind == "en":
            return self.on_next()
        if kind == "ex":
            return self.on_stop()
        if kind == "ee" and rest:
            return self.on_elaborate(int(rest[0]))
        if kind == "eq" and rest:
            return self.on_ask_start(int(rest[0]))
        raise FlowError("This menu has expired. Send /esslce to start again.")

    # ---- menus -----------------------------------------------------------------------------------------------
    def on_mode(self, mode: str) -> Screen:
        self.mode = mode
        self.paper_id = self.paper_year = None  # a fresh mode choice starts fresh, no stale year carried over
        self.unit = self.unit_grade = None
        self.skill = None
        self.incorrect_only = False
        self._recommendation = None
        self.subjects = self.api.esslce_subjects(self.user_id)["subjects"]
        if not self.subjects:
            return Screen("There are no ESSLCE questions ready for students yet.")
        rows = [
            [(f"{pretty_subject(s['subject'])} ({s['questions']})", f"es|{i}")]
            for i, s in enumerate(self.subjects)
        ]
        return Screen("Choose a subject:", rows)

    def on_subject(self, index: int) -> Screen:
        if not 0 <= index < len(self.subjects):
            raise FlowError("This menu has expired. Send /esslce to start again.")
        self.subject = self.subjects[index]["subject"]
        if self.mode == "practice":
            return Screen(
                f"{pretty_subject(self.subject)}: how do you want to practice?",
                [
                    [("🔀 Mixed, all years", "epc|mixed")],
                    [("📅 Pick a specific year", "epc|year")],
                    [("📚 Pick a unit", "epc|unit")],
                    [("🎯 Pick a skill", "epc|skill")],
                    [("❌ Review my mistakes", "epc|incorrect")],
                    [("📊 My Progress", "epc|progress")],
                    [("‹ Back", "em|practice")],
                ],
            )
        if self.mode == "diagnostic":
            return self._start_diagnostic()
        # exam mode: a full exam is always exactly one specific paper
        return self._papers_screen(back="em|exam")

    def _start_diagnostic(self) -> Screen:
        res = self.api.esslce_diagnostic(self.user_id, self.subject)
        self.queue = res["questions"]
        self.current = None
        self.exam_results = []
        self.answered = self.correct = 0
        if not self.queue:
            return Screen(
                f"No {pretty_subject(self.subject)} questions are ready for a diagnostic yet.",
                [[("‹ Back", "em|diagnostic")]],
            )
        return self._question_screen()

    def on_practice_choice(self, choice: str) -> Screen:
        if choice == "year":
            self.unit = self.unit_grade = None
            self.skill = None
            self.incorrect_only = False
            return self._papers_screen(back="em|practice")
        if choice == "unit":
            self.paper_id = self.paper_year = None
            self.skill = None
            self.incorrect_only = False
            return self._units_screen()
        if choice == "skill":
            self.paper_id = self.paper_year = None
            self.unit = self.unit_grade = None
            self.incorrect_only = False
            return self._skills_screen()
        if choice == "progress":
            self.paper_id = self.paper_year = None
            return self._progress_screen()
        if choice == "incorrect":
            self.paper_id = self.paper_year = None
            self.unit = self.unit_grade = None
            self.skill = None
            self.incorrect_only = True
            self.queue, self.current = [], None
            self._refill()
            if not self.queue:
                return Screen(
                    "No mistakes to review in this subject yet - either you haven't practiced it, or you've "
                    "gotten everything right so far.",
                    [[("‹ Back", "em|practice")]],
                )
            return self._question_screen()
        # "mixed": reset any year/unit/skill/incorrect-only previously chosen (e.g. from an earlier
        # exam-mode or scoped run in this same session) so on_next's empty-queue check doesn't mistake
        # this for a scoped queue
        self.paper_id = self.paper_year = None
        self.unit = self.unit_grade = None
        self.skill = None
        self.incorrect_only = False
        self.queue, self.current = [], None
        self._refill()
        if not self.queue:
            return Screen(
                "There are no new questions in that subject right now.",
                [[("‹ Back", "em|practice")]],
            )
        return self._question_screen()

    def _papers_screen(self, back: str) -> Screen:
        self.papers = self.api.esslce_papers(self.user_id, self.subject)["papers"]
        if not self.papers:
            return Screen(f"No {pretty_subject(self.subject)} papers are ready yet.", [[("‹ Back", back)]])
        rows = [
            [(f"{p['year_ec']} E.C. ({p['ready_for_students']} items)", f"ep|{i}")]
            for i, p in enumerate(self.papers)
        ]
        return Screen(f"{pretty_subject(self.subject)}: choose a year", rows)

    def _units_screen(self) -> Screen:
        self.units = self.api.esslce_units(self.user_id, self.subject)["units"]
        if not self.units:
            return Screen(
                f"No {pretty_subject(self.subject)} questions are tagged to a unit yet.",
                [[("‹ Back", "em|practice")]],
            )
        rows = [
            [(f"Grade {u['grade']} · {clip(u['unit'], 40)} ({u['questions']})", f"eu|{i}")]
            for i, u in enumerate(self.units)
        ]
        return Screen(
            f"{pretty_subject(self.subject)}: choose a unit", rows + [[("‹ Back", "em|practice")]]
        )

    def on_unit(self, index: int) -> Screen:
        if not 0 <= index < len(self.units):
            raise FlowError("This menu has expired. Send /esslce to start again.")
        u = self.units[index]
        self.unit, self.unit_grade = u["unit"], u["grade"]
        self.skill = None
        self.incorrect_only = False
        self.queue, self.current = [], None
        self._refill()
        if not self.queue:
            return Screen(
                "There are no new questions in that unit right now.",
                [[("‹ Back", "em|practice")]],
            )
        return self._question_screen()

    def _skills_screen(self) -> Screen:
        self.skills = self.api.esslce_skills(self.user_id, self.subject)["skills"]
        if not self.skills:
            return Screen(
                f"{pretty_subject(self.subject)} doesn't have skill-based practice available.",
                [[("‹ Back", "em|practice")]],
            )
        rows = [
            [(f"{s['skill']} ({s['questions']})", f"ek|{i}")] for i, s in enumerate(self.skills)
        ]
        return Screen(
            f"{pretty_subject(self.subject)}: choose a skill", rows + [[("‹ Back", "em|practice")]]
        )

    def on_skill(self, index: int) -> Screen:
        if not 0 <= index < len(self.skills):
            raise FlowError("This menu has expired. Send /esslce to start again.")
        self.skill = self.skills[index]["skill"]
        self.unit = self.unit_grade = None
        self.incorrect_only = False
        self.queue, self.current = [], None
        self._refill()
        if not self.queue:
            return Screen(
                "There are no new questions in that skill right now.",
                [[("‹ Back", "em|practice")]],
            )
        return self._question_screen()

    def _progress_screen(self) -> Screen:
        data = self.api.esslce_progress(self.user_id, self.subject)
        self._recommendation = data.get("recommendation")
        lines = [f"📊 {pretty_subject(self.subject)} progress"]
        if not data["attempted"]:
            lines.append("\nYou haven't answered any questions in this subject yet.")
            return Screen("\n".join(lines), [[("‹ Back", "em|practice")]])

        pct = round(100 * data["correct"] / data["attempted"])
        lines.append(f"\nOverall: {data['correct']}/{data['attempted']} correct ({pct}%)")

        weak_units = [u for u in data["units"] if u["attempted"] >= 3][:3]
        if weak_units:
            lines.append("\nWeakest units:")
            for u in weak_units:
                lines.append(
                    f"  {clip(u['unit'], 40)} (Gr.{u['grade']}): "
                    f"{round(100 * u['accuracy'])}% ({u['attempted']} tries)"
                )
        weak_skills = [s for s in data["skills"] if s["attempted"] >= 3][:3]
        if weak_skills:
            lines.append("\nWeakest skills:")
            for s in weak_skills:
                lines.append(
                    f"  {s['skill']}: {round(100 * s['accuracy'])}% ({s['attempted']} tries)"
                )

        rows = []
        rec = self._recommendation
        if rec:
            label = rec["unit"] if rec["kind"] == "unit" else rec["skill"]
            lines.append(f"\n🎯 Recommended focus: {clip(label, 40)} ({round(100 * rec['accuracy'])}%)")
            rows.append([("▶ Practice this now", "er")])
        else:
            lines.append("\nNot enough attempts yet for a confident recommendation - keep practicing!")
        rows.append([("‹ Back", "em|practice")])
        return Screen("\n".join(lines), rows)

    def on_recommendation(self) -> Screen:
        rec = self._recommendation
        if not rec:
            raise FlowError("This menu has expired. Send /esslce to start again.")
        self.paper_id = self.paper_year = None
        self.incorrect_only = False
        if rec["kind"] == "unit":
            self.unit, self.unit_grade = rec["unit"], rec["grade"]
            self.skill = None
        else:
            self.skill = rec["skill"]
            self.unit = self.unit_grade = None
        self.queue, self.current = [], None
        self._refill()
        if not self.queue:
            return Screen(
                "There are no new questions in that area right now.",
                [[("‹ Back", "em|practice")]],
            )
        return self._question_screen()

    def on_paper(self, index: int) -> Screen:
        if not 0 <= index < len(self.papers):
            raise FlowError("This menu has expired. Send /esslce to start again.")
        self.paper_id = self.papers[index]["id"]
        self.paper_year = self.papers[index]["year_ec"]
        self.unit = self.unit_grade = None
        self.skill = None
        self.incorrect_only = False
        self.queue, self.current = [], None
        self.exam_results = []
        self.answered = self.correct = 0
        res = self.api.esslce_next(self.user_id, self.subject, paper_id=self.paper_id)
        self.queue = res["questions"]
        if not self.queue:
            back = "em|exam" if self.mode == "exam" else "em|practice"
            return Screen("This paper has no questions ready yet.", [[("‹ Back", back)]])
        return self._question_screen()

    # ---- the question loop ----------------------------------------------------------------------------------
    def _refill(self) -> None:
        res = self.api.esslce_next(
            self.user_id,
            self.subject,
            unit=self.unit,
            grade=self.unit_grade,
            skill=self.skill,
            incorrect_only=self.incorrect_only,
            count=BATCH,
        )
        # never repeat a question inside one session
        self.queue = [q for q in res["questions"] if q["id"] not in self.answered_ids]

    def _header(self, q) -> str:
        unit = f" · {clip(q.get('unit') or '', 40)}" if q.get("unit") else ""
        return f"{pretty_subject(self.subject)} · Grade 12 · Item {q['item_no']}{unit}"

    def _question_screen(self) -> Screen:
        self.asking_question_id = None  # a new question means any earlier chat context is no longer relevant
        self.current = q = self.queue.pop(0)
        body = "\n".join(f"{L}) {clip(opt, 200)}" for L, opt in zip(LETTERS, q["options"]))
        passage = f"{clip(q['passage_text'], 700)}\n\n" if q.get("passage_text") else ""
        text = f"{self._header(q)}\n\n{passage}{clip(q['stem'], 500)}\n\n{body}"
        # A has_diagram item's stem/options alone are incomplete (they refer to a figure/table the vision
        # model couldn't transcribe as text) - its real source page photo is sent as its own message, same
        # self-contained-caption pattern as _feedback_screen's explanation image (a photo upload can land
        # out of order against a later question's faster text edit).
        image = q.get("diagram_image_base64")
        image_caption = f"{self._header(q)}\n\n{clip(q['stem'], 300)}\n\n{body}" if image else None
        return Screen(
            text,
            [
                [(L, f"ea|{q['id']}|{i}") for i, L in enumerate(LETTERS)],
                [("■ Stop", "ex")],
            ],
            image_base64=image,
            image_caption=image_caption,
        )

    def on_answer(self, question_id: int, chosen: int):
        if question_id in self.answered_ids:
            return None  # double tap
        if not self.current or self.current["id"] != question_id or not 0 <= chosen < 4:
            raise FlowError("That question is no longer active. Send /esslce to continue.")
        q = self.current
        res = self.api.esslce_answer(self.user_id, question_id, chosen, mode=self.mode)
        self.answered_ids.add(question_id)
        self.answered += 1
        self.correct += bool(res["is_correct"])
        self.current = None

        if self.mode in ("exam", "diagnostic"):
            # grading is already computed and durably recorded server-side - just don't show it yet
            self.exam_results.append(
                {"item_no": q["item_no"], "unit": q.get("unit"), "skill": q.get("skill"), **res}
            )
            return self.on_next()

        return self._feedback_screen(q, chosen, res)

    def _feedback_screen(self, q, chosen, res) -> Screen:
        lines = []
        for i, (L, opt) in enumerate(zip(LETTERS, q["options"])):
            mark = (
                "  ✅"
                if i == res["correct_index"]
                else ("  ❌ (your answer)" if i == chosen else "")
            )
            lines.append(f"{L}) {clip(opt, 200)}{mark}")
        verdict = (
            "✅ Correct!"
            if res["is_correct"]
            else f"❌ Not quite. The correct answer is {LETTERS[res['correct_index']]}."
        )
        options_block = "\n".join(lines)
        text = f"{verdict}\n\n{clip(q['stem'], 500)}\n\n{options_block}"
        image = res.get("explanation_image_base64")
        if not image and res.get("explanation"):
            text += f"\n\nWhy: {clip(res['explanation'], 600)}"
        elif res.get("supporting_quote"):
            text += f"\n\nWhy: {clip(res['explanation'] or '', 400)}\nTextbook: “{clip(res['supporting_quote'], 200)}”"
        # When there's an image, it's sent as ITS OWN message (Telegram can't attach a photo to an
        # edited text message) - a slow photo upload can finish later than a fast text edit for a
        # following question, so the caption repeats verdict+options here. That way each message is
        # self-contained and still makes sense on its own however the two end up ordered in the chat,
        # instead of relying on the image staying next to a separate text message that explains it.
        image_caption = None
        if image:
            short_lines = [
                f"{L}) {clip(opt, 100)}" + ("  ✅" if i == res["correct_index"] else "")
                for i, (L, opt) in enumerate(zip(LETTERS, q["options"]))
            ]
            image_caption = f"{verdict}\n\n{clip(q['stem'], 300)}\n\n" + "\n".join(short_lines)
        return Screen(
            text,
            [
                [("🔍 Explain more", f"ee|{q['id']}")],
                [("💬 Ask about this", f"eq|{q['id']}")],
                [("Next question ➡", "en")],
                [("■ Stop", "ex")],
            ],
            image_base64=image,
            image_caption=image_caption,
        )

    @staticmethod
    def _citation_line(citation: dict | None) -> str:
        """Built entirely from fields the backend resolved from the Chunk/Textbook rows - never from the
        LLM's own words, so a page number here is never something the model could have invented."""
        if not citation:
            return ""
        parts = [
            citation["textbook"],
            f"Grade {citation['grade']}",
            citation.get("unit_or_chapter"),
            citation.get("section"),
        ]
        if citation.get("page_start"):
            page = f"p.{citation['page_start']}"
            if citation.get("page_end") and citation["page_end"] != citation["page_start"]:
                page += f"-{citation['page_end']}"
            parts.append(page)
        return "\U0001f4d6 " + ", ".join(p for p in parts if p)

    def on_elaborate(self, question_id: int) -> Screen:
        """"I still don't get it" - a deeper, on-demand explanation (cached server-side per question, so
        this can be slow the first time anyone asks and instant for everyone after)."""
        res = self.api.esslce_elaborate(self.user_id, question_id)
        image = res.get("content_image_base64")
        citation_line = self._citation_line(res.get("citation"))
        if image:
            text = "🔍 Here's a similar worked example:"
        else:
            text = f"🔍 More detail:\n\n{clip(res['content'], 1500)}"
            if citation_line:
                text += f"\n\n{citation_line}"
        return Screen(
            text,
            [
                [("💬 Ask about this", f"eq|{question_id}")],
                [("Next question ➡", "en")],
                [("■ Stop", "ex")],
            ],
            image_base64=image,
            image_caption="🔍 Worked example" if image else None,
        )

    def on_ask_start(self, question_id: int) -> Screen:
        self.asking_question_id = question_id
        self.chat_history = []
        return Screen(
            "💬 Ask me anything about this question - just type your message.",
            [[("Next question ➡", "en")], [("■ Stop", "ex")]],
        )

    def on_chat_message(self, text: str) -> Screen:
        """Called by the bot's free-text message handler, only while self.asking_question_id is set -
        NEVER cached (unlike on_elaborate), so every message here is a fresh, uncached LLM call."""
        res = self.api.esslce_ask(self.user_id, self.asking_question_id, text, self.chat_history)
        reply = res["reply"]
        self.chat_history.append({"role": "user", "content": text})
        self.chat_history.append({"role": "assistant", "content": reply})
        self.chat_history = self.chat_history[-12:]  # cap what's resent next turn - cost control
        return Screen(
            f"\U0001f4ac {clip(reply, 1500)}",
            [[("Next question ➡", "en")], [("■ Stop", "ex")]],
        )

    def on_next(self) -> Screen:
        if not self.queue:
            if self.mode == "exam":
                return self._exam_summary_screen()
            if self.mode == "diagnostic":
                # a fixed, one-shot set fetched all at once - never refill from the mixed pool
                return self._diagnostic_summary_screen()
            if self.paper_id is not None:
                # a specific year was chosen (not the mixed pool) - on_paper already fetched every
                # eligible item of that one paper at once, so an empty queue means that whole paper is
                # done, not "try refilling from somewhere else"
                return Screen(
                    f"\U0001f389 You've finished every question in the {self.paper_year} E.C. paper.\n\n"
                    + self._summary(),
                    [[("‹ Choose another subject", "em|practice")]],
                )
            self._refill()
        if not self.queue:
            return Screen(
                "\U0001f389 You've answered every available question here.\n\n" + self._summary(),
                [[("‹ Choose another subject", "em|practice")]],
            )
        return self._question_screen()

    def _summary(self) -> str:
        if not self.answered:
            return "You haven't answered any questions yet."
        return f"This session: {self.answered} answered, {self.correct} correct ({round(100 * self.correct / self.answered)}%)."

    def _exam_summary_screen(self) -> Screen:
        res = self.api.esslce_exam_summary(self.user_id, self.paper_id)
        pct = round(100 * res["correct"] / res["total_eligible"]) if res["total_eligible"] else 0
        lines = [
            f"\U0001f4cb Exam finished: {res['correct']}/{res['total_eligible']} correct ({pct}%)",
            "",
        ]
        for r in res["results"]:
            mark = "✅" if r["is_correct"] else "❌"
            lines.append(f"{mark} Item {r['item_no']}")
        return Screen("\n".join(lines), [[("‹ Choose another subject", "em|exam")]])

    def _diagnostic_summary_screen(self) -> Screen:
        """Deliberately does NOT claim a 'weakest unit/skill' the way _progress_screen's recommendation
        does - a diagnostic spreads thin across many topics (often just 1 item per unit/skill), and
        recommend_focus's own MIN_ATTEMPTS_FOR_SIGNAL exists precisely because one question is never
        enough to call a topic weak. Shows the honest per-item breakdown instead, and lets the student
        choose where to practice next themselves."""
        total = len(self.exam_results)
        correct = sum(1 for r in self.exam_results if r["is_correct"])
        pct = round(100 * correct / total) if total else 0
        lines = [
            f"\U0001f4cb Diagnostic finished: {correct}/{total} correct ({pct}%)",
            "",
            f"This is a quick baseline from {total} questions spread across different topics - not a "
            "prediction of your real exam score.",
            "",
        ]
        for r in self.exam_results:
            mark = "✅" if r["is_correct"] else "❌"
            topic = r.get("unit") or r.get("skill") or ""
            topic_part = f" · {clip(topic, 30)}" if topic else ""
            lines.append(f"{mark} Item {r['item_no']}{topic_part}")
        lines.append("")
        lines.append("Keep practicing to build a fuller picture of your strengths and weaknesses.")
        return Screen(
            "\n".join(lines),
            [[("Start practicing", "em|practice")], [("‹ Choose another subject", "em|diagnostic")]],
        )

    def on_stop(self) -> Screen:
        self.queue, self.current = [], None
        if self.mode == "exam" and self.exam_results:
            return self._exam_summary_screen()
        if self.mode == "diagnostic" and self.exam_results:
            return self._diagnostic_summary_screen()
        return Screen(
            "■ Session finished.\n\n" + self._summary() + "\n\nSend /esslce to continue."
        )
