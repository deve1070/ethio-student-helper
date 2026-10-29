import logging
from typing import TypedDict

from langchain.schema import Document
from langgraph.graph import END, StateGraph

from .citation_agent import CitationAgent
from .relevance_checker import RelevanceChecker
from .research_agent import ResearchAgent
from .verification_agent import VerificationAgent

logger = logging.getLogger(__name__)


MAX_RESEARCH_ATTEMPTS = 2


class AgentState(TypedDict):
    question: str
    documents: list[Document]
    draft_answer: str
    citations: list[dict]
    verification_report: str
    is_relevant: bool
    retriever: object
    research_attempts: int
    verification_status: str  # "PASS" | "FAIL" | "ERROR" | "" (not run yet)
    verification_feedback: str  # what the verifier rejected, fed to the retry


class AgentWorkflow:
    def __init__(self):
        self.researcher = ResearchAgent()
        self.citation_agent = CitationAgent()
        self.verifier = VerificationAgent()
        self.relevance_checker = RelevanceChecker()
        self.compiled_workflow = self._build_workflow()

    def _build_workflow(self):
        """Create and compile the multi-agent workflow."""
        workflow = StateGraph(AgentState)
        workflow.add_node("check_relevance", self._check_relevance_step)
        workflow.add_node("research", self._research_step)
        workflow.add_node("cite", self._citation_step)
        workflow.add_node("verify", self._verification_step)
        workflow.set_entry_point("check_relevance")
        workflow.add_conditional_edges(
            "check_relevance",
            self._decide_after_relevance_check,
            {
                "relevant": "research",
                "irrelevant": END,
            },
        )
        workflow.add_edge("research", "cite")
        workflow.add_edge("cite", "verify")
        workflow.add_conditional_edges(
            "verify",
            self._decide_after_verification,
            {
                "re_research": "research",
                "end": END,
            },
        )
        return workflow.compile()

    def _check_relevance_step(self, state: AgentState) -> dict:
        retriever = state["retriever"]
        classification = self.relevance_checker.check(
            question=state["question"], retriever=retriever, k=6
        )
        if classification in ("CAN_ANSWER", "PARTIAL"):
            return {"is_relevant": True}
        return {
            "is_relevant": False,
            "draft_answer": (
                "This question isn't related (or there's no data) for your "
                "query. Please ask another question relevant to the "
                "selected grade/subject."
            ),
            "citations": [],
        }

    def _decide_after_relevance_check(self, state: AgentState) -> str:
        decision = "relevant" if state["is_relevant"] else "irrelevant"
        logger.debug(f"_decide_after_relevance_check -> {decision}")
        return decision

    def full_pipeline(self, question: str, retriever) -> dict:
        try:
            logger.debug(f"Starting full_pipeline with question='{question}'")
            documents = retriever.invoke(question)
            logger.info(f"Retrieved {len(documents)} relevant documents")
            initial_state = AgentState(
                question=question,
                documents=documents,
                draft_answer="",
                citations=[],
                verification_report="",
                is_relevant=False,
                retriever=retriever,
                research_attempts=0,
                verification_status="",
                verification_feedback="",
            )
            # NOTE: compiled LangGraph graphs expose .invoke(), not .run() —
            # the original code called a method that doesn't exist on
            # CompiledStateGraph and would have raised at runtime.
            final_state = self.compiled_workflow.invoke(initial_state)
            return {
                "draft_answer": final_state.get("draft_answer"),
                "citations": final_state.get("citations", []),
                "verification_report": final_state.get("verification_report"),
                # False = the textbook has nothing on this question (the "not related" reply);
                # verification_status: "PASS" | "FAIL" | "ERROR" | "" (not run)
                "is_relevant": bool(final_state.get("is_relevant")),
                "verification_status": final_state.get("verification_status", ""),
            }
        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")
            raise

    def _research_step(self, state: AgentState) -> dict:
        attempts = state.get("research_attempts", 0)
        logger.debug(
            f"Entered _research_step (attempt {attempts + 1}) with question='{state['question']}'"
        )
        # NOTE: ResearchAgent's method is `generate`, not `research`.
        result = self.researcher.generate(
            question=state["question"],
            documents=state["documents"],
            feedback=state.get("verification_feedback") or None,
        )
        logger.debug("Researcher returned draft answer.")
        return {
            "draft_answer": result["draft_answer"],
            "research_attempts": attempts + 1,
        }

    def _citation_step(self, state: AgentState) -> dict:
        logger.debug(
            "Entered _citation_step. Resolving citations for retrieved chunks..."
        )
        citations = self.citation_agent.extract(
            state["documents"], answer=state.get("draft_answer")
        )
        logger.debug(f"Resolved {len(citations)} citations.")
        return {"citations": citations}

    def _verification_step(self, state: AgentState) -> dict:
        logger.debug("Entered _verification_step. Verifying the draft answer...")
        result = self.verifier.check(
            state["draft_answer"], state["documents"], question=state["question"]
        )
        status = result["status"]
        problems = result["unsupported_claims"] + result["contradictions"]
        update = {
            "verification_report": result["verification_report"],
            "verification_status": status,
            "verification_feedback": "\n".join(f"- {p}" for p in problems),
        }

        if (
            status == "FAIL"
            and state.get("research_attempts", 0) >= MAX_RESEARCH_ATTEMPTS
        ):
            note = "\n\n> Note: some details in this answer could not be confirmed in the textbook excerpts."
            if problems:
                note += " Unconfirmed: " + "; ".join(problems)
            update["draft_answer"] = state["draft_answer"] + note

        if status == "ERROR":
            update["draft_answer"] = (
                state["draft_answer"]
                + "\n\n> Note: this answer could not be checked against the textbook right now. "
                "Please verify important details in your book."
            )
        return update

    def _decide_after_verification(self, state: AgentState) -> str:
        status = state.get("verification_status", "")
        attempts = state.get("research_attempts", 0)

        if status == "FAIL" and attempts < MAX_RESEARCH_ATTEMPTS:
            logger.info(
                f"Verification failed (attempt {attempts}/{MAX_RESEARCH_ATTEMPTS}); re-researching."
            )
            return "re_research"
        logger.info(
            f"Ending workflow (verification status={status!r}, attempts={attempts})."
        )
        return "end"
