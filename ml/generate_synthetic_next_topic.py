"""Generate and validate the privacy-safe Apogee synthetic next-topic dataset.

The labels in this dataset are authored simulation judgments. They are not user feedback,
human annotations, or empirical ground truth. No production database or API is accessed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


DATASET_VERSION = "apogee-synthetic-next-topic-v1"
FEATURE_SCHEMA_VERSION = "apogee-next-topic-features-v1"
LABEL_RUBRIC_VERSION = "synthetic-next-topic-rubric-v1"
GENERATION_SEED = 20261116
REVIEW_SEED = 20261117
SCENARIOS_PER_FAMILY = 10
EXPECTED_SCENARIOS = 150
EXPECTED_CANDIDATES = 1200
MODEL_FEATURE_FIELDS = (
    "exploration_state", "candidate_topic_id", "candidate_page_count",
    "candidate_visit_count", "candidate_recency_days", "candidate_is_observed",
    "observed_topic_breadth", "total_observed_pages", "total_observed_visits",
    "repeat_visit_ratio", "candidate_page_share", "candidate_visit_share",
    "candidate_prerequisite_count", "observed_prerequisite_count",
    "missing_prerequisite_count", "prerequisite_evidence_level",
    "candidate_is_graph_gap", "candidate_is_direct_extension",
)

TRAIN_FAMILIES = (
    "first_steps_code", "graph_pathfinder", "data_foundations",
    "semantic_search_builder", "cloud_deployment", "privacy_hardening",
    "sparse_returner", "foundation_revisit", "browser_toolmaker",
)
VALIDATION_FAMILIES = (
    "model_practitioner", "web_api_builder", "cross_domain_research",
)
FROZEN_TEST_FAMILIES = (
    "repeated_algorithm_loop", "production_search_ops", "secure_data_platform",
)
SPLIT_FAMILIES = {
    "train": TRAIN_FAMILIES,
    "validation": VALIDATION_FAMILIES,
    "test": FROZEN_TEST_FAMILIES,
}

VARIANT_CONTEXTS = (
    "a weekend prototype with a short feedback cycle",
    "a structured course project with time for fundamentals",
    "a small team handoff where maintainability matters",
    "an offline personal tool with limited infrastructure",
    "a public demonstration where clarity matters",
    "a reliability review after an earlier prototype",
    "a return after several weeks away from the subject",
    "an interdisciplinary experiment with uncertain scope",
    "a constrained deployment with privacy requirements",
    "a reflective study session intended to broaden rather than deepen one area",
)


@dataclass(frozen=True)
class Activity:
    pages: int
    visits: int
    recency_days: int


@dataclass(frozen=True)
class JudgmentProfile:
    strong: tuple[str, ...]
    potential: tuple[str, ...]
    context: str


@dataclass(frozen=True)
class Family:
    family_id: str
    exploration_state: str
    narrative: str
    activity: Mapping[str, Activity]
    profiles: tuple[JudgmentProfile, JudgmentProfile, JudgmentProfile]


def _activity(**items: tuple[int, int, int]) -> dict[str, Activity]:
    return {topic_id.replace("_", "-"): Activity(*values) for topic_id, values in items.items()}


FAMILIES = (
    Family(
        "first_steps_code", "beginner",
        "A fictional beginner is learning to turn small scripts into dependable technical projects.",
        _activity(programming=(2, 3, 4)),
        (
            JudgmentProfile(("algorithms",), ("web-development", "databases", "security-privacy"),
                            "The next step should build problem-solving habits without forcing a deployment stack."),
            JudgmentProfile(("programming", "web-development"), ("algorithms", "databases"),
                            "The learner wants a visible application while reinforcing basic code structure."),
            JudgmentProfile(("programming", "algorithms"), ("web-development", "security-privacy"),
                            "The scenario calls for safer coding fundamentals before adding infrastructure."),
        ),
    ),
    Family(
        "graph_pathfinder", "intermediate",
        "A fictional developer understands graph traversal and wants to apply it in a useful system.",
        _activity(programming=(2, 5, 20), algorithms=(4, 8, 2)),
        (
            JudgmentProfile(("information-retrieval", "databases"), ("web-development", "programming"),
                            "Graph knowledge is being redirected toward search and stored graph-like data."),
            JudgmentProfile(("cloud-systems",), ("security-privacy", "web-development", "databases"),
                            "Operational deployment is more useful than revisiting the formal prerequisite."),
            JudgmentProfile(("machine-learning", "information-retrieval", "algorithms"),
                            ("databases", "security-privacy"),
                            "The goal is an experimental ranking system with privacy constraints."),
        ),
    ),
    Family(
        "data_foundations", "beginner",
        "A fictional learner has started using relational data and needs a coherent next direction.",
        _activity(databases=(3, 5, 3), programming=(1, 1, 14)),
        (
            JudgmentProfile(("databases", "programming"), ("information-retrieval", "web-development"),
                            "Consolidating data and code fundamentals best supports the unfinished project."),
            JudgmentProfile(("information-retrieval",), ("algorithms", "databases", "security-privacy"),
                            "The learner wants to understand how stored records become searchable."),
            JudgmentProfile(("cloud-systems", "web-development", "databases"), ("security-privacy",),
                            "The next task exposes stored data through a small protected interface."),
        ),
    ),
    Family(
        "semantic_search_builder", "interdisciplinary",
        "A fictional builder is prototyping semantic search and must choose among evaluation, data, and product concerns.",
        _activity(information_retrieval=(4, 9, 1), databases=(1, 2, 18), machine_learning=(2, 3, 7)),
        (
            JudgmentProfile(("machine-learning", "algorithms"),
                            ("information-retrieval", "web-development", "security-privacy"),
                            "Evaluation and data handling are more urgent than the sparse database prerequisite signal."),
            JudgmentProfile(("web-development",), ("cloud-systems", "information-retrieval", "security-privacy"),
                            "A usable interface is the immediate goal after the retrieval prototype."),
            JudgmentProfile(("databases", "information-retrieval", "algorithms"), ("machine-learning",),
                            "This variant needs a deeper indexing and ranking foundation."),
        ),
    ),
    Family(
        "model_practitioner", "intermediate",
        "A fictional practitioner has experimented with models and is deciding how to make the work usable and testable.",
        _activity(machine_learning=(4, 7, 2), programming=(2, 3, 9), algorithms=(1, 2, 21)),
        (
            JudgmentProfile(("databases", "information-retrieval"), ("machine-learning", "security-privacy"),
                            "The next need is managing examples and evaluating retrieval-like behavior."),
            JudgmentProfile(("cloud-systems",), ("web-development", "security-privacy", "programming"),
                            "The experiment is ready for a controlled deployment exercise."),
            JudgmentProfile(("machine-learning", "algorithms", "programming"), ("databases",),
                            "The model behavior is unstable, so foundations and reproducibility come first."),
        ),
    ),
    Family(
        "cloud_deployment", "intermediate",
        "A fictional developer has explored managed infrastructure and now needs to make a small service dependable.",
        _activity(cloud_systems=(4, 10, 1), web_development=(2, 4, 6), programming=(1, 2, 30)),
        (
            JudgmentProfile(("security-privacy", "databases"), ("cloud-systems", "web-development"),
                            "Protection and durable state are the largest remaining deployment risks."),
            JudgmentProfile(("programming",), ("algorithms", "cloud-systems", "security-privacy"),
                            "The service code needs simplification before more platform work."),
            JudgmentProfile(("web-development", "cloud-systems", "information-retrieval"), ("databases",),
                            "The fictional product needs an API, hosting, and a search surface."),
        ),
    ),
    Family(
        "web_api_builder", "intermediate",
        "A fictional API builder is deciding whether to deepen the interface, persistence, operations, or safety.",
        _activity(web_development=(4, 8, 1), programming=(3, 5, 5), databases=(2, 3, 12)),
        (
            JudgmentProfile(("security-privacy", "cloud-systems"), ("databases", "web-development"),
                            "The interface exists, so safe operation and deployment now carry the most value."),
            JudgmentProfile(("information-retrieval",), ("databases", "algorithms", "web-development"),
                            "Users need to find records rather than receive another API feature."),
            JudgmentProfile(("programming", "databases", "web-development"), ("security-privacy",),
                            "A redesign of data boundaries and code structure is warranted."),
        ),
    ),
    Family(
        "privacy_hardening", "interdisciplinary",
        "A fictional local application stores personal material and needs a careful privacy-oriented next step.",
        _activity(security_privacy=(3, 6, 2), web_development=(2, 3, 9), databases=(2, 4, 11)),
        (
            JudgmentProfile(("security-privacy", "programming"), ("databases", "web-development"),
                            "Threat modeling and code-level controls should precede feature expansion."),
            JudgmentProfile(("cloud-systems",), ("security-privacy", "databases", "programming"),
                            "The exercise studies private deployment boundaries rather than adding product features."),
            JudgmentProfile(("information-retrieval", "security-privacy", "machine-learning"), ("databases",),
                            "The next question is how semantic processing interacts with sensitive stored text."),
        ),
    ),
    Family(
        "sparse_returner", "sparse_history",
        "A fictional user returns after a long gap with only fragmentary evidence of earlier technical exploration.",
        _activity(programming=(1, 1, 120)),
        (
            JudgmentProfile(("programming",), ("algorithms", "web-development", "databases"),
                            "The sparse record supports a cautious restart with several plausible directions."),
            JudgmentProfile(("security-privacy", "databases"), ("programming", "cloud-systems"),
                            "The new stated goal concerns safe local data, which outweighs the old page trace."),
            JudgmentProfile(("web-development", "information-retrieval", "programming"), ("machine-learning",),
                            "The return is motivated by building a searchable browser tool."),
        ),
    ),
    Family(
        "repeated_algorithm_loop", "repeated_visits",
        "A fictional learner repeatedly revisits algorithm material and wants to escape an unproductive loop.",
        _activity(algorithms=(2, 24, 0), programming=(1, 7, 5)),
        (
            JudgmentProfile(("web-development", "databases"), ("cloud-systems", "information-retrieval"),
                            "Applying the material in a concrete system is more useful than another prerequisite pass."),
            JudgmentProfile(("information-retrieval",), ("machine-learning", "databases", "security-privacy"),
                            "A ranking problem provides a fresh application for graph and complexity ideas."),
            JudgmentProfile(("programming", "machine-learning", "cloud-systems"),
                            ("web-development", "security-privacy"),
                            "This variant needs implementation discipline and a safe deployment challenge."),
        ),
    ),
    Family(
        "foundation_revisit", "returning_to_foundations",
        "A fictional advanced builder deliberately returns to foundational topics after a complex project became brittle.",
        _activity(programming=(2, 3, 90), algorithms=(3, 5, 65), databases=(4, 7, 4),
                  information_retrieval=(5, 11, 1), cloud_systems=(3, 5, 8)),
        (
            JudgmentProfile(("programming", "algorithms"), ("databases", "security-privacy"),
                            "The explicit intent is to repair foundational reasoning despite broad advanced evidence."),
            JudgmentProfile(("databases",), ("programming", "information-retrieval", "algorithms"),
                            "Query and transaction fundamentals caused the recent failure."),
            JudgmentProfile(("security-privacy", "programming", "web-development"), ("cloud-systems",),
                            "The retrospective found unsafe boundaries in application code."),
        ),
    ),
    Family(
        "cross_domain_research", "interdisciplinary",
        "A fictional researcher is connecting software systems, search, and statistical modeling without a single dominant track.",
        _activity(machine_learning=(2, 4, 3), information_retrieval=(2, 4, 4),
                  databases=(2, 3, 10), programming=(2, 3, 18)),
        (
            JudgmentProfile(("algorithms", "machine-learning"),
                            ("security-privacy", "information-retrieval"),
                            "Method design and responsible data use are the strongest cross-cutting needs."),
            JudgmentProfile(("cloud-systems",), ("databases", "web-development", "security-privacy"),
                            "The immediate experiment concerns reproducible infrastructure."),
            JudgmentProfile(("machine-learning", "information-retrieval", "web-development"), ("programming",),
                            "The research question needs a model, retrieval layer, and demonstrable interface."),
        ),
    ),
    Family(
        "production_search_ops", "advanced",
        "A fictional team has a mature search prototype and is choosing the next production-oriented investigation.",
        _activity(information_retrieval=(6, 14, 0), databases=(5, 10, 2), cloud_systems=(4, 8, 3),
                  machine_learning=(3, 5, 7), web_development=(2, 4, 9)),
        (
            JudgmentProfile(("security-privacy", "cloud-systems"), ("databases", "programming"),
                            "Operational safety and resilience dominate another retrieval tutorial."),
            JudgmentProfile(("machine-learning",), ("information-retrieval", "algorithms", "security-privacy"),
                            "The next experiment is an honest ranking evaluation with explicit failure analysis."),
            JudgmentProfile(("web-development", "programming", "databases"), ("cloud-systems",),
                            "The system needs clearer product behavior and maintainable service boundaries."),
        ),
    ),
    Family(
        "secure_data_platform", "advanced",
        "A fictional data platform combines storage and deployment work but has unresolved governance and user-facing needs.",
        _activity(databases=(6, 12, 1), cloud_systems=(5, 9, 2), security_privacy=(3, 5, 6),
                  programming=(3, 4, 16)),
        (
            JudgmentProfile(("security-privacy", "web-development"), ("databases", "cloud-systems"),
                            "Access boundaries and a comprehensible interface are the next useful investments."),
            JudgmentProfile(("information-retrieval",), ("machine-learning", "security-privacy", "databases"),
                            "The fictional users now need governed discovery across stored material."),
            JudgmentProfile(("programming", "algorithms", "security-privacy"), ("cloud-systems",),
                            "A reliability incident calls for simpler code, explicit algorithms, and safer controls."),
        ),
    ),
    Family(
        "browser_toolmaker", "interdisciplinary",
        "A fictional browser-tool maker is balancing interface work, local search, and private data handling.",
        _activity(web_development=(4, 9, 1), programming=(3, 5, 7),
                  information_retrieval=(2, 3, 12), security_privacy=(1, 2, 20)),
        (
            JudgmentProfile(("security-privacy", "information-retrieval"), ("databases", "web-development"),
                            "Private capture and useful recall are the core product risks."),
            JudgmentProfile(("databases",), ("algorithms", "information-retrieval", "programming"),
                            "The next milestone is durable deduplicated local storage."),
            JudgmentProfile(("web-development", "cloud-systems", "security-privacy"), ("programming",),
                            "This variant explores a polished interface and constrained local deployment."),
        ),
    ),
)


def load_taxonomy() -> tuple[str, tuple[Any, ...]]:
    backend = Path(__file__).resolve().parents[1] / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    from app.services.topic_taxonomy import TAXONOMY_VERSION, TOPICS

    return TAXONOMY_VERSION, TOPICS


def split_for_family(family_id: str) -> str:
    matches = [split for split, families in SPLIT_FAMILIES.items() if family_id in families]
    if len(matches) != 1:
        raise ValueError(f"scenario family {family_id!r} must occur in exactly one split")
    return matches[0]


def _varied_activity(base: Mapping[str, Activity], variant: int, rng: random.Random) -> dict[str, dict[str, int | None]]:
    result: dict[str, dict[str, int | None]] = {}
    for topic_id in sorted(base):
        item = base[topic_id]
        page_delta = rng.choice((-1, 0, 0, 0, 1)) if item.pages > 1 else 0
        pages = max(1, item.pages + page_delta)
        visit_delta = rng.choice((-1, 0, 1, 2)) + (variant % 2)
        visits = max(pages, item.visits + visit_delta)
        recency = max(0, item.recency_days + rng.choice((-2, -1, 0, 1, 3)))
        result[topic_id] = {"page_count": pages, "visit_count": visits, "recency_days": recency}
    return result


def _profile_for_variant(family: Family, variant: int) -> JudgmentProfile:
    # Four A, three B, and three C profiles balance strong/potential labels globally.
    return family.profiles[(0, 1, 2, 0, 1, 2, 0, 1, 2, 0)[variant]]


def _label_for(profile: JudgmentProfile, topic_id: str) -> int:
    # Targets are declared contextual judgments. Candidate features are intentionally not inputs.
    if topic_id in profile.strong:
        return 2
    if topic_id in profile.potential:
        return 1
    return 0


def _candidate_row(scenario: Mapping[str, Any], topic: Any, topics: Sequence[Any],
                   profile: JudgmentProfile) -> dict[str, Any]:
    activity = scenario["observed_topic_activity"]
    candidate_activity = activity.get(topic.id, {"page_count": 0, "visit_count": 0, "recency_days": None})
    observed_topics = {topic_id for topic_id, item in activity.items() if item["page_count"] > 0}
    observed_prerequisites = sum(prerequisite in observed_topics for prerequisite in topic.prerequisites)
    dependents = [item.id for item in topics if topic.id in item.prerequisites]
    is_graph_gap = candidate_activity["page_count"] < 2 and any(
        dependent in observed_topics for dependent in dependents
    )
    total_pages = sum(item["page_count"] for item in activity.values())
    total_visits = sum(item["visit_count"] for item in activity.values())
    repeated_visits = max(0, total_visits - total_pages)
    if not topic.prerequisites:
        prerequisite_level = "not_applicable"
    elif observed_prerequisites == 0:
        prerequisite_level = "none"
    elif observed_prerequisites == len(topic.prerequisites):
        prerequisite_level = "complete"
    else:
        prerequisite_level = "partial"
    target = _label_for(profile, topic.id)
    return {
        "dataset_version": DATASET_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "taxonomy_version": scenario["taxonomy_version"],
        "synthetic": True,
        "scenario_id": scenario["scenario_id"],
        "scenario_family": scenario["scenario_family"],
        "split": scenario["split"],
        "exploration_state": scenario["exploration_state"],
        "scenario_narrative": scenario["scenario_narrative"],
        "candidate_topic_id": topic.id,
        "candidate_topic_name": topic.name,
        "candidate_page_count": candidate_activity["page_count"],
        "candidate_visit_count": candidate_activity["visit_count"],
        "candidate_recency_days": candidate_activity["recency_days"],
        "candidate_is_observed": candidate_activity["page_count"] > 0,
        "observed_topic_breadth": len(observed_topics),
        "total_observed_pages": total_pages,
        "total_observed_visits": total_visits,
        "repeat_visit_ratio": round(repeated_visits / total_visits, 6) if total_visits else 0.0,
        "candidate_page_share": round(candidate_activity["page_count"] / total_pages, 6) if total_pages else 0.0,
        "candidate_visit_share": round(candidate_activity["visit_count"] / total_visits, 6) if total_visits else 0.0,
        "candidate_prerequisite_ids": list(topic.prerequisites),
        "candidate_prerequisite_count": len(topic.prerequisites),
        "observed_prerequisite_count": observed_prerequisites,
        "missing_prerequisite_count": len(topic.prerequisites) - observed_prerequisites,
        "prerequisite_evidence_level": prerequisite_level,
        "candidate_is_graph_gap": is_graph_gap,
        "candidate_is_direct_extension": any(item in observed_topics for item in topic.prerequisites),
        "synthetic_usefulness_target": target,
        "synthetic_label_provenance": LABEL_RUBRIC_VERSION,
        "synthetic_label_disclaimer": "Synthetic rubric judgment; not user feedback or empirical ground truth.",
    }


def generate_dataset(seed: int = GENERATION_SEED) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    taxonomy_version, topics = load_taxonomy()
    topic_ids = tuple(topic.id for topic in topics)
    rng = random.Random(seed)
    scenarios: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for family_index, family in enumerate(FAMILIES, start=1):
        for variant in range(SCENARIOS_PER_FAMILY):
            scenario_number = (family_index - 1) * SCENARIOS_PER_FAMILY + variant + 1
            profile = _profile_for_variant(family, variant)
            activity = _varied_activity(family.activity, variant, rng)
            narrative = (
                f"SYNTHETIC scenario {scenario_number:03d}: {family.narrative} "
                f"The setting is {VARIANT_CONTEXTS[variant]}. {profile.context}"
            )
            scenario = {
                "dataset_version": DATASET_VERSION,
                "taxonomy_version": taxonomy_version,
                "synthetic": True,
                "scenario_id": f"syn-scenario-{scenario_number:03d}",
                "scenario_family": family.family_id,
                "family_variant": variant + 1,
                "split": split_for_family(family.family_id),
                "exploration_state": family.exploration_state,
                "scenario_narrative": narrative,
                "observed_topic_activity": {
                    topic_id: activity.get(
                        topic_id, {"page_count": 0, "visit_count": 0, "recency_days": None}
                    )
                    for topic_id in topic_ids
                },
                "synthetic_provenance": "Deterministic fictional scenario generated from declared family templates.",
            }
            scenarios.append(scenario)
            candidates.extend(_candidate_row(scenario, topic, topics, profile) for topic in topics)
    return scenarios, candidates


def _duplicates(values: Iterable[str]) -> set[str]:
    counts = Counter(values)
    return {value for value, count in counts.items() if count > 1}


def _normalized_narrative(value: str) -> str:
    return " ".join(value.casefold().split())


def validate_dataset(scenarios: Sequence[Mapping[str, Any]], candidates: Sequence[Mapping[str, Any]],
                     split_manifests: Mapping[str, Sequence[str]] | None = None) -> dict[str, Any]:
    taxonomy_version, topics = load_taxonomy()
    topic_ids = {topic.id for topic in topics}
    family_ids = {family.family_id for family in FAMILIES}
    errors: list[str] = []
    scenario_ids = [str(row.get("scenario_id", "")) for row in scenarios]
    if len(scenarios) != EXPECTED_SCENARIOS:
        errors.append(f"expected {EXPECTED_SCENARIOS} scenarios, found {len(scenarios)}")
    if len(candidates) != EXPECTED_CANDIDATES:
        errors.append(f"expected {EXPECTED_CANDIDATES} candidates, found {len(candidates)}")
    if duplicates := _duplicates(scenario_ids):
        errors.append(f"duplicate scenario IDs: {sorted(duplicates)}")
    narratives = [_normalized_narrative(str(row.get("scenario_narrative", ""))) for row in scenarios]
    if duplicates := _duplicates(narratives):
        errors.append(f"duplicate scenario narratives: {len(duplicates)}")
    for row in scenarios:
        scenario_id = str(row.get("scenario_id", ""))
        family = str(row.get("scenario_family", ""))
        split = str(row.get("split", ""))
        activity = row.get("observed_topic_activity")
        if (
            row.get("dataset_version") != DATASET_VERSION
            or row.get("taxonomy_version") != taxonomy_version
            or row.get("synthetic") is not True
            or family not in family_ids
            or split_for_family(family) != split
            or not str(row.get("exploration_state", "")).strip()
            or not str(row.get("scenario_narrative", "")).startswith("SYNTHETIC scenario ")
        ):
            errors.append(f"{scenario_id}: invalid scenario metadata")
        if not isinstance(activity, Mapping) or set(activity) != topic_ids:
            errors.append(f"{scenario_id}: activity must cover every taxonomy topic")
            continue
        for topic_id, item in activity.items():
            if not isinstance(item, Mapping):
                errors.append(f"{scenario_id}/{topic_id}: invalid activity record")
                continue
            pages, visits, recency = item.get("page_count"), item.get("visit_count"), item.get("recency_days")
            if (
                not isinstance(pages, int) or isinstance(pages, bool) or pages < 0
                or not isinstance(visits, int) or isinstance(visits, bool) or visits < pages
                or (pages == 0 and recency is not None)
                or (pages > 0 and (not isinstance(recency, int) or isinstance(recency, bool) or recency < 0))
            ):
                errors.append(f"{scenario_id}/{topic_id}: inconsistent pages, visits, or recency")
    by_scenario: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    pairs: list[tuple[str, str]] = []
    for row in candidates:
        scenario_id = str(row.get("scenario_id", ""))
        topic_id = str(row.get("candidate_topic_id", ""))
        by_scenario[scenario_id].append(row)
        pairs.append((scenario_id, topic_id))
        if row.get("dataset_version") != DATASET_VERSION or row.get("synthetic") is not True:
            errors.append(f"{scenario_id}/{topic_id}: invalid dataset version or synthetic marker")
        if row.get("taxonomy_version") != taxonomy_version or topic_id not in topic_ids:
            errors.append(f"{scenario_id}/{topic_id}: invalid taxonomy metadata")
        if row.get("synthetic_usefulness_target") not in (0, 1, 2):
            errors.append(f"{scenario_id}/{topic_id}: target must be 0, 1, or 2")
        if row.get("synthetic_label_provenance") != LABEL_RUBRIC_VERSION:
            errors.append(f"{scenario_id}/{topic_id}: invalid synthetic label provenance")
        required = (
            "scenario_family", "split", "exploration_state", "scenario_narrative",
            "candidate_page_count", "candidate_visit_count", "candidate_is_observed",
            "observed_topic_breadth", "total_observed_pages", "total_observed_visits",
            "repeat_visit_ratio", "candidate_page_share", "candidate_visit_share",
            "candidate_prerequisite_ids", "observed_prerequisite_count",
            "missing_prerequisite_count", "prerequisite_evidence_level",
            "candidate_is_graph_gap", "synthetic_label_provenance",
        )
        if any(row.get(field) is None for field in required):
            errors.append(f"{scenario_id}/{topic_id}: missing required feature")
    if duplicates := _duplicates(f"{scenario_id}|{topic_id}" for scenario_id, topic_id in pairs):
        errors.append(f"duplicate scenario-candidate pairs: {sorted(duplicates)}")
    for scenario_id in scenario_ids:
        rows = by_scenario.get(scenario_id, [])
        if len(rows) != len(topic_ids) or {str(row.get("candidate_topic_id")) for row in rows} != topic_ids:
            errors.append(f"{scenario_id}: candidates must contain every taxonomy topic exactly once")
    orphan_ids = set(by_scenario) - set(scenario_ids)
    if orphan_ids:
        errors.append(f"candidate rows reference unknown scenarios: {sorted(orphan_ids)}")
    scenario_by_id = {str(row["scenario_id"]): row for row in scenarios}
    if {str(row.get("scenario_family")) for row in scenarios} != family_ids:
        errors.append("scenario family coverage differs from declared families")
    if split_manifests is None:
        split_manifests = {
            split: [str(row["scenario_id"]) for row in scenarios if row["split"] == split]
            for split in SPLIT_FAMILIES
        }
    seen_split_ids: list[str] = []
    family_splits: dict[str, set[str]] = defaultdict(set)
    for split, ids in split_manifests.items():
        if split not in SPLIT_FAMILIES:
            errors.append(f"unknown split {split}")
            continue
        for scenario_id in ids:
            seen_split_ids.append(scenario_id)
            scenario = scenario_by_id.get(scenario_id)
            if scenario is None:
                errors.append(f"split {split} references unknown scenario {scenario_id}")
                continue
            if scenario["split"] != split:
                errors.append(f"{scenario_id}: row and manifest splits disagree")
            family_splits[str(scenario["scenario_family"])].add(split)
    if set(seen_split_ids) != set(scenario_ids) or len(seen_split_ids) != len(scenario_ids):
        errors.append("every scenario must occur in exactly one split manifest")
    leaked = {family: sorted(splits) for family, splits in family_splits.items() if len(splits) != 1}
    if leaked:
        errors.append(f"scenario-family leakage: {leaked}")
    test_families = {
        str(scenario_by_id[item]["scenario_family"])
        for item in split_manifests.get("test", []) if item in scenario_by_id
    }
    if test_families != set(FROZEN_TEST_FAMILIES):
        errors.append("test families differ from the frozen test partition")
    labels = Counter(int(row["synthetic_usefulness_target"]) for row in candidates)
    if any(labels[label] / max(len(candidates), 1) < 0.15 for label in (0, 1, 2)):
        errors.append(f"class imbalance exceeds the minimum 15% support rule: {dict(labels)}")
    strong_by_topic = Counter(
        str(row["candidate_topic_id"]) for row in candidates
        if row["synthetic_usefulness_target"] == 2
    )
    if set(strong_by_topic) != topic_ids or max(strong_by_topic.values()) > 2 * min(strong_by_topic.values()):
        errors.append(f"strong-label topic imbalance exceeds 2:1: {dict(strong_by_topic)}")
    if errors:
        raise ValueError("; ".join(errors))
    split_scenario_counts = Counter(str(row["split"]) for row in scenarios)
    split_candidate_counts = Counter(str(row["split"]) for row in candidates)
    split_labels = {
        split: dict(sorted(Counter(
            int(row["synthetic_usefulness_target"]) for row in candidates if row["split"] == split
        ).items()))
        for split in SPLIT_FAMILIES
    }
    graph_gap_rows = [row for row in candidates if row["candidate_is_graph_gap"]]
    graph_gap_disagreements = sum(row["synthetic_usefulness_target"] == 0 for row in graph_gap_rows)
    labels_by_topic = {
        topic_id: {
            str(label): sum(
                row["candidate_topic_id"] == topic_id
                and row["synthetic_usefulness_target"] == label
                for row in candidates
            )
            for label in (0, 1, 2)
        }
        for topic_id in sorted(topic_ids)
    }
    strong_per_scenario = Counter(
        sum(row["synthetic_usefulness_target"] == 2 for row in by_scenario[scenario_id])
        for scenario_id in scenario_ids
    )
    return {
        "dataset_version": DATASET_VERSION,
        "synthetic": True,
        "generation_seed": GENERATION_SEED,
        "scenario_count": len(scenarios),
        "candidate_count": len(candidates),
        "candidate_topics_per_scenario": len(topic_ids),
        "scenario_family_count": len(family_ids),
        "label_distribution": {str(key): value for key, value in sorted(labels.items())},
        "label_distribution_percent": {
            str(key): round(100 * value / len(candidates), 2) for key, value in sorted(labels.items())
        },
        "label_distribution_by_topic": labels_by_topic,
        "strong_label_distribution_by_topic": dict(sorted(strong_by_topic.items())),
        "candidate_coverage_by_topic": dict(sorted(Counter(
            str(row["candidate_topic_id"]) for row in candidates
        ).items())),
        "scenario_family_distribution": dict(sorted(Counter(
            str(row["scenario_family"]) for row in scenarios
        ).items())),
        "exploration_state_distribution": dict(sorted(Counter(
            str(row["exploration_state"]) for row in scenarios
        ).items())),
        "strong_targets_per_scenario_distribution": {
            str(key): value for key, value in sorted(strong_per_scenario.items())
        },
        "split_scenario_counts": dict(sorted(split_scenario_counts.items())),
        "split_candidate_counts": dict(sorted(split_candidate_counts.items())),
        "split_label_distribution": split_labels,
        "split_family_counts": {split: len(families) for split, families in SPLIT_FAMILIES.items()},
        "review_sample_scenario_count": len(FAMILIES) * 2,
        "review_sample_candidate_count": len(FAMILIES) * 2 * len(topic_ids),
        "graph_gap_candidate_count": len(graph_gap_rows),
        "graph_gap_candidates_labelled_not_useful": graph_gap_disagreements,
        "validation_status": "passed",
        "limitations": [
            "All targets are synthetic rubric judgments rather than observed user feedback.",
            "Only 15 scenario families exist; the frozen test split contains three families.",
            "Family holdout measures transfer to these fictional templates, not real-user generalization.",
        ],
    }


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


REVIEW_FIELDS = (
    "dataset_version", "taxonomy_version", "synthetic", "scenario_id", "scenario_family",
    "split", "exploration_state", "scenario_narrative", "candidate_topic_id",
    "candidate_topic_name", "candidate_page_count", "candidate_visit_count",
    "candidate_recency_days", "candidate_is_observed", "candidate_prerequisite_ids",
    "observed_prerequisite_count", "missing_prerequisite_count", "candidate_is_graph_gap",
    "human_usefulness_target", "reviewer_id", "reviewer_notes",
)


def _write_review_files(output_dir: Path, scenarios: Sequence[Mapping[str, Any]],
                        candidates: Sequence[Mapping[str, Any]]) -> None:
    rng = random.Random(REVIEW_SEED)
    sample_ids: list[str] = []
    for family in sorted({str(row["scenario_family"]) for row in scenarios}):
        family_ids = sorted(str(row["scenario_id"]) for row in scenarios if row["scenario_family"] == family)
        sample_ids.extend(sorted(rng.sample(family_ids, 2)))
    rows = [row for row in candidates if row["scenario_id"] in set(sample_ids)]
    with (output_dir / "human-review-sample.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=REVIEW_FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            review = {field: row.get(field, "") for field in REVIEW_FIELDS}
            review["candidate_prerequisite_ids"] = "|".join(row["candidate_prerequisite_ids"])
            review["candidate_recency_days"] = "" if row["candidate_recency_days"] is None else row["candidate_recency_days"]
            review["human_usefulness_target"] = ""
            review["reviewer_id"] = ""
            review["reviewer_notes"] = ""
            writer.writerow(review)
    key_fields = (
        "dataset_version", "scenario_id", "candidate_topic_id", "synthetic_usefulness_target",
        "synthetic_label_provenance", "synthetic_label_disclaimer",
    )
    with (output_dir / "human-review-sample-synthetic-label-key.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=key_fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row[field] for field in key_fields})


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_outputs(output_dir: Path, seed: int = GENERATION_SEED) -> dict[str, Any]:
    if seed != GENERATION_SEED:
        raise ValueError(f"published dataset seed is frozen at {GENERATION_SEED}")
    scenarios, candidates = generate_dataset(seed)
    manifests = {
        split: [row["scenario_id"] for row in scenarios if row["split"] == split]
        for split in SPLIT_FAMILIES
    }
    statistics = validate_dataset(scenarios, candidates, manifests)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_dir / "scenarios.jsonl", scenarios)
    _write_jsonl(output_dir / "candidates.jsonl", candidates)
    for split, scenario_ids in manifests.items():
        _write_json(output_dir / f"split-{split}.json", {
            "dataset_version": DATASET_VERSION,
            "synthetic": True,
            "split": split,
            "generation_seed": seed,
            "scenario_families": list(SPLIT_FAMILIES[split]),
            "scenario_ids": scenario_ids,
            "scenario_count": len(scenario_ids),
            "candidate_count": len(scenario_ids) * 8,
            "frozen_before_training": split == "test",
        })
    _write_review_files(output_dir, scenarios, candidates)
    _write_json(output_dir / "generation-statistics.json", statistics)
    artifact_names = [
        "scenarios.jsonl", "candidates.jsonl", "split-train.json",
        "split-validation.json", "split-test.json", "generation-statistics.json",
        "human-review-sample.csv", "human-review-sample-synthetic-label-key.csv",
    ]
    manifest = {
        "dataset_version": DATASET_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "taxonomy_version": scenarios[0]["taxonomy_version"],
        "label_rubric_version": LABEL_RUBRIC_VERSION,
        "model_feature_fields": list(MODEL_FEATURE_FIELDS),
        "target_field": "synthetic_usefulness_target",
        "group_field": "scenario_id",
        "excluded_metadata_fields": [
            "scenario_id", "scenario_family", "split", "scenario_narrative",
            "candidate_topic_name", "synthetic_label_provenance", "synthetic_label_disclaimer",
        ],
        "synthetic": True,
        "generation_seed": seed,
        "review_sample_seed": REVIEW_SEED,
        "generator": "ml/generate_synthetic_next_topic.py",
        "artifacts": {name: {"sha256": _sha256(output_dir / name)} for name in artifact_names},
    }
    _write_json(output_dir / "dataset-manifest.json", manifest)
    return statistics


def validate_output_dir(output_dir: Path) -> dict[str, Any]:
    scenarios = _read_jsonl(output_dir / "scenarios.jsonl")
    candidates = _read_jsonl(output_dir / "candidates.jsonl")
    split_payloads = {
        split: json.loads((output_dir / f"split-{split}.json").read_text(encoding="utf-8"))
        for split in SPLIT_FAMILIES
    }
    for split, payload in split_payloads.items():
        expected = {
            "dataset_version": DATASET_VERSION,
            "synthetic": True,
            "split": split,
            "generation_seed": GENERATION_SEED,
            "scenario_families": list(SPLIT_FAMILIES[split]),
            "frozen_before_training": split == "test",
        }
        if any(payload.get(field) != value for field, value in expected.items()):
            raise ValueError(f"invalid {split} split manifest metadata")
    manifests = {split: payload["scenario_ids"] for split, payload in split_payloads.items()}
    statistics = validate_dataset(scenarios, candidates, manifests)
    manifest = json.loads((output_dir / "dataset-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("dataset_version") != DATASET_VERSION or manifest.get("synthetic") is not True:
        raise ValueError("invalid dataset manifest")
    if manifest.get("model_feature_fields") != list(MODEL_FEATURE_FIELDS):
        raise ValueError("dataset manifest model feature fields differ from the frozen contract")
    for name, metadata in manifest.get("artifacts", {}).items():
        if _sha256(output_dir / name) != metadata.get("sha256"):
            raise ValueError(f"artifact checksum mismatch: {name}")
    return statistics


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("ml/synthetic-next-topic-v1/data"),
        help="Directory for explicitly synthetic output artifacts.",
    )
    parser.add_argument("--validate", type=Path, help="Validate an existing generated directory.")
    args = parser.parse_args(argv)
    try:
        if args.validate:
            statistics = validate_output_dir(args.validate)
            print(f"valid synthetic candidates: {statistics['candidate_count']}")
        else:
            statistics = write_outputs(args.output_dir)
            print(
                f"generated {statistics['scenario_count']} synthetic scenarios and "
                f"{statistics['candidate_count']} candidate rows"
            )
    except (OSError, ValueError, json.JSONDecodeError, csv.Error) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
