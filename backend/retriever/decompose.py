"""
Retrieval for broad / multi-part questions.

Why this exists: for "What are the trends in the periodic table?" the book has
separate sections on atomic radius, ionization energy, electron affinity and
electronegativity. A single similarity search returns the first two topics
many times over and never reaches the others (the electronegativity statement
ranked 27th, so it never made the top 10). Asking for more chunks or for
"diverse" chunks (MMR) does not help, because the extra slots go to unrelated
exercises. What does work is searching for each part separately.

How it works:
  1. The normal search runs first (it is needed anyway).
  2. If the question looks broad (types, trends, factors, differences, ...),
     one small LLM call reads the question PLUS the first passages found and
     lists the separate topics to search for. Seeing the passages matters: the
     book's own intro sentence names the topics ("Major trends are
     electronegativity, ionization energy, ..."), so the planner uses the
     book's vocabulary instead of guessing.
  3. Each topic is searched on its own; the best few chunks of each are merged
     (de-duplicated) after the best chunks of the original question.
  4. Any failure or "single topic" answer falls back to the plain search, so
     this wrapper can never make a question fail that used to work.

Every request prints one "[planner] ..." line saying what happened.

Usage (api/routes_explain.py):
    from llm.client import LLMClient
    from retriever.decompose import DecomposingRetriever
    _planner_llm = LLMClient(temperature=0, max_tokens=800)   # module level
    ...
    retriever = DecomposingRetriever(retriever, _planner_llm)
"""

import json
import logging
import re

logger = logging.getLogger(__name__)

_BROAD = re.compile(
    r"\b(trends?|types?|kinds?|categories|classes|factors?|causes?|effects?|"
    r"characteristics|properties|features|advantages|disadvantages|steps|stages|"
    r"differences?|differ|compare|comparison|contrast|similarit(?:y|ies)|"
    r"list|various|different|examples|branches|components|functions|uses)\b",
    re.I,
)

_PLANNER_PROMPT = (
    "A student asked a question about a school textbook. The question asks for a "
    "LIST or a COMPARISON, so a good answer covers several separate topics. "
    "Below are the first passages the search found.\n\n"
    "Your task: name the separate topics the answer should cover, as search "
    "queries.\n"
    "Rules:\n"
    "- Give 2 to 6 queries. Each is SHORT (2 to 6 words), for example "
    '"electron affinity trend".\n'
    "- Take the topics from the passages when they list them. A sentence such as "
    '"Major trends are X, Y and Z" gives one query for each of X, Y and Z.\n'
    "- For a comparison of A and B, give one query for A and one for B.\n"
    "- Give a single query only if the question and passages really name just "
    "one topic.\n"
    "Reply with a JSON array of strings only, no other text.\n\n"
    "Question: {question}\n\n"
    "Passages:\n{passages}\n"
)


class DecomposingRetriever:
    def __init__(
        self,
        base,
        llm=None,
        per_query: int = 5,
        original_k: int = 6,
        max_docs: int = 14,
        passages_for_planner: int = 4,
        passage_chars: int = 350,
    ):
        self.base = base
        self.llm = llm
        self.per_query = per_query
        self.original_k = original_k
        self.max_docs = max_docs
        self.passages_for_planner = passages_for_planner
        self.passage_chars = passage_chars
        # The workflow calls invoke() twice for one request (once in
        # full_pipeline, once in the relevance check). Cache so the planner
        # call and the searches happen only once.
        self._cache: dict[str, list] = {}
        self.last_note = ""

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def looks_broad(question: str) -> bool:
        return bool(_BROAD.search(question))

    def plan(self, question: str, docs: list | None = None) -> list[str]:
        """Return the search queries (fewer than 2 means: do not split)."""
        if self.llm is None or not self.looks_broad(question):
            return []
        passages = (
            "\n".join(
                f"- {' '.join(d.page_content.split())[: self.passage_chars]}"
                for d in (docs or [])[: self.passages_for_planner]
            )
            or "(none)"
        )
        raw = ""
        try:
            response = self.llm.chat(
                messages=[
                    {
                        "role": "user",
                        "content": _PLANNER_PROMPT.format(
                            question=question, passages=passages
                        ),
                    }
                ]
            )
            raw = (response["choices"][0]["message"]["content"] or "").strip()
            start, end = raw.find("["), raw.rfind("]")
            queries = json.loads(raw[start : end + 1])
            queries = [q.strip() for q in queries if isinstance(q, str) and q.strip()]
            self.last_note = f"planner reply: {raw[:150]!r}"
            return queries[:6]
        except Exception as e:
            logger.warning("Query planner failed (%s); using the plain search", e)
            self.last_note = f"planner failed: {e}; reply was {raw[:100]!r}"
            return []

    @staticmethod
    def _key(doc) -> str:
        return (getattr(doc, "metadata", None) or {}).get(
            "vector_id"
        ) or doc.page_content

    # -- retriever interface used by the workflow -------------------------
    def invoke(self, question: str, *args, **kwargs):
        if question in self._cache:
            return self._cache[question]

        first = self.base.invoke(question)
        queries = self.plan(question, first)

        # print() rather than logger.info: the server's default log level hides
        # INFO, and this line is the quickest way to see what happened.
        if len(queries) <= 1:
            print(
                f"[planner] plain search (looks_broad={self.looks_broad(question)}, "
                f"llm_configured={self.llm is not None}; {self.last_note or 'not asked'})"
            )
            self._cache[question] = first
            return first

        print(f"[planner] split into {len(queries)} searches: {queries}")
        subs = [self.base.invoke(q)[: self.per_query] for q in queries]

        merged, seen = [], set()
        # Original-question hits first (they matter most), then the
        # sub-queries taken round-robin so every topic gets represented.
        for doc in first[: self.original_k]:
            k = self._key(doc)
            if k not in seen:
                seen.add(k)
                merged.append(doc)
        for rank in range(self.per_query):
            for sub in subs:
                if rank < len(sub):
                    k = self._key(sub[rank])
                    if k not in seen:
                        seen.add(k)
                        merged.append(sub[rank])
        merged = merged[: self.max_docs]
        self._cache[question] = merged
        return merged
