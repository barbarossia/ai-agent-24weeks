from pathlib import Path

from autonomous_homelab_sre_agent.agents import DiagnosticAnalyst, IndependentSREReviewer
from autonomous_homelab_sre_agent.knowledge import ObsidianRetriever
from autonomous_homelab_sre_agent.scenarios import get_scenario


LAB_ROOT = Path(__file__).parents[1]


def test_diagnosis_requires_a_retrieved_source_fact():
    scenario = get_scenario("proxy-rule-mismatch")
    observations = scenario.baseline

    without_knowledge = DiagnosticAnalyst().analyze(
        case_id=scenario.case_id,
        observations=observations,
        citations=[],
    )
    retrieved = ObsidianRetriever(LAB_ROOT / "vault").retrieve(
        scenario.request, topic_terms=scenario.topic_terms
    )
    with_knowledge = DiagnosticAnalyst().analyze(
        case_id=scenario.case_id,
        observations=observations,
        citations=[item.model_dump(mode="json") for item in retrieved.citations],
    )

    assert without_knowledge.diagnosis.cause_code == "inconclusive"
    assert with_knowledge.diagnosis.cause_code == "route_mismatch"
    assert all(item.source == "knowledge/netflix-routing.md" for item in with_knowledge.diagnosis.citations)


def test_reviewer_rederives_cause_and_rejects_a_forged_handoff():
    scenario = get_scenario("proxy-rule-mismatch")
    retrieved = ObsidianRetriever(LAB_ROOT / "vault").retrieve(
        scenario.request, topic_terms=scenario.topic_terms
    )
    handoff = DiagnosticAnalyst().analyze(
        case_id=scenario.case_id,
        observations=scenario.baseline,
        citations=[item.model_dump(mode="json") for item in retrieved.citations],
    ).model_dump(mode="json")

    assert IndependentSREReviewer().review(handoff).accepted is True

    handoff["diagnosis"]["cause_code"] = "dns_stale_target"
    assert IndependentSREReviewer().review(handoff).accepted is False
