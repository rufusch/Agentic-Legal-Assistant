# Recommended public authorities for bail and criminal procedure

These sources could not be downloaded from the build sandbox: indiacode.nic.in, sci.gov.in, egazette.gov.in
and huggingface.co all refused connections. **No legal text was generated or added for them.** Download
them on your own machine:

```powershell
.\.venv\Scripts\python -m scripts.fetch_public_corpus corpus\recommended-sources.txt --out corpus\bail-authorities
.\.venv\Scripts\python -m scripts.ingest_corpus corpus\bail-authorities\manifest.jsonl     # validate, then add --execute
```

`fetch_public_corpus.py` checks every download. It rejects HTML or landing pages served in place of a PDF,
records the SHA-256 and `source_url`, and writes a manifest in the `corpus/public-starter` schema. Open each PDF
once and confirm the title before relying on it. Snapshots are `currency_status: not_certified`.

Status key:
* **indexed** means the exact URL appeared in search-engine results for the official site on 2026-10-08, but it was not fetched here.
* **verify** means the right document is known but the exact URL is not; find it via the landing page or search link.

## Statutes (India Code, Legislative Department)

| Source | URL | Status |
|---|---|---|
| Bharatiya Nagarik Suraksha Sanhita, 2023 (Act 46 of 2023). Bail: Chapter XXXV, ss. 478–496 (s. 479 undertrial detention, s. 480 bail in non-bailable offences, s. 482 anticipatory bail, s. 483 HC/Sessions powers). | https://indiacode.nic.in/bitstream/123456789/20099/3/A2023-46.pdf | indexed |
| Bharatiya Nyaya Sanhita, 2023 (Act 45 of 2023) | https://www.indiacode.nic.in/bitstream/123456789/20062/1/a202345.pdf | indexed |
| Bharatiya Sakshya Adhiniyam, 2023 (Act 47 of 2023) | https://www.indiacode.nic.in/bitstream/123456789/20063/1/aa202347.pdf | indexed |
| Code of Criminal Procedure, 1973 (repealed 1 July 2024; still governs earlier proceedings). Bail: ss. 436–439, 167(2) default bail. | https://www.indiacode.nic.in/bitstream/123456789/15272 (handle page; download the PDF there). Candidate PDF: https://www.indiacode.nic.in/bitstream/123456789/13624/1/the_code_of_criminal_procedure%2c_1973.pdf | verify (two different CrPC PDFs are indexed; confirm it is the amended English text) |
| Indian Penal Code, 1860 (for pre-July 2024 offences) | https://www.indiacode.nic.in (search "Indian Penal Code") | verify |
| Constitution of India (Art. 21, 22, 32, 136, 226) | https://legislative.gov.in/constitution-of-india (landing page; download the current English PDF) | verify |
| Indian Contract Act, 1872 | already in `corpus/public-starter` | done |

## Supreme Court judgments on bail (sci.gov.in)

Judgment PDFs live under `https://api.sci.gov.in/supremecourt/<year>/<diary>/...pdf`. Find each one through
https://www.sci.gov.in/judgements-case-no/ or the party-name search, then copy the PDF link into the list file.
Record `neutral_citation`, `court` and `decided_at` in its metadata.

| Judgment | Why it matters | Status |
|---|---|---|
| Satender Kumar Antil v. CBI, (2022) 10 SCC 51, decided 11 July 2022 (SLP (Crl) 5191/2021) | Categories of offences and bail guidelines; s. 41/41A compliance | verify. Follow-up compliance orders in diary 37889/2022 are indexed, e.g. https://api.sci.gov.in/supremecourt/2022/37889/37889_2022_2_3_43287_Order_29-Mar-2023.pdf (an *order*, not the main judgment) |
| Arnesh Kumar v. State of Bihar, (2014) 8 SCC 273 | Arrest safeguards for offences punishable up to 7 years | verify |
| Sushila Aggarwal v. State (NCT of Delhi), (2020) 5 SCC 1 (Constitution Bench) | Duration of anticipatory bail | verify |
| Gurbaksh Singh Sibbia v. State of Punjab, (1980) 2 SCC 565 | Anticipatory bail principles | verify |
| Siddharam Satlingappa Mhetre v. State of Maharashtra, (2011) 1 SCC 694 | Anticipatory bail factors (cited in the starter judgment) | verify |
| Sanjay Chandra v. CBI, (2012) 1 SCC 40 | Bail is the rule; purpose of detention | verify |
| Union of India v. K.A. Najeeb, (2021) 3 SCC 713 | Long undertrial custody versus statutory bail bars, under Art. 21 | verify |
| M. Ravindran v. Intelligence Officer, DRI, (2021) 2 SCC 485 | Default bail under s. 167(2) CrPC | verify |
| Sumit v. State of U.P., 2026 INSC 145 | already in `corpus/public-starter` | done |

The SCC citations above identify the cases. Do not put SCC citations in metadata unless you read them off
the downloaded document. Use the neutral citation printed on the PDF where there is one.

Gazette notifications (egazette.gov.in): the BNSS/BNS/BSA commencement notification (1 July 2024) is useful
for temporal-applicability questions. Search https://egazette.gov.in and verify the notification number before
adding it.
