"""Legal Research inputs and bounded, source-only model output."""
from datetime import date
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.evidence import VerifiedClaim, Citation, Warning, Confidence

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

class Filters(Strict):
    jurisdictions: list[str] = Field(default_factory=list,max_length=20)
    courts: list[str] = Field(default_factory=list,max_length=20)
    date_from: date | None = None
    date_to: date | None = None
    source_types: list[Literal['statute','judgment','secondary']] = Field(default_factory=lambda:['statute','judgment'])
    @model_validator(mode='after')
    def dates(self):
        if self.date_from and self.date_to and self.date_from>self.date_to: raise ValueError('Invalid date range')
        return self

class Options(Strict):
    include_secondary_sources: bool = False
    connect_to_case_facts: bool = True
    depth: Literal['standard','deep'] = 'standard'

class CreateResearch(Strict):
    question: str = Field(min_length=5,max_length=4000)
    context_document_ids: list[UUID] = Field(default_factory=list,max_length=20)
    filters: Filters = Field(default_factory=Filters)
    options: Options = Field(default_factory=Options)

class Proposition(Strict):
    section: Literal['executive_summary','legal_framework','application_to_facts']
    text: str = Field(min_length=1,max_length=2000)
    source_ids: list[str] = Field(min_length=1,max_length=8)

class ProposedResearch(Strict):
    propositions: list[Proposition] = Field(default_factory=list,max_length=24)
    limitations: list[str] = Field(default_factory=list,max_length=12)

class Decision(Strict):
    id: UUID
    supported: bool
    reason: str = Field(min_length=1,max_length=160)

class Checks(Strict):
    decisions: list[Decision] = Field(max_length=24)

class ResearchFeedback(Strict):
    accepted: bool
    use_for_training: bool = False

class RefineResearch(Strict):
    instruction: str = Field(min_length=5,max_length=2000)

class Summary(Strict):
    text: str
    claim_ids: list[UUID]
    citation_ids: list[UUID]

class Framework(Strict):
    heading: str
    analysis: str
    claim_ids: list[UUID]
    citation_ids: list[UUID]

class Application(Strict):
    issue: str
    analysis: str
    fact_citation_ids: list[UUID]
    law_citation_ids: list[UUID]
    confidence: Confidence

class Authority(Strict):
    id: UUID
    case_name: str
    neutral_citation: str | None = None
    court: str
    decided_at: str | None = None
    proposition: str
    treatment: Literal['binding','persuasive','distinguished','overruled','negative_treatment','unknown']
    claim_ids: list[UUID]
    citation_ids: list[UUID]

class ResearchMemo(Strict):
    id: UUID
    question: str
    context_document_ids: list[UUID]
    filters: Filters
    options: Options
    status: str
    parent_id: UUID | None
    version: int
    created_at: str
    model: dict
    source_document_ids: list[UUID]
    job_id: UUID
    failure: dict | None
    scope: dict
    search_log: list[dict]
    sub_queries: list[dict]
    retrieval: dict
    executive_summary: Summary
    legal_framework: list[Framework]
    key_authorities: list[Authority]
    application_to_facts: list[Application]
    conflicting_authorities: list[dict]
    claims: list[VerifiedClaim]
    citations: list[Citation]
    warnings: list[Warning]
    limitations: list[str]
    confidence: Confidence
    verification: dict
