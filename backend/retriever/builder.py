import uuid
from langchain_community.embeddings import FastEmbedEmbeddings
from langchain_community.retrievers import BM25Retriever
from langchain.retrievers import EnsembleRetriever
from config import constants
from config.settings import settings
import logging
from retriever import vectorstore

logger = logging.getLogger(__name__)

# RetrieverBuilder() is constructed at module import time by several routers
# (api/routes_exam.py, api/routes_explain.py, api/routes_notes.py,
# api/routes_esslce.py, exams/cache.py) plus assorted one-off scripts -
# confirmed by grep, ~20 call sites across the project. FastEmbedEmbeddings
# loads real ONNX model weights into memory on construction (measured
# directly: ~280MB), so building a fresh one per call site means paying that
# cost once per call site instead of once per process - on a live app with
# 4+ routers each constructing their own RetrieverBuilder() at import time,
# that is real, measured, redundant RAM (confirmed: the app's import RSS
# dropped further once this was shared, on top of the much larger easyocr
# fix in exams/ocr.py). One process-wide instance, built on first use,
# shared by every RetrieverBuilder() regardless of which module asked first.
_embeddings = None


def _shared_embeddings():
    global _embeddings
    if _embeddings is None:
        _embeddings = FastEmbedEmbeddings(model_name=settings.EMBEDDING_MODEL)
    return _embeddings


class RetrieverBuilder:
    def __init__(self):
        """
        Initialize the retriever builder with local embeddings (fastembed,
        ONNX Runtime - see config/settings.py's EMBEDDING_MODEL comment for
        why this replaced the Gemini embedding API). FastEmbedEmbeddings
        already applies BGE's own asymmetric query/document convention
        internally (query_embed vs embed/passage_embed) - the same
        query-vs-document asymmetry the earlier Gemini wrapper class had to
        implement by hand, here built into the library.
        """
        self.embeddings = _shared_embeddings()

    def build_hybrid_retriever(self, docs):
        """
        Build a session-scoped hybrid retriever from freshly uploaded docs.
        Used by the original docchat ad-hoc upload flow — unchanged.
        """
        try:
            # A fresh collection per call - this is session-scoped debug tooling (app.py's
            # Gradio UI only, never the production path), so uploads from different sessions
            # must never share one collection.
            vector_store = vectorstore.from_documents(
                documents=docs,
                embedding=self.embeddings,
                collection_name=f"upload-{uuid.uuid4()}",
            )
            logger.info("Vector store created successfully.")
            bm25 = BM25Retriever.from_documents(docs)
            vector_retriever = vector_store.as_retriever(
                search_kwargs={"k": settings.VECTOR_SEARCH_K}
            )
            logger.info("BM25 retriever created successfully.")

            hybrid_retriever = EnsembleRetriever(
                retrievers=[bm25, vector_retriever],
                weights=settings.HYBRID_RETRIEVER_WEIGHTS,
            )
            logger.info("Hybrid retriever created successfully.")
            return hybrid_retriever
        except Exception as e:
            logger.error(f"Error building hybrid retriever: {e}")
            raise

    def build_textbook_retriever(self, grade: int, subject: str):
        """
        Build a retriever scoped to one grade + subject against the
        permanent textbook index built by ingestion/textbook_ingest.py.

        Unlike build_hybrid_retriever, this does NOT build a new index —
        it queries the existing persisted vector collection, filtered by
        metadata, so it's cheap to call on every /v1/explain request.
        BM25 is skipped here since it needs the full corpus, not a
        metadata-filtered slice; revisit if vector-only recall proves
        insufficient for a given subject.
        """
        try:
            vector_store = vectorstore.get_vector_store(
                collection_name=constants.TEXTBOOK_COLLECTION_NAME,
                embedding_function=self.embeddings,
            )
            retriever = vector_store.as_retriever(
                search_kwargs={
                    "k": settings.VECTOR_SEARCH_K,
                    "filter": {"$and": [{"grade": grade}, {"subject": subject}]},
                }
            )
            logger.info(
                f"Textbook retriever built for grade={grade}, subject={subject}"
            )
            return retriever
        except Exception as e:
            logger.error(f"Error building textbook retriever: {e}")
            raise
