import json
import logging

from langchain.schema import Document

from llm.gemini_client import GeminiLLMClient
from llm.gemini_rest import GeminiRequestError
from llm.retry import LLMUnavailableError

logger = logging.getLogger(__name__)


def _as_bool(value) -> bool:
    """Models sometimes return "yes"/"true" strings instead of JSON booleans."""
    if isinstance(value, bool):
        return value
    return str(value).strip().strip("*").upper() in {"TRUE", "YES", "Y", "1"}


def _as_list(value) -> list[str]:
    if not value or (
        isinstance(value, str) and value.strip().lower() in {"none", "n/a", ""}
    ):
        return []
    if isinstance(value, str):
        return [value.strip()]
    return [str(v).strip() for v in value if str(v).strip()]


class VerificationAgent:
    def __init__(self):
        """
        Fact-checks a draft answer against the retrieved textbook chunks.

        Deliberately a DIFFERENT model than the one that drafted the answer
        (ResearchAgent, llm/client.py's Groq-backed LLMClient): a verifier
        from the same model family as the author tends to share its blind
        spots, so this is Gemini (llm/gemini_client.py) - the same
        cross-model cross-check this project now applies to exam-answer
        resolution (exams/store.py's solve_question_crosschecked).
        """
        logger.info("Initializing VerificationAgent with a Gemini LLM client...")
        # A small time budget: the student is waiting, and the answer is already written. If Gemini
        # is overloaded the check is skipped (status ERROR) and the answer is sent as it is.
        # 4000: Gemini's hidden thinking shares this limit, and a long answer has many claims to check;
        # at 1000 the reply was cut off mid-JSON
        self.model = GeminiLLMClient(temperature=0, max_tokens=4000, timeout=25, retry_attempts=1)

    def generate_prompt(self, answer: str, context: str, question: str | None) -> str:
        question_block = f"QUESTION:\n{question}\n\n" if question else ""
        return (
            "You are a careful fact-checker for a school study tool. The ANSWER "
            "explains a topic to a high-school student. Its first part should follow "
            "the CONTEXT (excerpts from the student's textbook); its 'Explained "
            "further' part may add examples and detail beyond the textbook.\n\n"
            "Rules:\n"
            "- Split the ANSWER into individual factual claims and check each one.\n"
            "- A claim that conflicts with the CONTEXT is a contradiction.\n"
            "- A claim that is factually wrong is incorrect. Judge claims the "
            "CONTEXT does not mention with your own knowledge. A correct claim is "
            "fine even if the CONTEXT never mentions it, so do not report it.\n"
            '- "relevant" is true only if the ANSWER actually addresses the '
            "QUESTION.\n"
            "- Quote or closely paraphrase each contradiction and incorrect claim "
            "so it can be fixed.\n\n"
            "Return ONLY one JSON object, with no markdown fences and no other "
            "text, in exactly this shape:\n"
            '{"contradictions": [], "incorrect_claims": [], "relevant": true, '
            '"notes": "one short sentence"}\n\n'
            f"{question_block}"
            f"ANSWER:\n{answer}\n\n"
            f"CONTEXT:\n{context}\n"
        )

    @staticmethod
    def parse_verification_response(response_text: str) -> dict | None:
        """Extract the JSON object from the model's reply. None if unusable."""
        start, end = response_text.find("{"), response_text.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            data = json.loads(response_text[start : end + 1])
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict) or not ({"contradictions", "incorrect_claims"} & data.keys()):
            return None
        return {
            "incorrect_claims": _as_list(data.get("incorrect_claims")),
            "contradictions": _as_list(data.get("contradictions")),
            "relevant": _as_bool(data.get("relevant", True)),
            "notes": str(data.get("notes", "")).strip(),
        }

    @staticmethod
    def format_verification_report(v: dict) -> str:
        # Plain lines (no markdown bold) so the report is easy to read in logs and to search.
        return (
            f"Incorrect Claims: {'; '.join(v['incorrect_claims']) or 'None'}\n"
            f"Contradictions: {'; '.join(v['contradictions']) or 'None'}\n"
            f"Relevant: {'YES' if v['relevant'] else 'NO'}\n"
            f"Additional Details: {v['notes'] or 'None'}\n"
        )

    def check(
        self, answer: str, documents: list[Document], question: str | None = None
    ) -> dict:
        """
        Returns:
          verification_report  human-readable text
          status               "PASS" | "FAIL" | "ERROR"
                               FAIL  = the verifier found problems with the answer
                               ERROR = the verifier itself failed (model error,
                                       empty or unparseable reply); says nothing
                                       about the answer, so callers shouldn't
                                       treat it as a failed answer.
          incorrect_claims, contradictions
          context_used
        """
        context = "\n\n".join(doc.page_content for doc in documents)
        prompt = self.generate_prompt(answer, context, question)
        logger.info(
            "VerificationAgent.check: %d documents, %d chars of context",
            len(documents),
            len(context),
        )

        def error_result(reason: str) -> dict:
            logger.warning("Verification could not be completed: %s", reason)
            return {
                "verification_report": f"Verification unavailable: {reason}",
                "status": "ERROR",
                "incorrect_claims": [],
                "contradictions": [],
                "context_used": context,
            }

        try:
            response = self.model.chat(messages=[{"role": "user", "content": prompt}])
            raw = response["choices"][0]["message"]["content"].strip()
        except (LLMUnavailableError, GeminiRequestError) as e:
            # an outage or a configuration problem, not a bug: one warning line, no traceback
            return error_result(f"model error ({str(e)[:300]})")
        except Exception as e:
            logger.exception("Verifier model call failed")
            return error_result(f"model error ({e})")

        logger.debug("Raw verifier response: %s", raw)
        if not raw:
            return error_result("the model returned an empty reply (raise max_tokens?)")

        parsed = self.parse_verification_response(raw)
        if parsed is None:
            return error_result("the reply was not valid JSON")

        passed = parsed["relevant"] and not parsed["incorrect_claims"] and not parsed["contradictions"]
        report = self.format_verification_report(parsed)
        logger.info("Verification %s | %s", "PASS" if passed else "FAIL", report.strip().replace("\n", " | "))
        return {
            "verification_report": report,
            "status": "PASS" if passed else "FAIL",
            "incorrect_claims": parsed["incorrect_claims"],
            "contradictions": parsed["contradictions"],
            "context_used": context,
        }
