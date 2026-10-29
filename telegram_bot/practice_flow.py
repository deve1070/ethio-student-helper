from dataclasses import dataclass, field

LETTERS = ("A", "B", "C", "D")
BATCH = 5


class FlowError(Exception):
    """A problem to show the student in a pop-up (expired menu, wrong question)."""


@dataclass
class Screen:
    text: str
    buttons: list = field(default_factory=list)  # rows of (label, callback_data)
    image_base64: str | None = None  # set by esslce_flow for a rendered LaTeX explanation; sent as a photo
    image_caption: str | None = None  # self-contained verdict+options, sent as that photo's caption -
    # not reliant on staying next to `text`'s separate message if a slow upload lands out of order


def pretty_subject(subject: str) -> str:
    return subject.replace("_", " ").title()


def clip(text: str, n: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def format_page(citation: dict) -> str:
    parts = [citation.get("textbook"), citation.get("unit")]
    out = ", ".join(p for p in parts if p)
    return out + (f", p.{citation['page']}" if citation.get("page") else "")


class PracticeSession:
    def __init__(self, api, user_id: int, mode: str = "practice"):
        self.api, self.user_id, self.mode = api, user_id, mode
        self.grade = self.subject = None
        self.subjects, self.units = [], []
        self.unit_filter = None  # list of exact unit names, or None for all units
        self.queue, self.current = [], None
        self.answered_ids: set[str] = set()
        self.answered = self.correct = 0

    # ---- entry -----------------------------------------------------------------------------------------------
    def start(self) -> Screen:
        title = (
            "Which grade are you studying?"
            if self.mode == "practice"
            else "Progress: which grade?"
        )
        return Screen(title, [[(f"Grade {g}", f"pg|{g}") for g in (9, 10, 11, 12)]])

    def quick_start(self, grade: int, subject: str) -> Screen:
        """Start straight away on a subject the student practised before (the reminder's button):
        their weak units if they have any, otherwise questions from every unit."""
        self.mode, self.grade, self.subject = "practice", grade, subject
        self.subjects = [
            {"subject": subject, "questions": 0}
        ]  # so the Back buttons still work
        self.units = self.api.practice_units(self.user_id, grade, subject)["units"]
        weak = [u["unit"] for u in self.units if u["level"] == "weak"]
        self.unit_filter = weak or None
        self.queue, self.current = [], None
        self._refill()
        if not self.queue:
            return Screen(
                "There are no new questions in that subject right now. Choose another one:",
                [[("Choose a subject", "pm")]],
            )
        screen = self._question_screen()
        intro = (
            "Starting with your weakest units."
            if weak
            else "A mix of questions from every unit."
        )
        screen.text = f"{intro}\n\n{screen.text}"
        return screen

    def handle(self, data: str):
        """Dispatch one button press. Returns a Screen, or None to ignore (e.g. a double tap)."""
        kind, *rest = data.split("|")
        if kind == "pm":
            return self.start()
        if kind == "pg" and rest:
            return self.on_grade(int(rest[0]))
        if kind == "ps" and rest:
            return self.on_subject(int(rest[0]))
        if kind == "pu" and rest:
            return self.on_unit(rest[0])
        if kind == "pa" and len(rest) == 2:
            return self.on_answer(rest[0], int(rest[1]))
        if kind == "pn":
            return self.on_next()
        if kind == "pr" and rest:
            return self.on_report(rest[0])
        if kind == "px":
            return self.on_stop()
        raise FlowError("This menu has expired. Send /practice to start again.")

    # ---- menus -----------------------------------------------------------------------------------------------
    def on_grade(self, grade: int) -> Screen:
        self.grade = grade
        self.subjects = self.api.practice_subjects(self.user_id, grade)["subjects"]
        if not self.subjects:
            return Screen(
                f"There are no practice questions for Grade {grade} yet.\n"
                "You can still ask the textbook: /explain <grade> <subject> <question>",
                [[("‹ Back", "pm")]],
            )
        rows = [
            [(f"{pretty_subject(s['subject'])} ({s['questions']})", f"ps|{i}")]
            for i, s in enumerate(self.subjects)
        ]
        rows.append([("‹ Back", "pm")])
        return Screen(f"Grade {grade}: choose a subject", rows)

    def on_subject(self, index: int) -> Screen:
        if not 0 <= index < len(self.subjects):
            raise FlowError("This menu has expired. Send /practice to start again.")
        self.subject = self.subjects[index]["subject"]
        if self.mode == "progress":
            return self._progress_screen()
        self.units = self.api.practice_units(self.user_id, self.grade, self.subject)[
            "units"
        ]
        rows = [[("All units", "pu|all")]]
        if any(u["level"] == "weak" for u in self.units):
            rows.append([("🎯 My weak units", "pu|weak")])
        for i, u in enumerate(self.units):
            rows.append([(clip(f"{u['unit']} ({u['questions']})", 56), f"pu|{i}")])
        rows.append([("‹ Back", f"pg|{self.grade}")])
        return Screen(
            f"{pretty_subject(self.subject)}, Grade {self.grade}: which unit?", rows
        )

    def on_unit(self, token: str) -> Screen:
        if token == "all":
            self.unit_filter = None
        elif token == "weak":
            self.unit_filter = [
                u["unit"] for u in self.units if u["level"] == "weak"
            ] or None
        else:
            index = int(token)
            if not 0 <= index < len(self.units):
                raise FlowError("This menu has expired. Send /practice to start again.")
            self.unit_filter = [self.units[index]["unit"]]
        self.queue, self.current = [], None
        self._refill()
        if not self.queue:
            return Screen(
                "There are no questions here yet. Try another unit.",
                [[("‹ Back", f"ps|{self._subject_index()}")]],
            )
        return self._question_screen()

    # ---- the question loop ----------------------------------------------------------------------------------------
    def _subject_index(self) -> int:
        return next(
            (i for i, s in enumerate(self.subjects) if s["subject"] == self.subject), 0
        )

    def _refill(self) -> None:
        res = self.api.practice_next(
            self.user_id, self.grade, self.subject, units=self.unit_filter, count=BATCH
        )
        # never repeat a question inside one session
        self.queue = [q for q in res["questions"] if q["id"] not in self.answered_ids]

    def _header(self, q) -> str:
        return f"{pretty_subject(self.subject)} · Grade {self.grade} · {clip(q.get('unit') or '', 40)} · {q.get('difficulty', '')}"

    def _question_screen(self) -> Screen:
        self.current = q = self.queue.pop(0)
        body = "\n".join(
            f"{L}) {clip(opt, 200)}" for L, opt in zip(LETTERS, q["options"])
        )
        text = f"Question {self.answered + 1}\n{self._header(q)}\n\n{clip(q['question'], 500)}\n\n{body}"
        return Screen(
            text,
            [
                [(L, f"pa|{q['id']}|{i}") for i, L in enumerate(LETTERS)],
                [("⚠ Report this question", f"pr|{q['id']}"), ("■ Stop", "px")],
            ],
        )

    def on_answer(self, question_id: str, chosen: int):
        if question_id in self.answered_ids:
            return None  # double tap
        if not self.current or self.current["id"] != question_id or not 0 <= chosen < 4:
            raise FlowError(
                "That question is no longer active. Send /practice to continue."
            )
        q, res = (
            self.current,
            self.api.practice_answer(self.user_id, question_id, chosen),
        )
        self.answered_ids.add(question_id)
        self.answered += 1
        self.correct += bool(res["is_correct"])
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
        text = (
            f"{verdict}\n\n{clip(q['question'], 500)}\n\n"
            + "\n".join(lines)
            + f"\n\nWhy: {clip(res['explanation'], 600)}\nBook: {format_page(res['citation'])}"
        )
        self.current = None
        return Screen(
            text,
            [
                [("Next question ➡", "pn")],
                [("⚠ Report this question", f"pr|{question_id}"), ("■ Stop", "px")],
            ],
        )

    def on_next(self) -> Screen:
        if not self.queue:
            self._refill()
        if not self.queue:
            return Screen(
                "🎉 You have answered every available question here in this session.\n\n"
                + self._summary(),
                [[("‹ Choose another unit", f"ps|{self._subject_index()}")]],
            )
        return self._question_screen()

    def on_report(self, question_id: str) -> Screen:
        self.api.practice_report(self.user_id, question_id)
        if self.current and self.current["id"] == question_id:
            self.current = None
        self.queue = [q for q in self.queue if q["id"] != question_id]
        return Screen(
            "Thank you. This question has been taken out until a teacher checks it.",
            [[("Next question ➡", "pn"), ("■ Stop", "px")]],
        )

    def _summary(self) -> str:
        if not self.answered:
            return "You haven't answered any questions yet."
        return f"This session: {self.answered} answered, {self.correct} correct ({round(100 * self.correct / self.answered)}%)."

    def on_stop(self) -> Screen:
        self.queue, self.current = [], None
        return Screen(
            "■ Session finished.\n\n"
            + self._summary()
            + "\n\nSend /progress to see your weakest units, or /practice to continue."
        )

    # ---- progress ----------------------------------------------------------------------------------------------------
    def _progress_screen(self) -> Screen:
        p = self.api.practice_progress(self.user_id, self.grade, self.subject)
        head = f"📊 {pretty_subject(self.subject)} · Grade {self.grade}"
        if not p["attempts"]:
            return Screen(
                f"{head}\n\nYou haven't answered any questions yet. Send /practice to start."
            )
        lines = [
            head,
            f"Answered {p['attempts']} · {round(100 * p['accuracy'])}% correct",
            "",
        ]
        if p["weakest_units"]:
            lines.append("Needs work:")
            lines += [f"• {clip(u, 60)}" for u in p["weakest_units"]]
            lines.append("")
        lines.append("By unit:")
        for u in p["units"]:
            lines.append(
                f"{clip(u['unit'], 44)}: {round(100 * u['accuracy'])}% ({u['level']}, {u['attempts']} answered)"
            )
        lines += ["", "Send /practice, then choose “My weak units”."]
        return Screen("\n".join(lines))
