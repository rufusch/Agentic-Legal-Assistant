"""Regenerate the framework-independent request/output schema package."""
import json
from pathlib import Path
from backend.review_schema import ReviewReport, CreateReview, RerunReview
from backend.evidence import Citation, VerifiedClaim
from backend.drafting_schema import CreateDraft, Answers, GenerateDraft, EditSection, DraftFeedback, LegalDraft

from backend.research_schema import CreateResearch, RefineResearch, ResearchFeedback, ResearchMemo

models=[CreateResearch,RefineResearch,ResearchFeedback,ResearchMemo,CreateReview,RerunReview,ReviewReport,Citation,VerifiedClaim,CreateDraft,Answers,GenerateDraft,EditSection,DraftFeedback,LegalDraft]
target=Path(__file__).resolve().parents[1]/'integration/contracts.json'
target.write_text(json.dumps({m.__name__:m.model_json_schema() for m in models},indent=2),encoding='utf-8')
