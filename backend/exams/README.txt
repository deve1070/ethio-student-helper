National exam (ESSLCE) bank - separate from the practice questions.

Install: copy the folder  exams/  into backend/  (next to ingestion/, retriever/, db/ ...).
  extraction also needs:  pip install pillow pytesseract opencv-python-headless pypdfium2
                          sudo apt install tesseract-ocr          (only for the OCR cross-check; extraction works without it)

IMPORTANT - table and class names:  everything is called esslce_* / Esslce*.  The project already has an
`exam_questions` table and an `ExamQuestion` class (the exam SOLVER's answer cache in db/models.py). The first draft reused
those names, which makes SQLAlchemy refuse to start ("Table 'exam_questions' is already defined").
If you already ran `create-tables` with the first draft, check the database:  \dt exam_*
  and, if you see exam_papers, exam_passages or exam_topic_links, drop those three (they belong to the first draft):
  DROP TABLE IF EXISTS exam_topic_links, exam_passages, exam_papers;        -- never drop exam_questions / exam_answers

Flow (each step is a command, each can be reviewed before the next):
  python -m exams.cli create-tables
  python -m exams.cli extract "Chemistry 2016 ESSLCE.pdf" --subject chemistry --stream natural_science --year-ec 2016 \
        --first-printed-page 2 --expected 1-80 --vision-model <a model id that accepts images> --out exams_out
  (read exams_out/chemistry_2016_natural_science/review.txt, fix transcript.txt if needed, re-run extract)
  python -m exams.cli load exams_out/chemistry_2016_natural_science     # refuses a paper with missing/duplicate item numbers
  python -m exams.cli key chemistry 2016 --stream natural_science chemistry_2016_key.txt        # a real key only
  python -m exams.cli approve chemistry 2016 --stream natural_science --all-clean               # keyed + no flags
  python -m exams.cli approve chemistry 2016 --stream natural_science --items 5,6,33            # after comparing with the photo
  python -m exams.cli link chemistry 2016 --stream natural_science                              # suggested textbook links
  python -m exams.cli unit chemistry 2016 --stream natural_science --items 5,6 --grade 11 --unit "Unit 3: Acids and Bases"
  python -m exams.cli minutes chemistry 2016 --stream natural_science 90                        # time allowed in a mock exam
  python -m exams.cli index chemistry 2016 --stream natural_science                             # approved -> collection "esslce_exams"
  python -m exams.cli status

What changed from the first draft (all covered by test/test_esslce_pipeline.py):
  - tables/classes renamed to esslce_* (the collision above)
  - a paper with missing / duplicate / out-of-order item numbers is refused at `load` (it used to load, with the problem only in review.txt);
    --allow-incomplete loads it anyway, and `status` then shows complete: False (an incomplete paper cannot be a mock exam)
  - textbook links keep the textbook's UUID (it was only kept when the id was all digits, i.e. never in this project)
  - `link` ranks suggestions by grade for review, but "the best unit" is chosen by distance; `unit` records a person's decision, which `link` never overwrites
  - changing the key of an APPROVED question withdraws its approval; withdrawing an approval removes it from the exam index
  - the exam index embeds the question wording only (year/item are metadata), so a student's own wording can match it
  - lines the model added (not markup) are dropped AND shown in review.txt, so a lost stem is visible
  - subjects are normalised (Information Technology -> information_technology, maths -> mathematics) like the textbooks
  - paper.json records the validation issues; `minutes` stores the mock-exam time

Not built yet: students taking these questions (sessions, answers, mock exams, Telegram), using them in /exam, topic-frequency analytics.
Tables: esslce_papers, esslce_passages, esslce_questions, esslce_topic_links. No foreign key to quiz_questions, textbooks or the exam-solver cache.