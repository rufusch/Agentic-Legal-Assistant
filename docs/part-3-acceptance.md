# Legal Drafting acceptance — 8 October 2026

## Automated validation

- Full backend regression: `python -m pytest -q --basetemp=tmp/backend-part3-release` — **60 passed**, two dependency deprecation warnings.
- Final bounded-verification-format check: `python -m pytest tests/test_drafting.py -q --basetemp=tmp/backend-drafting-reasons` — **9 passed**.
- Affected-module checks after final prompt/transport updates: `python -m pytest tests/test_drafting.py tests/test_llm_review.py tests/test_cloud_integration.py -q --basetemp=tmp/backend-part3-transport-final` — **22 passed**.
- Browser client checks: `node integration/api-client.test.mjs` passed; `node --check frontend/drafting.js` passed.
- Coverage includes asynchronous intake, answered/acknowledged/blocking gaps, unknown requirement rejection, source/claim identity, unknown citations, fabricated legal statements, hidden factual assertions, verification coverage failure, tenant isolation, unavailable model failure, source deletion cascade, version conflicts, unverified export blocking, TXT/DOCX/PDF output, unchanged-text re-verification, approved sanitized SFT data, consent revocation, stale-version exclusion, cancellation, idempotent generation and restart recovery for intake/generation.
- Separate drafting model activation was verified to leave the review model unchanged.

## Live preview

The real local backend accepted a synthetic Contract clause matter through the browser, displayed missing intake fields, saved answers and ran real Qwen 4B generation plus a second support-check pass. It completed with warnings: **10 source-linked claims, 4 citations and 2 unsupported blocks replaced by visible placeholders**. The source drawer opened the actual captured intake record. Current-code validation of the completed result's exact source spans passed, and live TXT/DOCX/PDF exports succeeded. See part-3-live-validation.json and legal-drafting-preview.png.

The run took over 20 minutes on this laptop's CPU and produced repetitive optional sections. Subsequent prompt refinements expose the user's drafting instructions directly, request only relevant headings, and shorten verification reasons; those refinements pass automated checks but have not been re-run through another full real-model generation. Cloud model services can use their default CPU allocation instead of a hardcoded two-thread cap. The local runner retains a configurable two-thread override for this laptop.

The live test validates the executable path and exact source links, not court filing quality or all supported document genres. It does not establish independent legal correctness. The completed draft is preserved in local history, and the preview server was restarted with the final code after validation.

## Deployment and quality boundaries

Cloud deployment remains untested because Docker is unavailable here. Current legal authority retrieval searches the tenant library; no external legal database or identity-provider login is included. The initial missing-info check uses transparent templates and is not a court-compliance certification. English output is currently supported. CPU inference on this laptop is slow. Source-span validation plus same-model interpretation checking cannot guarantee the absence of all factual/legal errors. Human legal review remains necessary.
