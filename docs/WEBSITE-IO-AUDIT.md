# Website input/output audit — 9 October 2026

The live Chrome console showed HTTP 403 on document uploads, draft creation,
and conversation creation. The live Codespace has not been updated by this
audit; an authenticated remote shell is not available in this chat.

## Repairs

- Preserve the same-origin hosting cookie alongside the application bearer.
- Derive the exact Codespaces origin when starting the backend directly, and
  default a missing forwarding-domain variable to `app.github.dev`. Other
  Codespace origins remain rejected; private-port access remains required.
- Keep draft and review forms usable when local storage fails. Clear the
  correct tenant-specific review draft on reset and successful submission.
- Update the actual drafting requirements indicator. Prevent duplicate
  drafting, generation, review, research, and chat submissions.
- Surface chat initialization errors with a retry action. Retry incomplete
  initialization and tolerate history-list failures.
- Bind research controls before loading history, retain question/court/source
  selections across renders, and avoid replacing the progress DOM on every event.
- Guard file-input click bubbling; implement repository drag/drop and upload
  retry while preserving the chosen file and metadata. Report readiness only
  after parsing finishes.
- Escape document search values on render. Use a multiline chat message box;
  Enter sends, Shift+Enter inserts a line, and composition input does not send.
- Prevent attachment uploads from enabling Send during an active chat job;
  reset job-following state when changing conversations. Report clipboard and
  message-refresh errors.
- Preserve backend messages for failed draft saves, generation, and exports.
  Remove CSP-blocked inline drafting focus handlers and remote font requests.
- Restrict hash-based routing to registered workflows, preserving local anchors.

## Validation

- 40 backend tests passed across Codespaces configuration/origin rejection,
  frontend serving, drafting, research, chat, reviews, grounding audit and
  authenticated range/download behavior. These use deterministic model doubles.
- Browser tests run real frontend modules in headless Chrome under a same-origin
  CSP with controlled API responses. They check drafting/review validation and
  submission recovery, requirements enabling/disabling, research persistence
  despite failed history, file-picker behavior, quoted search values, upload
  retry and success, chat send recovery and multiline input, empty auditor,
  review/draft/memo output rendering, draft editing, PDF download, full-app
  startup, header document search, homepage prompt transfer, and local anchors.
- Client contract, input recovery, review upload, and review background tests pass.

This is coverage of the implemented workflows and reproduced failures, not a
claim that every possible input, provider outage, or legal answer is verified.
Hosted model outputs and the repaired live Codespace require a separate live
check after deploying these files and restarting the backend.

## Apply to the live Codespace

Copy the updated files into the Codespace project, then restart the existing
application using `bash scripts/start-codespaces.sh`. Keep port 8000 private.
The starter prints a new eight-hour application token; connect with that token
and reload the browser. Verify uploads, drafting, research, chat, source viewing
and exports against the running backend.
