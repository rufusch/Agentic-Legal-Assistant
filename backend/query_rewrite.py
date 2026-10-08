"""Deterministic legal query understanding: section/act normalisation, old<->new code aliasing,
entity and exact-term extraction. An optional LLM hook adds paraphrases but is never required."""
import re
from dataclasses import dataclass, field

from backend.legal_aliases import ACTS, CONCEPTS, SYNONYMS, act_mappings

_MAP = act_mappings()
_ALIAS = sorted(((alias, key) for key, (_, aliases) in ACTS.items() for alias in aliases), key=lambda x: -len(x[0]))
_ACT_RE = re.compile(r'(?<![\w.])(' + '|'.join(re.escape(a) for a, _ in _ALIAS) + r')(?![\w])', re.I)
_ALIAS_KEY = {a: k for a, k in _ALIAS}
_NUM = r'(\d{1,4}[A-Z]{0,2})((?:\s*\(\s*[\da-z]{1,4}\s*\))*)'
_SEC_RE = re.compile(r'(?<![\w])(?:u/s\.?|sections?|secs?\.?|ss?\.|§)\s*' + _NUM + r'((?:\s*(?:/|,|and|&|r/w|read with)\s*\d{1,4}[A-Z]{0,2}(?:\s*\(\s*[\da-z]{1,4}\s*\))*)*)', re.I)
_ART_RE = re.compile(r'(?<![\w])(?:articles?|arts?\.?)\s*(\d{1,3}[A-Z]?)', re.I)
_CITE_RE = re.compile(r'\(\s*(?:19|20)\d{2}\s*\)\s*\d{1,3}\s*SCC\s*(?:\(\w+\)\s*)?\d{1,5}|(?:19|20)\d{2}\s+INSC\s+\d{1,5}|(?:19|20)\d{2}\s+SCC\s+OnLine\s+\w+\s+\d{1,6}|AIR\s+(?:19|20)\d{2}\s+SC\s+\d{1,5}|(?:19|20)\d{2}\s+Cri\.?\s*L\.?\s*J\.?\s+\d{1,6}', re.I)
_DATE_RE = re.compile(r'\b\d{1,2}[./-]\d{1,2}[./-](?:19|20)\d{2}\b|\b\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s+(?:19|20)\d{2}\b', re.I)
_MONEY_RE = re.compile(r'(?:rs\.?|inr|₹)\s*[\d,]+(?:\.\d+)?\s*(?:/-)?(?:\s*(?:lakh|lakhs|crore|crores))?', re.I)
_COURT_RE = re.compile(r'\b(?:supreme court(?: of india)?|high court(?: of [A-Z][a-z]+)?|sessions court|court of session|magistrate|district court|trial court)\b', re.I)
_PARTY_RE = re.compile(r'\b([A-Z][a-zA-Z.]+(?:\s+[A-Z][a-zA-Z.&]+){0,4})\s+(?:v\.?|vs\.?|versus)\s+([A-Z][a-zA-Z.]+(?:\s+[A-Z][a-zA-Z.&()]+){0,5})')


@dataclass
class ParsedQuery:
    original: str
    variants: list = field(default_factory=list)
    entities: dict = field(default_factory=dict)
    exact_terms: list = field(default_factory=list)   # e.g. 'section 438', '(2014) 8 scc 273'
    provisions: list = field(default_factory=list)    # [(act or None, number)] incl. aliases
    direct: list = field(default_factory=list)        # provisions written in the query itself
    acts: list = field(default_factory=list)


def _norm_cite(c):
    return re.sub(r'\s+', ' ', re.sub(r'\(\s*', '(', re.sub(r'\s*\)', ')', c))).strip().casefold()


def _acts(text):
    return [_ALIAS_KEY[m.group(1).casefold()] for m in _ACT_RE.finditer(text) if m.group(1).casefold() in _ALIAS_KEY]


def _nearest_act(text, pos):
    """Act named closest after (preferred, 'Section 438 CrPC') or before the reference."""
    after = _ACT_RE.search(text, pos, pos + 60)
    if after and after.group(1).casefold() in _ALIAS_KEY:
        return _ALIAS_KEY[after.group(1).casefold()]
    before = [m for m in _ACT_RE.finditer(text, max(0, pos - 60), pos)]
    return _ALIAS_KEY.get(before[-1].group(1).casefold()) if before else None


def parse_query(query):
    q = query or ''
    acts = list(dict.fromkeys(_acts(q)))
    provisions, sections, articles = [], [], []
    for m in _SEC_RE.finditer(q):
        nums = [m.group(1)] + re.findall(r'(\d{1,4}[A-Z]{0,2})', m.group(3) or '')
        act = _nearest_act(q, m.end())
        for n in nums:
            n = n.upper()
            sections.append(n)
            provisions.append((act, n))
    for m in _ART_RE.finditer(q):
        articles.append(m.group(1).upper())
        provisions.append(('coi', m.group(1).upper()))
    direct = list(provisions)
    low = q.casefold()
    for phrase, provs in CONCEPTS.items():
        if phrase in low:
            provisions.extend(p for p in provs if p not in provisions)
    # Old<->new code aliases. Bare numbers ('s. 438') resolve against acts named in the query.
    expanded = list(provisions)
    for act, n in provisions:
        candidates = [act] if act else (acts or [k for (k, num) in _MAP if num == n])
        for a in candidates:
            for alias in sorted(_MAP.get((a, n), ())):
                if alias not in expanded:
                    expanded.append(alias)
    cites = list(dict.fromkeys(_norm_cite(c.group(0)) for c in _CITE_RE.finditer(q)))
    exact = list(dict.fromkeys([f'{"article" if a == "coi" else "section"} {n.lower()}' for a, n in expanded] + cites))
    entities = {
        'sections': list(dict.fromkeys(sections)), 'articles': list(dict.fromkeys(articles)),
        'acts': [ACTS[a][0] for a in acts], 'citations': cites,
        'dates': _DATE_RE.findall(q), 'amounts': [m.strip() for m in _MONEY_RE.findall(q)],
        'courts': list(dict.fromkeys(m.group(0) for m in _COURT_RE.finditer(q))),
        'parties': [f'{a} v. {b}' for a, b in _PARTY_RE.findall(q)],
        'provisions': [{'act': ACTS[a][0] if a in ACTS else None, 'number': n} for a, n in expanded],
    }
    # Variant 1: canonicalised original. Variant 2: alias/act expansion. Variant 3: synonyms.
    canon = _SEC_RE.sub(lambda m: 'section ' + m.group(1) + (m.group(2) or '') + (m.group(3) or ''), q)
    canon = _ART_RE.sub(lambda m: 'article ' + m.group(1), canon)
    variants = [q]
    if canon.strip() and canon != q:
        variants.append(canon)
    extra = []
    for a, n in expanded:
        if (a, n) in provisions and a is None:
            continue
        name = ACTS[a][0] if a in ACTS else ''
        extra.append(f'{"article" if a == "coi" else "section"} {n} {name}'.strip())
    if extra:
        variants.append(canon + ' ' + ' '.join(dict.fromkeys(extra)))
    syn = [v for k, v in SYNONYMS.items() if re.search(r'(?<!\w)' + re.escape(k) + r'(?!\w)', low)]
    if syn:
        variants.append(canon + ' ' + ' '.join(syn))
    return ParsedQuery(q, list(dict.fromkeys(variants)), entities, exact, expanded, direct, acts)


REWRITE_SCHEMA = {'type': 'object', 'properties': {'variants': {'type': 'array', 'maxItems': 3, 'items': {'type': 'string', 'maxLength': 300}}}, 'required': ['variants'], 'additionalProperties': False}


def rewrite_with_llm(query, llm, limit=3):
    """Optional paraphrases from a duck-typed llm.complete(messages, schema)->dict. Never raises."""
    if llm is None:
        return []
    try:
        out = llm.complete([
            {'role': 'system', 'content': 'Rewrite the Indian legal research query into up to 3 alternative search queries. Use statutory wording, expand abbreviations, and include both pre-2023 (CrPC/IPC/Evidence Act) and 2023 (BNSS/BNS/BSA) names when relevant. Do not answer the query and do not invent case names or citations. Return JSON only.'},
            {'role': 'user', 'content': query[:2000]}], REWRITE_SCHEMA)
        items = out.get('variants', []) if isinstance(out, dict) else []
        return [v.strip()[:300] for v in items if isinstance(v, str) and v.strip()][:limit]
    except Exception:
        return []
