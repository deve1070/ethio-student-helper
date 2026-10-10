import json
import logging

from langchain.schema import Document

from llm.client import LLMClient

logger = logging.getLogger(__name__)


def _as_bool(value) -> bool:
    """Models sometimes return "yes"/"true" strings instead of JSON booleans."""
    if isinstance(value, bool):
        return value
    return str(value).strip().strip("*").upper() in {"TRUE", "YES", "Y", "1"}


def _as_list(value) -> list[str]:
    if not value or (isinstance(value, str) and value.strip().lower() in {"none", "n/a", ""}):
        return []
    if isinstance(value, str):
        return [value.strip()]
    return [str(v).strip() for v in value if str(v).strip()]


class VerificationAgent:
    def __init__(self):
        """
        Fact-checks a draft answer against the retrieved textbook chunks.

        max_tokens is generous on purpose: the Groq model is a reasoning
        model and its hidden reasoning counts against this budget. A small
        value produces an empty reply, which used to be treated as a failed
        verification.
        """
        logger.info("Initializing VerificationAgent with Groq LLM client...")
        self.model = LLMClient(temperature=0, max_tokens=1000)

    def generate_prompt(self, answer: str, context: str, question: str | None) -> str:
        question_block = f"QUESTION:\n{question}\n\n" if question else ""
        return (
            "You are a strict fact-checker for a school study tool. Decide whether "
            "the ANSWER is fully supported by the CONTEXT, which is a set of "
            "excerpts from a textbook.\n\n"
            "Rules:\n"
            "- Split the ANSWER into individual factual claims and check each one.\n"
            "- A claim is supported only if the CONTEXT states it, or it follows "
            "directly from what the CONTEXT states.\n"
            "- Do NOT use your own knowledge. A claim that is true in the real "
            "world but is not in the CONTEXT is UNSUPPORTED. Extra terms, "
            "examples, numbers and mechanisms that the CONTEXT never mentions "
            "are unsupported.\n"
            "- A claim that conflicts with the CONTEXT is a contradiction.\n"
            '- "supported" is true only if there are no unsupported claims and '
            "no contradictions.\n"
            '- "relevant" is true only if the ANSWER actually addresses the '
            "QUESTION.\n"
            "- Quote or closely paraphrase each unsupported claim so it can be "
            "removed.\n\n"
            "Return ONLY one JSON object, with no markdown fences and no other "
            "text, in exactly this shape:\n"
            '{"supported": true, "unsupported_claims": [], "contradictions": [], '
            '"relevant": true, "notes": "one short sentence"}\n\n'
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
        if not isinstance(data, dict) or "supported" not in data:
            return None
        return {
            "supported": _as_bool(data.get("supported")),
            "unsupported_claims": _as_list(data.get("unsupported_claims")),
            "contradictions": _as_list(data.get("contradictions")),
            "relevant": _as_bool(data.get("relevant", True)),
            "notes": str(data.get("notes", "")).strip(),
        }

    @staticmethod
    def format_verification_report(v: dict) -> str:
        # Plain "Supported: YES/NO" lines (no markdown bold) so the report is
        # easy to read in logs and to search.
        return (
            f"Supported: {'YES' if v['supported'] else 'NO'}\n"
            f"Unsupported Claims: {'; '.join(v['unsupported_claims']) or 'None'}\n"
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
          unsupported_claims, contradictions
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
                "unsupported_claims": [],
                "contradictions": [],
                "context_used": context,
            }

        try:
            response = self.model.chat(messages=[{"role": "user", "content": prompt}])
            raw = response["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.exception("Verifier model call failed")
            return error_result(f"model error ({e})")

        logger.debug("Raw verifier response: %s", raw)
        if not raw:
            return error_result("the model returned an empty reply (raise max_tokens?)")

        parsed = self.parse_verification_response(raw)
        if parsed is None:
            return error_result("the reply was not valid JSON")

        # Don't trust the boolean alone: a "supported: true" that still lists
        # unsupported claims or contradictions is a fail.
        passed = (
            parsed["supported"]
            and parsed["relevant"]
            and not parsed["unsupported_claims"]
            and not parsed["contradictions"]
        )
        report = self.format_verification_report(parsed)
        logger.info("Verification %s\n%s", "PASS" if passed else "FAIL", report)
        return {
            "verification_report": report,
            "status": "PASS" if passed else "FAIL",
            "unsupported_claims": parsed["unsupported_claims"],
            "contradictions": parsed["contradictions"],
            "context_used": context,
        }
