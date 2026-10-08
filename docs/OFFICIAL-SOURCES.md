# Official-source grounding

Official PDF retrieval is enabled by default (`LEXIMIND_OFFICIAL_SOURCES=1`). No search API key is required. AI generation and verification still require the configured model provider and its API key, or a working local model.

Research and chat discover relevant sources in `corpus/official-catalog.json`, fetch the official PDF, parse it in the existing isolated parser, and retrieve exact stored passages. Drafting retrieves official authorities separately from user-provided case facts. Reviews fetch authorities when the existing **compare with governing law** option is enabled. All workflows retain their source-only generation and claim-verification checks. Raw training does not replace retrieval.

In **Legal Research → Context Documents**, enter an official PDF URL, title and source type, then select **Fetch official source**. India Code record pages are also supported when they expose a matching Act PDF. Successfully imported sources become available to research, drafting, chat and selected-document review.

The citation drawer includes the original source website, page/offset anchors, import date, SHA-256 and any dated-snapshot date. JSON exports retain provenance; review, drafting and research document exports include source URLs and available dates/checksums.

## Coverage and failures

Discovery is a local catalog of 853 entries, primarily central-legislation titles plus two Supreme Court judgments. It is **not** exhaustive internet search, a comprehensive case-law database, or a current-law/treatment certification. Add a specific official judgment PDF when the catalog lacks it. Supported hosts are listed by `GET /api/v1/official-sources` and in `backend/official_sources.py`; a new court host requires a reviewed allowlist change.

Only successfully fetched and parsed official PDF bytes enter evidence. A landing page must resolve to the same India Code record's PDF. Search snippets, the dataset's mirror text, a CAPTCHA, and model memory are never substituted for official evidence. Redirect destinations and public DNS addresses are validated; source size, transfer time and parser resource limits are bounded. Source text remains untrusted evidence, never instructions.

If live retrieval fails, only an exact-URL, hash-verified official starter snapshot may be used. Its original snapshot date and failed live fetch are recorded explicitly. Other failures are reported and the unavailable source is omitted. Insufficient supporting evidence results in abstention/placeholders through the existing verification workflow. Cached imports are reused for 24 hours; when reimported, only the latest stored version of the same URL is selected as an authority. Older historical outputs retain their original citations. This does not establish whether later amendments or judgments exist.

Official import receipts are server-created and tenant-scoped. User-uploaded metadata cannot forge one. When official retrieval is enabled, research/drafting/chat authority pools use these verified imports; uploaded case documents remain context/fact evidence. Set `LEXIMIND_OFFICIAL_SOURCES=0` to restore workspace-only authority behavior for an offline installation.

## Catalog attribution

Central-legislation discovery titles and India Code URLs were extracted from Vaquill's `open-india-law` central-legislation metadata, revision `58ea6d8b6859f8039ee68dff5af636f787b02463` (dataset card: CC BY 4.0). Attribution: [Vaquill open-india-law](https://huggingface.co/datasets/vaquill/open-india-law). Matching keywords and selected direct PDF URLs were added for discovery. These metadata entries are not used as legal evidence. The official source must be fetched independently.

## Validation

A live Qwen 27B/GPT-OSS 20B research test published two verified propositions citing the official India Code Contract Act PDF. This is an integration smoke check, not a broad accuracy result. The test exposed Groq request-size/rate-limit and verifier output-budget failures; these were resolved with bounded retrieval and provider-aware output budgets. Groq defaults to a 6,000-character excerpt budget and 1,500 generator output tokens; verifier/judge output remains 4,000 tokens. Repeated source metadata is encoded losslessly while all quotes and evidence IDs are preserved. Short Retry-After limits receive at most two cancellable retries; daily exhaustion fails without retry. Override scope with `LEXIMIND_SOURCE_CONTEXT_CHARACTERS` and output with `LEXIMIND_MODEL_MAX_OUTPUT_TOKENS` to fit your account allowance. Larger matters can still require a higher allowance or narrower scope.

Live test: downloaded the Supreme Court's Sumit v. State of U P judgment of 9 February 2026, parsed 30 passages and verified SHA-256 `55451c3fc23541d04dc6c80ade377d3be8d1b6e060bfe1a9bae83e566ed13ef3`. The running website also imported the Indian Contract Act and this judgment successfully from live official PDFs. Network availability can change.

Tests cover original-URL citation propagation, exact source checks, unavailable-source exclusion, dated-snapshot handling, hostile URLs/redirects, private DNS, and tenant isolation. They do not certify legal conclusions or model answer accuracy.
