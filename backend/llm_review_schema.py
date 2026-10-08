from typing import Literal
from uuid import UUID

from pydantic import Field
from backend.review_schema import Strict


class SourceRef(Strict):
    source_id: str = Field(pattern=r'^E[1-9][0-9]*$',description='Use an evidence source_id supplied in the packet.')


class CitedText(Strict):
    text: str = Field(min_length=1,max_length=1200)
    references: list[SourceRef] = Field(min_length=1,max_length=6)


class ModelFact(CitedText):
    label: str = Field(min_length=1,max_length=100)
    assertion_type: Literal['source_statement','allegation','finding','inference']


class ModelConflict(Strict):
    topic: str = Field(min_length=1,max_length=150)
    explanation: str = Field(min_length=1,max_length=800)
    sides: list[CitedText] = Field(min_length=2,max_length=4)
    severity: Literal['low','medium','high','critical']


class ModelGap(CitedText):
    why_it_matters: str = Field(min_length=1,max_length=600)
    suggested_action: str = Field(min_length=1,max_length=600)
    severity: Literal['low','medium','high']


class ModelEvidence(CitedText):
    title: str = Field(min_length=1,max_length=150)
    category: Literal['clause','fact','law','precedent']


class ModelRisk(CitedText):
    severity: Literal['low','medium','high','critical']
    likelihood: Literal['unlikely','possible','likely','unknown']


class ModelEvent(CitedText):
    date: str | None


class DraftAnalysis(Strict):
    document_kind: Literal['contract','case','mixed','other']
    overview: CitedText
    key_facts: list[ModelFact] = Field(max_length=15)
    timeline: list[ModelEvent] = Field(max_length=12)
    contradictions: list[ModelConflict] = Field(max_length=8)
    missing_information: list[ModelGap] = Field(max_length=8)
    relevant_evidence: list[ModelEvidence] = Field(max_length=15)
    risks: list[ModelRisk] = Field(max_length=8)


class VerificationDecision(Strict):
    id: str
    supported: bool
    reason: str = Field(min_length=1,max_length=500)


class Verification(Strict):
    decisions: list[VerificationDecision] = Field(max_length=80)
