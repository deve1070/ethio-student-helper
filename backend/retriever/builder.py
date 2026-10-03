from langchain_community.vectorstores import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.retrievers import BM25Retriever
from langchain.retrievers import EnsembleRetriever
from config import constants
from config.settings import settings
import logging
from langchain_community.embeddings import HuggingFaceEmbeddings

logger = logging.getLogger(__name__)


class RetrieverBuilder:
    def __init__(self):
        """
        Initialize the retriever builder with embeddings (Gemini's
        text-embedding-004 — Groq doesn't serve embedding models, only
        chat/completion, so embeddings and generation use different
        providers here).
        """
        # self.embeddings = GoogleGenerativeAIEmbeddings(
        #     model=settings.GEMINI_EMBEDDING_MODEL,
        #     google_api_key=settings.GEMINI_API_KEY,
        # )
        self.embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-small-en-v1.5")

    def build_hybrid_retriever(self, docs):
        """
        Build a session-scoped hybrid retriever from freshly uploaded docs.
        Used by the original docchat ad-hoc upload flow — unchanged.
        """
        try:
            # Create Chroma vector store
            vector_store = Chroma.from_documents(
                documents=docs,
                embedding=self.embeddings,
                persist_directory=settings.CHROMA_DB_PATH,
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
        it queries the existing persisted Chroma collection, filtered by
        metadata, so it's cheap to call on every /v1/explain request.
        BM25 is skipped here since it needs the full corpus, not a
        metadata-filtered slice; revisit if vector-only recall proves
        insufficient for a given subject.
        """
        try:
            vector_store = Chroma(
                collection_name=constants.TEXTBOOK_COLLECTION_NAME,
                embedding_function=self.embeddings,
                persist_directory=settings.CHROMA_DB_PATH,
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
