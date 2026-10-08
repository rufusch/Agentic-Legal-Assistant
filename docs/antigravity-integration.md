# Antigravity frontend integration

Run `./run-local.ps1` and open http://127.0.0.1:8000/. The supplied frontend lives in `antigravity-frontend`; the original ZIP is unchanged. `/backend-preview` preserves the earlier diagnostic frontend.

The active frontend uses authenticated backend APIs for homepage activity, document upload with SHA256 and parsing, Contract / Case Review, Legal Drafting, Legal Research, source inspection and binary exports. Jobs use bearer-authenticated streaming, terminal recovery and cancellation. Draft edits carry the current version to prevent silent conflicts. Source links use citation UUIDs, so repeated labels such as S1 cannot select another report’s evidence.

The supplied mock backend and fabricated chat responses were removed from this working copy. RAG Chat and novelty display planned status. Research uses uploaded authorities and reports insufficient evidence when they are absent; it does not search an external legal database.

Browser validation covered real homepage/library data, extracted document source inspection, a new drafting requirements check, an existing draft with exact source quotes, and a new research run that correctly abstained without authorities. Backend tests: 68 passed. Frontend contract tests cover upload/hash, request mapping, optimistic conflicts, citation identity and terminal streaming recovery. Run them with `node antigravity-frontend/tests/api-integration.test.mjs`.

No new full drafting/review inference or model training was performed during integration. The configured local model can be slow on CPU. Cloud deployment and external model connectivity have not been validated here; end users need only a browser once the backend and model are hosted. Model credentials stay on the server. Production requires an authenticated session; automatic demo sessions are loopback-only.

The four workflow configurations can later point to independently fine-tuned model artifacts. Building the application does not train model weights. Large legal corpora require a separate ingestion, curation and evaluation process; retrieval data and approved fine-tuning examples serve different purposes.
