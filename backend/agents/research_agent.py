from langchain.schema import Document

from llm.client import LLMClient
from llm.retry import LLMUnavailableError


# Plain (non-f-string) text so backslashes and braces need no escaping.
# The client renders $...$ / $$...$$ with KaTeX (remark-math + rehype-katex on
# the web). \( \) delimiters are avoided because Markdown treats "\(" as an
# escaped parenthesis and strips the backslash before the math plugin sees it.
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
        print("Initializing ResearchAgent with Groq LLM client...")
        self.model = LLMClient(temperature=0, max_tokens=1500)
        print("LLM client initialized successfully.")

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
                "Write a new answer that removes every rejected statement and "
                "contains only information stated in the context.\n"
            )
        return f"""
            You are an AI assistant that answers school textbook questions using only the given context.

            Instructions:
            - Answer the question using ONLY the provided context.
            - Do NOT add facts, terms, examples or explanations from your own knowledge, even if you know they are true.
            - If the context covers only part of the question, answer that part and say plainly which part the textbook excerpts do not cover.
            - Be clear, concise and factual. Use a short table when comparing two things.
            {MATH_RULES}
            - Include as much relevant information from the context as you can.
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
        print(
            f"ResearchAgent.generate called with question='{question}' and {len(documents)} documents."
            + (" (retry with verifier feedback)" if feedback else "")
        )
        context = "\n\n".join([doc.page_content for doc in documents])
        print(f"Combined context length: {len(context)} characters.")
        prompt = self.generate_prompt(question, context, feedback)
        print("Prompt created for the LLM.")
        try:
            print("Sending prompt to the model...")
            response = self.model.chat(messages=[{"role": "user", "content": prompt}])
            print("LLM response received.")
        except Exception as e:
            print(f"Error during model inference: {e}")
            raise LLMUnavailableError("Failed to generate answer due to a model error") from e
        try:
            llm_response = response["choices"][0]["message"]["content"].strip()
            print(f"Raw LLM response:\n{llm_response}")
        except (KeyError, IndexError) as e:
            print(f"Unexpected response structure: {e}")
            llm_response = (
                "I cannot answer this question based on the provided documents."
            )
        draft_answer = (
            self.sanitize_response(llm_response)
            if llm_response
            else "I cannot answer this question based on the provided documents."
        )
        print(f"Generated answer:{draft_answer}")

        return {"draft_answer": draft_answer, "context_used": context}
