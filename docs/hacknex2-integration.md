# Hacknex2 with the trainable workflow backend

The active application now uses `hacknex2-frontend`, extracted from the supplied `Hacknex2-Complete-Project.zip`. The original archive is unchanged. The supplied desktop layout, colors, navigation and screens are retained. Inline style values were moved into `css/supplied-layout.css` to work with the backend's existing security policy; narrow-window adaptations keep the preview usable.

Start with `./run-local.ps1` and open http://127.0.0.1:8000/. The existing workspace documents and earlier review, draft and research results are preserved. `/backend-preview` remains available for diagnostics.

## Real integrations

- Homepage uses authenticated tenant, user, activity and document counts.
- Document uploads compute SHA256, upload actual bytes, parse/OCR and wait for a ready source. Source inspection resolves stored text and offsets.
- Contract / Case Review uses the existing independent review model and report verification.
- Legal Drafting uses the existing independent drafting model, missing-information checks, grounded generation, version conflicts and real exports.
- Legal Research uses the existing independent research model and uploaded authorities. It abstains without adequate authorities.
- The supplied AI Assistant screen now uses an independent RAG Chat model. Conversations and messages persist under tenant ownership. Jobs support cancellation and restart recovery. Every published proposition has exact source references and a second support check. Unverified output is omitted. The same model performs both passes, so checks do not guarantee legal correctness.

Simulated uploads, records, answers, citations, feedback and Gemini branding were replaced by actual backend state. Helpful feedback does not authorize training. No external legal database is connected. Novelty remains pending; the supplied archive does not contain a completed novelty implementation.

## Model replacement and training

The workflow modules are our backend implementations; the underlying generative weights are the configured pretrained model, currently Qwen through Ollama. Four independent configuration prefixes select a model or later fine-tuned artifact:

| Workflow | Environment prefix |
| --- | --- |
| Contract / Case Review | `LEXIMIND_REVIEW_` |
| Legal Drafting | `LEXIMIND_DRAFTING_` |
| Legal Research | `LEXIMIND_RESEARCH_` |
| RAG Chat / AI Assistant | `LEXIMIND_CHAT_` |

Each supports `LLM_MODEL`, `LLM_PROVIDER`, `BASE_URL` and server-only `API_KEY`. The default weights may be shared, but each workflow has its own model instance, prompts, output contract and verification. Training/replacing one need not change the others. Cloud deployment remains server-side; end-user laptops need only a browser once hosted.

Model weights have not been trained here. A generative fine-tuning pipeline, corpus cleaning, licensing review, evaluation and training infrastructure remain separate work. Ingesting statutes or cases into retrieval does not itself train model weights.

Chat training examples are exported only after explicit accepted feedback with `use_for_training: true`. Use `POST /api/v1/conversations/{conversation_id}/messages/{message_id}/feedback` to approve or revoke, and `GET /api/v1/models/chat/dataset?format=sft` to export tenant-scoped JSONL. Only verified published propositions become targets. Deleting a source removes dependent conversations, answers, approvals and candidates. Earlier workflow training APIs remain available.

## Validation

72 backend tests passed. Final focused chat/frontend tests passed after the shared chat dataset route was added. Frontend contract tests passed, including real chat scope and training-consent mapping. Browser checks confirmed chat submission, evidence-gap abstention, saved feedback and conversation restoration after reload. Prior review/drafting/research integration tests remain passing.

No new full local-model generation was benchmarked during this integration; grounded synthesis and verification were exercised using controlled model test doubles. CPU inference can be slow. Cloud deployment and cloud model connectivity have not been executed here.
