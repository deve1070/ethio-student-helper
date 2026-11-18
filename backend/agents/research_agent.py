import logging
import time

from langchain.schema import Document
from llm.client import LLMClient
from llm.retry import LLMUnavailableError

logger = logging.getLogger(__name__)

MATH_RULES = r"""- Write mathematics in LaTeX: inline between single dollar signs (for example $A \subseteq B$ or $x^2$) and display equations between double dollar signs ($$ ... $$). Never use \( \) or \[ \] delimiters. Keep ordinary words outside the dollar signs.
            - Never type the | character inside a table or inside math. Write \lvert x \rvert for absolute value and \mid in set-builder notation, for example $\{x \mid x > 0\}$."""


class ResearchAgent:
    def __init__(self):
        """
        Initialize the ResearchAgent with a Groq-backed LLM client.

        max_tokens is generous because the Groq model is a reasoning model:
        hidden reasoning tokens count against this budget, so a small value
        cuts answers short or leaves them empty.
        """
        # 2500: the answer now has a textbook part and an "Explained further" part
        self.model = LLMClient(temperature=0, max_tokens=2500)

    def sanitize_response(self, response_text: str) -> str:
        """
        Sanitize the LLM's response by stripping unnecessary whitespace.
        """
        return response_text.strip()

    def generate_prompt(
        self, question: str, context: str, feedback: str | None = None
    ) -> str:
        """
        Generate a structured prompt for the LLM to generate a precise and factual answer.
        `feedback` is set on a retry: it lists what the verifier rejected in
        the previous draft, so the retry isn't just the same answer again.
        """
        feedback_block = ""
        if feedback:
            feedback_block = (
                "\nYour previous draft was rejected by a fact-checker for these "
                f"reasons:\n{feedback}\n"
                "Write a new answer that corrects or removes every rejected statement.\n"
            )
        return f"""
            You are a patient teacher helping an Ethiopian high-school student understand a topic from their textbook.
            The context below is excerpts from that textbook.

            Write the answer in two parts:
            1. First, answer the question the way the textbook does: its definitions, terms, facts and steps,
               taken from the context. Include as much relevant information from the context as you can.
               National exams test the textbook's wording, so keep its key terms.
            2. Then a section headed "**Explained further**" that helps the student really understand it:
               explain in simpler words, give everyday or Ethiopian examples, analogies, why it matters, and
               related details a teacher would add. Here you may use your own knowledge, but only what is
               correct, at the student's grade level, and consistent with the textbook. Never contradict it.

            - If the context covers only part of the question, answer that part from the textbook and say plainly
              which part the excerpts do not cover; you may still explain that part in "Explained further".
            - Be clear and well organised. Use a short table when comparing two things.
            {MATH_RULES}
            {feedback_block}
            Question:{question}
            Context:{context}
            Provide your answer below

        """

    def generate(
        self, question: str, documents: list[Document], feedback: str | None = None
    ) -> dict:
        """
        Generate an answer using the provided documents.
        """
        context = "\n\n".join([doc.page_content for doc in documents])
        prompt = self.generate_prompt(question, context, feedback)
        started = time.monotonic()
        try:
            response = self.model.chat(messages=[{"role": "user", "content": prompt}])
        except Exception as e:
            logger.warning("Answer model call failed: %s", e)
            raise LLMUnavailableError(
                "Failed to generate answer due to a model error"
            ) from e
        try:
            llm_response = response["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError) as e:
            logger.warning("Unexpected answer model response structure: %s", e)
            llm_response = (
                "I cannot answer this question based on the provided documents."
            )
        draft_answer = (
            self.sanitize_response(llm_response)
            if llm_response
            else "I cannot answer this question based on the provided documents."
        )
        # one line per answer: the answer text itself stays out of the logs
        logger.info(
            "Answer written in %.1fs: %d documents, %d chars of context, %d chars of answer%s",
            time.monotonic() - started, len(documents), len(context), len(draft_answer),
            " (retry after a failed check)" if feedback else "",
        )

        return {"draft_answer": draft_answer, "context_used": context}
