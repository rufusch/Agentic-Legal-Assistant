from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.evidence import Citation, Confidence, EvidenceBundle, VerifiedClaim, Warning


class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')


class ReviewOptions(Strict):
    compare_with_governing_law: bool=False
    risk_tolerance: Literal['conservative','balanced','aggressive']='balanced'
    jurisdiction: str | None=Field(default=None,min_length=2,max_length=100)
    as_of_date: date | None=None
    authority_document_ids: list[UUID]=Field(default_factory=list,max_length=20)


class CreateReview(Strict):
    document_ids: list[UUID]=Field(min_length=1,max_length=20)
    focus_question: str=Field(default='',max_length=2000)
    options: ReviewOptions=Field(default_factory=ReviewOptions)


class RerunReview(Strict):
    focus_question: str | None=Field(default=None,max_length=2000)
    options: ReviewOptions | None=None


class Fact(Strict):
    id: UUID
    label: str
    value: str
    claim_id: UUID
    citation_ids: list[UUID]=Field(min_length=1)
    assertion_type: Literal['source_statement','allegation','finding','inference']='source_statement'


class Side(Strict):
    statement: str
    citation_ids: list[UUID]=Field(min_length=1)


class Contradiction(Strict):
    id: UUID
    topic: str
    description: str
    severity: Literal['low','medium','high','critical']
    sides: list[Side]=Field(min_length=2)
    legal_effect: str | None=None
    resolution: str | None=None
    confidence: Confidence


class Missing(Strict):
    id: UUID
    item: str
    why_it_matters: str
    suggested_action: str | None=None
    severity: Literal['low','medium','high']
    citation_ids: list[UUID]=Field(default_factory=list)


class Evidence(Strict):
    id: UUID
    title: str
    summary: str
    category: Literal['clause','fact','law','precedent']
    citation_ids: list[UUID]=Field(min_length=1)


class Risk(Strict):
    id: UUID | None=None
    risk: str
    severity: Literal['low','medium','high','critical']
    likelihood: Literal['unlikely','possible','likely','unknown']
    citation_ids: list[UUID]=Field(min_length=1)


class RiskSummary(Strict):
    overall: Literal['low','medium','high','critical','undetermined']
    rationale: str
    items: list[Risk]


class Overview(Strict):
    id: UUID
    text: str = Field(min_length=1)
    citation_ids: list[UUID] = Field(min_length=1)


class TimelineEvent(Strict):
    id: UUID
    date: str | None
    event: str = Field(min_length=1)
    citation_ids: list[UUID] = Field(min_length=1)


class InterpretationCheck(Strict):
    item_id: UUID
    supported: bool
    reason: str = Field(min_length=1)


class VerificationRecord(Strict):
    method: str = ''
    same_model: bool = True
    items: list[InterpretationCheck] = Field(default_factory=list)


class ReviewReport(Strict):
    id: UUID
    status: str
    focus_question: str
    key_facts: list[Fact]
    contradictions: list[Contradiction]
    missing_information: list[Missing]
    relevant_evidence: list[Evidence]
    risk_summary: RiskSummary
    claims: list[VerifiedClaim]
    citations: list[Citation]
    warnings: list[Warning]
    confidence: Confidence
    source_document_ids: list[UUID]
    created_at: str
    options: ReviewOptions
    model: dict
    version: int
    root_review_id: UUID
    previous_review_id: UUID | None=None
    authority_coverage: list[dict]=Field(default_factory=list)
    job_id: UUID
    failure: dict | None=None
    overview: Overview | None=None
    timeline: list[TimelineEvent]=Field(default_factory=list)
    document_kind: str | None=None
    coverage: dict=Field(default_factory=dict)
    verification: VerificationRecord=Field(default_factory=VerificationRecord)


def verify_report(report, chunks):
    """Fail closed on factual prose; baseline and trained topic adapters publish exact extracts."""
    report=ReviewReport.model_validate(report)
    sources={c['id']:c for c in chunks}
    def load(document, chunk):
        source=sources.get(chunk)
        if not source or source['document_id'] != document:
            raise ValueError('Source is unavailable')
        return source
    EvidenceBundle(claims=report.claims,citations=report.citations,warnings=report.warnings).validate_source_spans(load)
    citations={c.id:c for c in report.citations}
    claims={c.id:c for c in report.claims}
    llm=report.model.get('kind') in {'local_llm','hosted_llm'}
    decisions={str(d.item_id):d for d in report.verification.items}
    if len(decisions)!=len(report.verification.items):raise ValueError('Duplicate interpretation-check IDs')
    def checked(item_id):
        if llm and (str(item_id) not in decisions or decisions[str(item_id)].supported is not True):
            raise ValueError('Unverified model interpretation')
    def exact(text, refs):
        if not refs or any(ref not in citations for ref in refs) or not any(text == citations[ref].quoted_text for ref in refs):
            raise ValueError('Unverified factual prose')
    for claim in report.claims:
        if not llm: exact(claim.text,claim.citation_ids)
        else: checked(claim.id)
    for fact in report.key_facts:
        if fact.claim_id not in claims or claims[fact.claim_id].text != fact.value or not set(fact.citation_ids) <= set(claims[fact.claim_id].citation_ids):
            raise ValueError('Fact/claim mismatch')
        if not llm: exact(fact.value,fact.citation_ids)
    for item in report.relevant_evidence:
        if not llm: exact(item.summary,item.citation_ids)
        else: checked(item.id)
    for conflict in report.contradictions:
        checked(conflict.id)
        for side in conflict.sides:
            if not llm: exact(side.statement,side.citation_ids)
            elif any(ref not in citations for ref in side.citation_ids): raise ValueError('Unresolved contradiction citation')
    for item in [*report.missing_information,*report.risk_summary.items]:
        checked(item.id)
        if llm and not item.citation_ids: raise ValueError('Model findings require source references')
        if any(ref not in citations for ref in item.citation_ids):
            raise ValueError('Unresolved item citation')
    for item in ([report.overview] if report.overview else [])+report.timeline:
        if any(ref not in citations for ref in item.citation_ids): raise ValueError('Unresolved narrative citation')
        checked(item.id)
    for citation in report.citations:
        chunk=load(str(citation.document_id),str(citation.chunk_id))
        if citation.page != chunk.get('page'):
            raise ValueError('Incorrect citation page anchor')
    return report.model_dump(mode='json')
