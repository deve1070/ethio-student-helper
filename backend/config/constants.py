# Maximum allowed size for a single file (50 MB)
MAX_FILE_SIZE: int = 50 * 1024 * 1024

# Maximum allowed total size for all uploaded files (200 MB)
MAX_TOTAL_SIZE: int = 200 * 1024 * 1024

# Allowed file types for upload
ALLOWED_TYPES: list = [".txt", ".pdf", ".docx", ".md"]

# Ethiopian curriculum: MoE textbooks cover grades 9-12
SUPPORTED_GRADES: list[int] = [9, 10, 11, 12]

# Root folder for raw MoE textbook PDFs, laid out as
# content/moe_textbooks/grade_<N>/<subject>/*.pdf  (not committed to git)
TEXTBOOK_CONTENT_ROOT: str = "content/moe_textbooks"

# Separate Chroma collections so textbook content, the crowdsourced exam-question
# cache, and the ESSLCE past-paper bank can be queried, filtered, and re-indexed independently
TEXTBOOK_COLLECTION_NAME: str = "textbooks"
EXAM_CACHE_COLLECTION_NAME: str = "exam_questions"
EXAM_COLLECTION_NAME: str = "esslce_exams"

# Grade 11-12 stream mapping, confirmed directly by the user (see memory esh_stream_subject_mapping):
# Biology/Chemistry/Physics are natural-science-only, Economics/Geography/History are social-science-only,
# English/SAT/Mathematics are common to both streams (mathematics was stream-split before 2016 EC, but that
# split is a property of individual ESSLCE papers - exams.models.EsslcePaper.stream - not of subject
# selection itself: a student always just picks "mathematics" here regardless of stream).
NATURAL_ONLY_SUBJECTS: set[str] = {"biology", "chemistry", "physics"}
SOCIAL_ONLY_SUBJECTS: set[str] = {"economics", "geography", "history"}
COMMON_SUBJECTS: set[str] = {"english", "scholastic_aptitude_test", "mathematics"}

# Mathematics and Physics content is almost always DERIVED (computed), not stated as a textbook fact -
# quote-verification has nothing to check a computed answer against. Chemistry is mixed ("to some extent"
# calculation, confirmed directly by the user), so it's included too. The Scholastic Aptitude Test's own
# printed structure is the same mix: Section Two "Quantitative Reasoning" (algebra, probability, geometry)
# is computed like a math item, while Section One "Verbal Reasoning" is not - the calculation-path
# generators already fall back to the grounded/plain path for anything that isn't a single computable
# value, so including SAT here costs nothing for its non-computational content.
# Used wherever generated content (an ESSLCE explanation, a Study Note) needs LaTeX math rendering.
CALCULATION_SUBJECTS: set[str] = {"mathematics", "physics", "chemistry", "scholastic_aptitude_test"}

# English textbook units are named after a real-world theme (e.g. "Sustainable Development", "Crime"),
# but that theme is only the VEHICLE for a reading passage or vocabulary list - the unit's actual taught
# content, and what ESSLCE tests, is grammar, vocabulary, and reading/writing skills, not the theme
# itself. A Study Note that summarizes "what the unit is about" the way a biology/history unit's notes
# do ends up describing the passage's subject matter (sustainable development itself) instead of the
# language point the unit teaches - confirmed directly by the user as a real, observed defect, not a
# hypothetical. notes.store.generate_note needs to write a different kind of note for these subjects.
LANGUAGE_SKILL_SUBJECTS: set[str] = {"english"}

# The ESSLCE question bank (exams/store.py) categorizes most subjects by textbook chapter via an
# auto-linker that embeds each question and finds its nearest textbook unit (EsslceTopicLink). For
# English that produces the same theme-vs-content mismatch as LANGUAGE_SKILL_SUBJECTS above (a question
# gets linked to "Unit 1: Sustainable Development" - a reading-passage theme, not a grammar/vocabulary
# skill) - confirmed live: English had 37 such chapter links auto-suggested. The Scholastic Aptitude Test
# has no textbook at all, so nothing links there today, but its own printed structure (Verbal Reasoning,
# Quantitative Reasoning, ...) is sections/skills, not chapters, same as English - excluded here too so
# a future SAT-adjacent textbook never starts linking it by chapter either. best_unit() in exams/store.py
# returns None unconditionally for these subjects; skill_strand() (section/part-based) is their only
# categorization axis for ESSLCE practice.
ESSLCE_SKILL_STRAND_SUBJECTS: set[str] = {"english", "scholastic_aptitude_test"}