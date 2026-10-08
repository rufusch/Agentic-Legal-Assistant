"""Retrieval ablation on the public starter corpus (Indian Contract Act + SC bail order).

Gold chunks are identified by a verbatim substring (whitespace-insensitive). Queries are
written in practitioner style (abbreviations, old/new code names) on purpose; they are NOT a
held-out set, so treat absolute numbers as indicative only.
Usage: python scripts/bench_retrieval.py [--modes bm25,hybrid,...]
"""
import argparse
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.parsing import chunks as split, extract  # noqa: E402
from backend.retrieval import RETRIEVERS  # noqa: E402

FILES = ['indian-contract-act-1872.pdf', 'supreme-court-bail-2026-02-09.pdf']

# (query, verbatim gold substring)
QUERIES = [
    ('Is there any bar u/s 438 CrPC on anticipatory bail after the charge sheet is filed?', 'there is no restriction in Section 438'),
    ('Bharat Chaudhary (2003) 8 SCC 77 anticipatory bail cognizance', 'reported in (2003)8 SCC 77'),
    ('Sushila Aggarwal constitution bench: should protection under s.438 be limited to a fixed period?', 'should not invariably be limited to a fixed period'),
    ('Can the investigating agency seek arrest under 437(5) or 439(2) Cr.P.C. when graver offences are added after bail?', 'under Sections 437(5) or 439(2) of Cr.P.C.'),
    ('Does Section 170 CrPC require the officer to arrest every accused when filing the chargesheet?', 'does not impose an obligation on the officer-in-charge to arrest'),
    ('what offences was the FIR registered for - dowry death under BNS 80 and Dowry Prohibition Act', '80(2)/85 BNS and Sections 3 and 4'),
    ('Modification or cancellation of anticipatory bail under BNSS s. 482 instead of expiry clauses', 'expiry clauses inserted at inception are unsustainable'),
    ('Sec. 73 ICA damages for breach of contract', 'Compensation for loss or damage'),
    ('who is competent to contract - minor, age of majority, s.11 Contract Act', 'Who are competent to contract .'),
    ('agreement in restraint of trade void S. 27 ICA', 'Agreement in restraint of trade, void.—'),
    ('definition of contract of indemnity sec 124', 'A contract by which one party promises to save the other'),
    ('liquidated damages / penalty stipulated in contract s 74', 'Compensation for breach of contract where penalty stipulated for .—'),
    ('duty of care of bailee section 151 Indian Contract Act', 'Care to be taken by bailee .—'),
    ('what is the definition of agent and principal under the contract act', 'An “agent” is a person employed to do any act for another'),
    # Harder: new-code names for old-code text, bare section numbers, reporter citations, paraphrase.
    ('Can a court grant pre-arrest bail under BNSS 482 after cognizance is taken?', 'there is no restriction in Section 438'),
    ('cancellation of bail under BNSS 483 when graver offences are added in the chargesheet', 'under Sections 437(5) or 439(2) of Cr.P.C.'),
    ('S. 128 ICA', 'The liability of the surety is co - extensive'),
    ('sec 56 contract act', 'An agreement to do an act impossible in itself is void'),
    ('u/s 70 ICA', 'Where a person lawfully does'),
    ('Section 171 Indian Contract Act', 'Bankers, factors, wharfingers'),
    ('Joginder Kumar (1994) 4 SCC 260', 'Joginder Kumar'),
    ('2023 SCC OnLine SC 892', 'Md. Asfak Alam'),
    ('Art. 21 personal liberty - arrest is not mandatory merely because it is lawful', 'Merely because an arrest can be made because it is lawful'),
    ('compensation when promise is not performed and loss arises naturally', 'Compensation for loss or damage'),
]


def load():
    pool = []
    for f in FILES:
        parsed = extract((ROOT / 'corpus/public-starter' / f).read_bytes(), 'application/pdf')
        for page in parsed['pages']:
            for start, _, text in split(page['text']):
                pool.append({'id': f'{f[:12]}-p{page["number"]:03d}-{start:06d}', 'document_id': f, 'text': text})
    return pool


def squash(s):
    return re.sub(r'\s+', '', s).casefold()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--modes', default='bm25,lsa,hybrid,hybrid+rewrite,full')
    ap.add_argument('--ranks', action='store_true', help='print per-query gold rank per mode')
    args = ap.parse_args()
    modes = args.modes.split(',')
    pool = load()
    gold = {}
    for q, needle in QUERIES:
        ids = {c['id'] for c in pool if squash(needle) in squash(c['text'])}
        if not ids:
            raise SystemExit(f'gold substring not found: {needle!r}')
        gold[q] = ids
    print(f'{len(pool)} chunks, {len(QUERIES)} queries')
    if args.ranks:
        print('  '.join(modes))
        for q, _ in QUERIES:
            row = []
            for m in modes:
                ids = [h['id'] for h in RETRIEVERS[m](pool, q, 10)]
                row.append(next((i for i, x in enumerate(ids, 1) if x in gold[q]), '-'))
            print(row, q[:70])
        return
    print(f'{"mode":<16}{"R@1":>7}{"R@5":>7}{"R@10":>7}{"MRR@10":>8}{"ms/q":>8}')
    for mode in modes:
        RETRIEVERS[mode](pool, 'warm up', 10)
        r1 = r5 = r10 = mrr = 0
        t = time.perf_counter()
        misses = []
        for q, _ in QUERIES:
            ids = [h['id'] for h in RETRIEVERS[mode](pool, q, 10)]
            rank = next((i for i, x in enumerate(ids, 1) if x in gold[q]), None)
            r1 += rank == 1
            r5 += bool(rank and rank <= 5)
            r10 += bool(rank)
            mrr += 1 / rank if rank else 0
            if not rank or rank > 5:
                misses.append(f'{rank or "-"}:{q[:40]}')
        ms = (time.perf_counter() - t) * 1000 / len(QUERIES)
        n = len(QUERIES)
        print(f'{mode:<16}{r1/n:>7.2f}{r5/n:>7.2f}{r10/n:>7.2f}{mrr/n:>8.3f}{ms:>8.0f}')
        for m in misses:
            print('    miss@5', m)


if __name__ == '__main__':
    main()
