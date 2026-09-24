from collections.abc import Iterable, Mapping

from knowledge_gap_agent.benchmark.models import KnowledgeEnvironment, ValidationIssue
from knowledge_gap_agent.contracts.benchmark import BenchmarkCase
from knowledge_gap_agent.corpus.models import Claim, CorpusChunk
from knowledge_gap_agent.utils.canonical import canonical_json


LABEL_FIELDS = frozenset({
    "schema_version", "category", "local_knowledge_ids", "answer_key", "required_claims",
    "required_claim_ids", "missing_claim_ids", "evidence_chunk_ids", "annotation_reason",
    "allowed_source_ids", "need_research", "draft_status", "review_status",
    "human_review_status",
})


def _issue(code: str, case_id: str, message: str, *refs: str) -> ValidationIssue:
    return ValidationIssue(code=code, case_id=case_id, message=message, refs=refs)


def _sorted_issues(issues: Iterable[ValidationIssue]) -> tuple[ValidationIssue, ...]:
    return tuple(sorted(issues, key=lambda issue: (
        issue.case_id or "", issue.code, issue.refs, issue.message,
    )))


def validate_case(
    case: BenchmarkCase,
    environment: KnowledgeEnvironment,
    chunks_by_id: Mapping[str, CorpusChunk],
    claims_by_id: Mapping[str, Claim],
) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []
    if case.environment_id != environment.environment_id:
        issues.append(_issue("environment_id_mismatch", case.case_id,
                             "case environment does not match supplied environment",
                             case.environment_id, environment.environment_id))

    referenced_chunks = set(environment.visible_chunk_ids + environment.research_chunk_ids
                            + environment.excluded_chunk_ids + case.evidence_chunk_ids)
    for chunk_id in sorted(referenced_chunks - chunks_by_id.keys()):
        issues.append(_issue("chunk_not_found", case.case_id,
                             "referenced chunk does not exist", chunk_id))
    for claim_id in sorted(set(case.required_claim_ids) - claims_by_id.keys()):
        issues.append(_issue("claim_not_found", case.case_id,
                             "referenced claim does not exist", claim_id))

    excluded = set(environment.excluded_chunk_ids)
    for chunk_id in sorted(set(case.evidence_chunk_ids) & excluded):
        issues.append(_issue("evidence_excluded", case.case_id,
                             "evidence chunk is excluded from the environment", chunk_id))

    available = set(environment.visible_chunk_ids + environment.research_chunk_ids)
    for chunk_id in sorted(set(case.evidence_chunk_ids) - available):
        issues.append(_issue("evidence_outside_environment", case.case_id,
                             "evidence chunk is outside visible and research pools", chunk_id))

    case_evidence = set(case.evidence_chunk_ids)
    required_claims = set(case.required_claim_ids)
    for chunk_id in case.evidence_chunk_ids:
        chunk = chunks_by_id.get(chunk_id)
        if chunk is not None and chunk.source_id not in case.allowed_source_ids:
            issues.append(_issue("evidence_source_not_allowed", case.case_id,
                                 "evidence chunk source is not allowed", chunk_id, chunk.source_id))
        if chunk is not None and required_claims.isdisjoint(chunk.claim_ids):
            issues.append(_issue("case_evidence_without_required_claim", case.case_id,
                                 "case evidence supports no required claim", chunk_id))
    visible_claims = {
        claim_id
        for chunk_id in environment.visible_chunk_ids
        if (chunk := chunks_by_id.get(chunk_id)) is not None
        for claim_id in chunk.claim_ids
    }
    research_claims = {
        claim_id
        for chunk_id in environment.research_chunk_ids
        if (chunk := chunks_by_id.get(chunk_id)) is not None
        for claim_id in chunk.claim_ids
    }
    for claim_id in case.required_claim_ids:
        claim = claims_by_id.get(claim_id)
        if claim is None:
            continue
        supporting = set(claim.evidence_chunk_ids) & case_evidence
        chunk_declares_claim = any(
            claim_id in chunks_by_id[chunk_id].claim_ids
            for chunk_id in supporting if chunk_id in chunks_by_id
        )
        if not supporting or not chunk_declares_claim:
            issues.append(_issue("required_claim_without_evidence", case.case_id,
                                 "required claim is not supported by case evidence", claim_id))
    for claim_id in sorted(set(case.missing_claim_ids) & visible_claims):
        issues.append(_issue("missing_claim_visible", case.case_id,
                             "missing claim is supported by a visible chunk", claim_id))

    if case.category.value == "local_sufficient":
        if case.missing_claim_ids:
            issues.append(_issue("local_sufficient_missing_claims", case.case_id,
                                 "local sufficient case cannot contain missing claims",
                                 *case.missing_claim_ids))
        for claim_id in sorted(required_claims - visible_claims):
            issues.append(_issue("local_sufficient_claim_not_visible", case.case_id,
                                 "required claim lacks visible support", claim_id))
    elif case.category.value in {"local_partial", "local_missing"}:
        missing_claims = set(case.missing_claim_ids)
        if case.category.value == "local_partial" and (
            not missing_claims or missing_claims == required_claims
        ):
            issues.append(_issue("local_partial_invalid_missing_partition", case.case_id,
                                 "local partial case requires a nonempty proper subset of missing claims",
                                 *case.missing_claim_ids))
        if case.category.value == "local_missing" and (
            not missing_claims or missing_claims != required_claims
        ):
            issues.append(_issue("local_missing_invalid_missing_partition", case.case_id,
                                 "local missing case requires every required claim to be missing",
                                 *case.missing_claim_ids))
        for claim_id in sorted(set(case.missing_claim_ids) - research_claims):
            issues.append(_issue("missing_claim_not_research_supported", case.case_id,
                                 "missing claim lacks research support", claim_id))
        known_claims = required_claims - missing_claims
        for claim_id in sorted(known_claims - visible_claims):
            issues.append(_issue("known_claim_not_visible", case.case_id,
                                 "non-missing required claim lacks visible support", claim_id))
    elif case.category.value == "outdated":
        has_outdated_evidence = any(
            old_claim_id in claims_by_id
            and claims_by_id[old_claim_id].valid_until is not None
            and any(
                current_id in research_claims
                and (
                    current_id in claims_by_id[old_claim_id].conflicts_with
                    or old_claim_id in claims_by_id[current_id].conflicts_with
                )
                for current_id in required_claims if current_id in claims_by_id
            )
            for old_claim_id in visible_claims
        )
        if not has_outdated_evidence:
            issues.append(_issue("outdated_evidence_missing", case.case_id,
                                 "outdated case lacks expired visible conflict and research update"))
    elif case.category.value == "conflict":
        visible_known = visible_claims & claims_by_id.keys()
        has_visible_conflict = any(
            right in visible_known
            and (right in claims_by_id[left].conflicts_with
                 or left in claims_by_id[right].conflicts_with)
            for left in visible_known for right in visible_known if left != right
        )
        if not has_visible_conflict or not (required_claims & research_claims):
            issues.append(_issue("conflict_evidence_missing", case.case_id,
                                 "conflict case lacks visible conflict or research adjudication"))
    return _sorted_issues(issues)


def validate_dataset(
    cases: Iterable[BenchmarkCase],
    environments: Iterable[KnowledgeEnvironment],
    chunks: Iterable[CorpusChunk],
    claims: Iterable[Claim],
) -> tuple[ValidationIssue, ...]:
    case_items = tuple(cases)
    environment_items = tuple(environments)
    chunk_items = tuple(chunks)
    claim_items = tuple(claims)
    issues: list[ValidationIssue] = []

    def index_unique(items, key_name: str, issue_code: str):
        result = {}
        ordered_items = sorted(items, key=lambda item: (
            getattr(item, key_name), canonical_json(item.model_dump(mode="json")),
        ))
        for item in ordered_items:
            key = getattr(item, key_name)
            if key in result:
                issues.append(_issue(issue_code, getattr(item, "case_id", "<dataset>"),
                                     f"duplicate {key_name}", key))
            else:
                result[key] = item
        return result

    environments_by_id = index_unique(environment_items, "environment_id", "duplicate_environment_id")
    chunks_by_id = index_unique(chunk_items, "chunk_id", "duplicate_chunk_id")
    claims_by_id = index_unique(claim_items, "claim_id", "duplicate_claim_id")
    index_unique(case_items, "case_id", "duplicate_case_id")
    for chunk in chunk_items:
        for claim_id in sorted(set(chunk.claim_ids) - claims_by_id.keys()):
            issues.append(_issue("chunk_claim_not_found", "<dataset>",
                                 "chunk references an unknown claim", chunk.chunk_id, claim_id))
        for claim_id in sorted(set(chunk.claim_ids) & claims_by_id.keys()):
            if chunk.chunk_id not in claims_by_id[claim_id].evidence_chunk_ids:
                issues.append(_issue("chunk_claim_missing_evidence_link", "<dataset>",
                                     "chunk claim link is absent from claim evidence",
                                     chunk.chunk_id, claim_id))
    for claim in claim_items:
        for chunk_id in sorted(set(claim.evidence_chunk_ids) - chunks_by_id.keys()):
            issues.append(_issue("claim_evidence_chunk_not_found", "<dataset>",
                                 "claim references an unknown evidence chunk",
                                 claim.claim_id, chunk_id))
        for chunk_id in sorted(set(claim.evidence_chunk_ids) & chunks_by_id.keys()):
            if claim.claim_id not in chunks_by_id[chunk_id].claim_ids:
                issues.append(_issue("claim_evidence_missing_claim_link", "<dataset>",
                                     "claim evidence link is absent from chunk claims",
                                     claim.claim_id, chunk_id))
        for conflict_id in sorted(set(claim.conflicts_with) - claims_by_id.keys()):
            issues.append(_issue("claim_conflict_not_found", "<dataset>",
                                 "claim references an unknown conflicting claim",
                                 claim.claim_id, conflict_id))
    for case in case_items:
        environment = environments_by_id.get(case.environment_id)
        if environment is None:
            issues.append(_issue("environment_not_found", case.case_id,
                                 "case references an unknown environment", case.environment_id))
            continue
        issues.extend(validate_case(case, environment, chunks_by_id, claims_by_id))
    return _sorted_issues(issues)


def build_runtime_payload(case: BenchmarkCase, environment: KnowledgeEnvironment) -> dict:
    return {
        "case_id": case.case_id,
        "base_question_id": case.base_question_id,
        "question": case.question,
        "environment_id": case.environment_id,
        "visible_chunk_ids": list(environment.visible_chunk_ids),
    }
