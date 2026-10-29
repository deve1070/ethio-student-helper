import logging
import re

from llm.client import LLMClient
from llm.retry import LLMUnavailableError

logger = logging.getLogger(__name__)

_VALID_LABELS = ("CAN_ANSWER", "PARTIAL", "NO_MATCH")


def _parse_label(raw: str) -> str | None:
    """Find a label anywhere in the model output, tolerating quotes, markdown,
    trailing periods, "Label: PARTIAL", "CAN ANSWER", etc."""
    normalized = re.sub(r"[\s\-]+", "_", raw.upper())
    for label in _VALID_LABELS:
        if label in normalized:
            return label
    return None


class RelevanceChecker:
    def __init__(self):
        self.model = LLMClient(temperature=0, max_tokens=256)

    def check(self, question: str, retriever, k=3) -> str:
        """
        1. Retrieve the top k documents chunks from the global retriever.
        2. Combine them into a single text string.
        3. Pass that text + question to the LLM for classification.
        Returns: "CAN_ANSWER", "PARTIAL", "NOT_RELEVANT"

        """
        logger.debug(
            f"RelevanceChecker. check called with question='{question}'and k={k}"
        )
        top_docs = retriever.invoke(question)
        if not top_docs:
            logger.warning(
                "Retriever returned 0 documents for question=%r. Check that "
                "ingestion ran and that grade/subject match the stored metadata.",
                question,
            )
            return "NO_MATCH"
        document_content = "\n\n".join(doc.page_content for doc in top_docs[:k])
        prompt = f"""
                You are AI relevance checker between a user's question and provided document content.

                Instructions:
                -Classify how well the document content addresses the user's question.
                -Respond with only one of the following labels: CAN_ANSWER, PARTIAL, NO_MATCH
                -Do not include any additional text or explanation.

                Lables:
                1) "CAN_ANSWER": The passage contain enough explicit information to fully answer the user's question.        
                2) "PARTIAL" : The passage mention or discuss the question's topic but do not provide all the details needed for a complete answer.
                3) "NO_MATCH": The passage does not discuss or mention the question's topic at all.

                Question: {question}

                Passages:
{document_content}

                Respond ONLY with one of the following labels: CAN_ANSWER, PARTIAL, NO_MATCH
                """
        try:
            response = self.model.chat(
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ]
            )
        except Exception as e:
            logger.exception(f"Relevance-check LLM call failed: {e}")
            raise LLMUnavailableError(str(e)) from e
        try:
            llm_response = response["choices"][0]["message"]["content"].strip().upper()
            logger.debug(f"LLM response: {llm_response}")
        except (IndexError, KeyError) as e:
            logger.error(f"Unexpected response structure:{e}")
            return "NO_MATCH"
        classification = _parse_label(llm_response)
        if classification is None:
            logger.warning(
                "Could not find a valid label in LLM response %r. Forcing NO_MATCH.",
                llm_response,
            )
            return "NO_MATCH"
        logger.info("Relevance classification: %s", classification)
        return classification
