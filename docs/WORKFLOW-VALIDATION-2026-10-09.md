# Workflow repairs and validation

## Problems addressed

- Local drafting exhausted a 2,000-token output cap. The launcher now gives drafting 6,000 tokens and other roles 4,000 within a 16,384-token context.
- The 4,000-character evidence budget crowded out authorities after a detailed intake. The local budget is now 12,000 characters.
- Repeated source metadata consumed context. Metadata packing preserves every evidence ID and source passage.
- Large verification responses could truncate. Drafting, research and chat verify at most five items per request and require complete, unique decisions.
- Drafting now provides direct upload, selects the uploaded document and automatically proceeds to generation when instructions are present. Unknown details appear as placeholders rather than a routine intake checklist.
- Failed drafts can be retried from history; input errors remain visible and resumed jobs show progress.
- Research uploads are selected automatically; when a question is supplied, upload starts the research workflow.
- Chat upload had a duplicated busy guard that returned before uploading anything. The guard now permits the upload and restores input availability afterward.
- OCR's orientation classifier could rotate upright text and return whitespace. Low-quality recognition retries without rotation and selects the better result.
- Unsupported draft passages receive one bounded source-checked repair attempt. Court holdings cannot be supported solely by user intake even if the generator labels them as facts. User-edited drafts are never rewritten by this recovery.
- Omitted draft citations trigger local retrieval of candidate passages; candidates must still pass the support check before publication. Duplicate section-heading blocks are omitted.
- Structured bail applications and notices use literal document assembly when the required supplied fields resolve exactly to captured intake. Allegations remain attributed; no precedent, legal consequence or missing party is invented. Notices can prefill explicit party/payment/deadline spans from instructions. The generation method is reported as `literal_intake_template`.
- Title-only model responses no longer qualify as completed drafts.

- Read a document returns a connected paragraph; official laws used and uploaded-document passages are displayed separately. Legal references require verified government imports and named authorities.
- Reader questions submit through Ask question or Enter, reusing the uploaded document; question mode answers the specific question rather than requesting another general summary. Browser regressions cover both submission methods.

## Validation

- Final complete backend suite: 207 tests passed, including structured bail/notice assembly, empty-output rejection, draft-refinement, citation-recovery and real OCR regressions.
- Browser checks cover empty inputs, service failure recovery, direct draft upload through displayed output without a checklist, automatic research context selection, chat upload, summary output, draft editing, research PDF download, navigation and mobile overflow.
- Live local Qwen: document summary contains both parties, amount, date and notice period; follow-up chat returns the notice period; research returns a cited finding from an official statute.
- Real PDF, DOCX, scanned PNG and scanned PDF uploads recovered the expected source text through the live server.
- The failed draft was reproduced as `MODEL_OUTPUT_LIMIT`. Subsequent runs completed, with TXT, DOCX and PDF exports verified.
- The repaired bail application contains eight sections, source-attributed supplied facts and three genuine placeholder blocks (respondent, verified authority, execution details). A payment notice contains both parties, amount, deadline and invoice reference.

These checks establish the tested flows and source traceability. They do not certify every possible legal document or unavailable authority. Unverified content remains explicitly marked rather than silently invented.
