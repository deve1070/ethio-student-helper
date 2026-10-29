"""
Seeds one small fake textbook + a couple of chunks with known content
into both Postgres (for citations) and the "textbooks" vector collection
(for retrieval) — so /v1/explain and /v1/exam/solve can be smoke-tested
end to end before you have real MoE PDFs run through
ingestion/textbook_ingest.py.

Run as: python -m scripts.seed_sample_content
"""

import uuid

from config import constants
from db.models import Chunk, Textbook
from db.session import SessionLocal
from retriever.builder import RetrieverBuilder
from retriever import vectorstore

SAMPLE_CHUNKS = [
    {
        "unit": "Unit 4: Cell Division",
        "section": "4.2 Mitosis",
        "page_start": 110,
        "page_end": 111,
        "text": (
            "Mitosis is a type of cell division that results in two daughter "
            "cells, each having the same number and kind of chromosomes as "
            "the parent nucleus. It is used for growth and repair of tissues."
        ),
    },
    {
        "unit": "Unit 4: Cell Division",
        "section": "4.3 Meiosis",
        "page_start": 112,
        "page_end": 113,
        "text": (
            "Meiosis is a type of cell division that reduces the chromosome "
            "number by half, producing four haploid gametes. Unlike mitosis, "
            "meiosis involves two successive divisions and is used for "
            "sexual reproduction."
        ),
    },
]


def main() -> None:
    db = SessionLocal()
    embeddings = RetrieverBuilder().embeddings
    vector_store = vectorstore.get_vector_store(
        collection_name=constants.TEXTBOOK_COLLECTION_NAME,
        embedding_function=embeddings,
    )

    try:
        textbook = Textbook(
            grade=11, subject="Biology", title="Biology Grade 11 (sample)"
        )
        db.add(textbook)
        db.flush()

        texts, metadatas, ids = [], [], []
        for sample in SAMPLE_CHUNKS:
            vector_id = str(uuid.uuid4())
            db.add(
                Chunk(
                    textbook_id=textbook.id,
                    unit_or_chapter=sample["unit"],
                    section=sample["section"],
                    page_start=sample["page_start"],
                    page_end=sample["page_end"],
                    text_excerpt=sample["text"][:280],
                    vector_id=vector_id,
                )
            )
            texts.append(sample["text"])
            metadatas.append(
                {
                    "vector_id": vector_id,
                    "textbook_id": str(textbook.id),
                    "grade": 11,
                    "subject": "Biology",
                    "unit": sample["unit"],
                    "section": sample["section"],
                }
            )
            ids.append(vector_id)

        vector_store.add_texts(texts=texts, metadatas=metadatas, ids=ids)
        db.commit()
        print(f"Seeded {len(SAMPLE_CHUNKS)} sample chunks for grade 11 Biology.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
