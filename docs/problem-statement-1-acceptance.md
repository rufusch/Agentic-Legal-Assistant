# Problem Statement 1 release checklist

Source: user-supplied HackNEX_2026_Problem_Statements.pdf, pages 1–2, HNX26EPS01.

The product must support evidence-grounded Contract / Case Review, Legal Drafting, Legal Research and RAG Chat. Facts and citations must resolve to supplied source text. Missing evidence must remain visible. The supplied Hacknex2 interface remains the product interface.

Release work:

1. Audit complete user flows, source inspection, uploads, cancellations, exports, saved history and errors; repair inactive controls.
2. Add an inspectable grounding audit and deterministic publication checks alongside model support checks.
3. Provide a reproducible paired evaluation harness: identical inputs, baseline, ablations, retrieval metrics, claim support, citation integrity, coverage and human usefulness review. Do not treat abstention as a perfect answer.
4. Run automated regressions and live model smoke tests; record exact configuration, source hashes and results.
5. Deliver setup scripts, a self-contained source release, a short technical write-up and a manifest with checksums.

An evaluation on a public development fixture is not an unseen judging result. No baseline victory, legal correctness guarantee, or trained model weights may be claimed without evidence. The local open-weight model can later be fine-tuned independently for each workflow; a corpus importer and consent-controlled SFT exports are separate from weight training.
