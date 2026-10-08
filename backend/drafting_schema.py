"""Legal Drafting contracts shared with the Antigravity SPA."""
from typing import Literal
from uuid import UUID
from pydantic import Field, model_validator
from backend.review_schema import Strict
from backend.evidence import Citation, VerifiedClaim, Confidence, Warning


class Preferences(Strict):
    language: Literal['en'] = 'en'
    tone: Literal['formal', 'plain'] = 'formal'
    include_alternative_clauses: bool = False


class CreateDraft(Strict):
    document_type: str = Field(min_length=2, max_length=100)
    jurisdiction: str = Field(min_length=2, max_length=100)
    court: str | None = Field(default=None, max_length=200)
    instructions: str = Field(min_length=5, max_length=8000)
    facts: dict = Field(default_factory=dict)
    supporting_document_ids: list[UUID] = Field(default_factory=list, max_length=20)
    preferences: Preferences = Field(default_factory=Preferences)

    @model_validator(mode='after')
    def bound_facts(self):
        import json
        if len(json.dumps(self.facts, ensure_ascii=False)) > 24000:
            raise ValueError('Facts must fit within 24,000 characters.')
        return self


class Answer(Strict):
    requirement_id: UUID
    value: str = Field(max_length=8000)


class Answers(Strict):
    answers: list[Answer] = Field(max_length=50)


class GenerateDraft(Strict):
    proceed_with_missing_information: bool = False
    acknowledged_requirement_ids: list[UUID] = Field(default_factory=list, max_length=50)


class EditSection(Strict):
    text: str = Field(min_length=1, max_length=12000)
    base_version: int = Field(ge=1)


class DraftFeedback(Strict):
    accepted: bool
    use_for_training: bool = False
    base_version: int = Field(ge=1)


class ProposedBlock(Strict):
    kind: Literal['paragraph', 'heading', 'list', 'signature', 'placeholder']
    text: str = Field(min_length=1, max_length=2000)
    statement_type: Literal['fact', 'legal', 'draft_language', 'placeholder']
    source_ids: list[str] = Field(max_length=6)


class ProposedSection(Strict):
    heading: str = Field(max_length=160)
    blocks: list[ProposedBlock] = Field(min_length=1, max_length=12)


class ProposedDraft(Strict):
    sections: list[ProposedSection] = Field(min_length=1, max_length=13)


class BlockDecision(Strict):
    id: UUID
    supported: bool
    statement_type: Literal['fact', 'legal', 'draft_language', 'placeholder']
    reason: str = Field(min_length=1, max_length=160)


class DraftVerification(Strict):
    decisions: list[BlockDecision] = Field(max_length=156)


class DraftBlock(Strict):
    id: UUID
    kind: Literal['paragraph', 'heading', 'list', 'signature', 'placeholder']
    text: str
    claim_ids: list[UUID]
    citation_ids: list[UUID]
    editable: bool = True
    statement_type: Literal['fact', 'legal', 'draft_language', 'placeholder', 'user_edit']
    verification_status: Literal['checked', 'unverified', 'placeholder']


class DraftSection(Strict):
    id: UUID
    heading: str
    order: int
    blocks: list[DraftBlock]


class LegalDraft(Strict):
    id: UUID
    status: str
    document_type: str
    title: str
    jurisdiction: str
    court: str | None
    instructions: str
    facts: dict
    supporting_document_ids: list[UUID]
    source_document_ids: list[UUID]
    preferences: Preferences
    requirements: list[dict]
    sections: list[DraftSection]
    unresolved_placeholders: list[dict]
    authorities: list[dict]
    claims: list[VerifiedClaim]
    citations: list[Citation]
    warnings: list[Warning]
    confidence: Confidence
    version: int
    created_at: str
    job_id: UUID
    model: dict
    failure: dict | None = None
    verification: dict = Field(default_factory=dict)
    retrieval: dict = Field(default_factory=dict)
    needs_verification: bool = False
    context_document_id: UUID | None = None
    acknowledged_requirement_ids: list[UUID] = Field(default_factory=list)
