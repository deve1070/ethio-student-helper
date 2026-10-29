
import uuid

from langchain_community.vectorstores import Chroma
from sqlalchemy.orm import Session

from config import constants
from config.settings import settings
from db.models import ExamAnswer, ExamQuestion
from retriever.builder import RetrieverBuilder
from utils.logging import logger


CACHE_DISTANCE_THRESHOLD = 0.15


class ExamCache:
    def __init__(self):
        self.embeddings = RetrieverBuilder().embeddings
        self.vector_store = Chroma(
            collection_name=constants.EXAM_CACHE_COLLECTION_NAME,
            embedding_function=self.embeddings,
            persist_directory=settings.CHROMA_DB_PATH,
        )

    def find_cached_answer(
        self, db: Session, question_text: str, grade: int, subject: str
    ) -> tuple[ExamQuestion, ExamAnswer] | None:
        """Return the closest cached (question, answer) pair if it's a
        confident match, scoped to the same grade + subject. None on miss.
        """
        hits = self.vector_store.similarity_search_with_score(
            question_text,
            k=1,
            filter={"$and": [{"grade": grade}, {"subject": subject}]},
        )
        if not hits:
            return None

        doc, distance = hits[0]
        if distance > CACHE_DISTANCE_THRESHOLD:
            logger.debug(
                f"Closest cached question at distance={distance:.3f}, "
                f"above threshold {CACHE_DISTANCE_THRESHOLD} — treating as a miss"
            )
            return None

        exam_question_id = doc.metadata.get("exam_question_id")
        question = (
            db.get(ExamQuestion, uuid.UUID(exam_question_id))
            if exam_question_id
            else None
        )
        if question is None or not question.answers:
            return None

        answer = sorted(question.answers, key=lambda a: a.created_at)[-1]
        logger.info(
            f"Cache hit for exam question {question.id} (distance={distance:.3f})"
        )
        return question, answer

    def store_new_answer(
        self,
        db: Session,
        question_text: str,
        grade: int,
        subject: str,
        exam_year: int | None,
        answer_text: str,
        citation_chunk_ids: list[uuid.UUID],
    ) -> tuple[ExamQuestion, ExamAnswer]:
        """Persist a freshly generated answer as the new canonical cache
        entry for this question, and index the question text so future
        submissions can find it via similarity search.
        """
        question = ExamQuestion(
            grade=grade,
            subject=subject,
            exam_year=exam_year,
            question_text=question_text,
        )
        db.add(question)
        db.flush()  # assigns question.id before we reference it below

        answer = ExamAnswer(
            exam_question_id=question.id,
            answer_text=answer_text,
            citation_chunk_ids=citation_chunk_ids or None,
            # auto_verified because it passed the workflow's own
            # verification_agent step; a human-review queue on top of
            # this is worth adding before fully trusting the cache
            verification_status="auto_verified",
        )
        db.add(answer)

        self.vector_store.add_texts(
            texts=[question_text],
            metadatas=[
                {
                    "exam_question_id": str(question.id),
                    "grade": grade,
                    "subject": subject,
                }
            ],
            ids=[str(question.id)],
        )
        db.commit()
        logger.info(f"Cached new exam answer for question {question.id}")
        return question, answer

    def bump_times_asked(self, db: Session, question: ExamQuestion) -> None:
        question.times_asked += 1
        db.commit()
