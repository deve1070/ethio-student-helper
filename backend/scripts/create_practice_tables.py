"""Create the quiz tables (safe to run again: existing tables are left alone).
python scripts/create_practice_tables.py      (run from backend/)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.models_practice import Base, QuizAttempt, QuizQuestion, QuizReport
from db.session import engine

Base.metadata.create_all(
    engine, tables=[QuizQuestion.__table__, QuizAttempt.__table__, QuizReport.__table__]
)
print("quiz_questions, quiz_attempts and quiz_reports are ready.")
