"""Reusable evidence contracts; validates references before final output is published."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Citation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: UUID
    label: str = Field(min_length=1)
    document_id: UUID
    document_name: str
    chunk_id: UUID
    quoted_text: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)
    section: str | None = None
    paragraph: int | None = Field(default=None, ge=1)
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)
    source_url: str | None = None
    jurisdiction: str | None = None
    court: str | None = None
    decided_at: str | None = None


class VerifiedClaim(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: UUID
    text: str = Field(min_length=1)
    citation_ids: list[UUID]
    verification_status: Literal['supported', 'partially_supported', 'unsupported', 'contradicted']
    confidence: float = Field(ge=0, le=1)
    warning: str | None = None


class Confidence(BaseModel):
    score: float = Field(ge=0, le=1)
    level: Literal['high', 'medium', 'low', 'unavailable']
    explanation: str


class Warning(BaseModel):
    id: UUID
    type: Literal['missing_information', 'contradiction', 'unsupported_claim', 'weak_authority', 'ocr_quality', 'partial_processing']
    severity: Literal['info', 'warning', 'critical']
    title: str
    message: str
    related_claim_ids: list[UUID] = Field(default_factory=list)
    citation_ids: list[UUID] = Field(default_factory=list)
    resolvable: bool


class EvidenceBundle(BaseModel):
    claims: list[VerifiedClaim]
    citations: list[Citation]
    warnings: list[Warning] = Field(default_factory=list)

    @model_validator(mode='after')
    def validate_references(self):
        citations = {c.id for c in self.citations}
        claims = {c.id for c in self.claims}
        if len(citations) != len(self.citations) or len(claims) != len(self.claims):
            raise ValueError('Evidence IDs must be unique.')
        if len({c.label for c in self.citations}) != len(self.citations):
            raise ValueError('Citation labels must be unique.')
        for claim in self.claims:
            if claim.verification_status not in {'supported', 'partially_supported'} or not claim.citation_ids:
                raise ValueError('Final claims require supported or partially supported cited evidence.')
            if not set(claim.citation_ids) <= citations:
                raise ValueError('Unresolved citation reference.')
        for warning in self.warnings:
            if not set(warning.citation_ids) <= citations or not set(warning.related_claim_ids) <= claims:
                raise ValueError('Unresolved warning reference.')
        return self

    def validate_source_spans(self, load_chunk):
        """load_chunk must enforce the caller's tenant scope; exact quotes alone do not prove entailment."""
        for citation in self.citations:
            chunk = load_chunk(str(citation.document_id), str(citation.chunk_id))
            if str(chunk['document_id']) != str(citation.document_id):
                raise ValueError('Citation document mismatch.')
            if citation.quoted_text not in chunk['text']:
                raise ValueError('Citation quote is not an exact stored span.')
            if (citation.start_offset is None) != (citation.end_offset is None):
                raise ValueError('Citation offsets must be supplied together.')
            if citation.start_offset is not None:
                start = citation.start_offset - chunk['start_offset']
                end = citation.end_offset - chunk['start_offset']
                if start < 0 or end <= start or end > len(chunk['text']) or chunk['text'][start:end] != citation.quoted_text:
                    raise ValueError('Citation offsets do not resolve to its exact quote.')
        return self
