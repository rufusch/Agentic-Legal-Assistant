"""Curated Indian legal aliases used for deterministic query expansion.

CURATED TABLE - VERIFY BEFORE RELYING ON IT. Mappings between the pre-2023 codes and the
2023 criminal-law reforms (in force 1 July 2024) were entered by hand for high-value bail /
criminal-procedure provisions only. They are used solely to widen *retrieval* recall; they
are never emitted as citations, so a wrong row can cost ranking quality but cannot fabricate
an authority. Check the official correspondence tables (MHA / India Code) before extending.
"""

# Canonical act key -> (display name, aliases matched case-insensitively on word boundaries).
ACTS = {
    'crpc': ('Code of Criminal Procedure, 1973', ['crpc', 'cr.p.c', 'cr. p.c', 'cr.p.c.', 'code of criminal procedure', 'criminal procedure code']),
    'bnss': ('Bharatiya Nagarik Suraksha Sanhita, 2023', ['bnss', 'bharatiya nagarik suraksha sanhita', 'nagarik suraksha sanhita']),
    'ipc': ('Indian Penal Code, 1860', ['ipc', 'i.p.c', 'i.p.c.', 'indian penal code', 'penal code']),
    'bns': ('Bharatiya Nyaya Sanhita, 2023', ['bns', 'bharatiya nyaya sanhita', 'nyaya sanhita']),
    'iea': ('Indian Evidence Act, 1872', ['evidence act', 'indian evidence act', 'iea']),
    'bsa': ('Bharatiya Sakshya Adhiniyam, 2023', ['bsa', 'bharatiya sakshya adhiniyam', 'sakshya adhiniyam']),
    'ica': ('Indian Contract Act, 1872', ['ica', 'contract act', 'indian contract act']),
    'sra': ('Specific Relief Act, 1963', ['sra', 'specific relief act']),
    'ni': ('Negotiable Instruments Act, 1881', ['ni act', 'n.i. act', 'n.i act', 'negotiable instruments act']),
    'coi': ('Constitution of India', ['constitution', 'constitution of india']),
    'cpc': ('Code of Civil Procedure, 1908', ['cpc', 'c.p.c', 'c.p.c.', 'code of civil procedure', 'civil procedure code']),
    'dpa': ('Dowry Prohibition Act, 1961', ['dowry prohibition act']),
    'ndps': ('Narcotic Drugs and Psychotropic Substances Act, 1985', ['ndps', 'ndps act']),
    'pmla': ('Prevention of Money Laundering Act, 2002', ['pmla']),
    'uapa': ('Unlawful Activities (Prevention) Act, 1967', ['uapa']),
}

# Old code <-> new code (2023 reforms). Section numbers are strings to allow '41A', '498A'.
OLD_TO_NEW = {
    ('crpc', 'bnss'): {
        '41': '35', '41A': '35', '154': '173', '156': '175', '161': '180', '164': '183',
        '167': '187', '170': '190', '173': '193', '200': '223', '313': '351', '436': '478',
        '436A': '479', '437': '480', '438': '482', '439': '483', '482': '528', '125': '144',
    },
    ('ipc', 'bns'): {
        '34': '3', '120B': '61', '299': '100', '300': '101', '302': '103', '304': '105',
        '304B': '80', '306': '108', '307': '109', '323': '115', '354': '74', '376': '64',
        '379': '303', '406': '316', '420': '318', '498A': '85', '506': '351', '509': '79',
    },
    ('iea', 'bsa'): {'45': '39', '65B': '63', '113A': '117', '113B': '118'},
}

# Concept phrases that strongly imply provisions (both regimes listed; used for recall only).
CONCEPTS = {
    'anticipatory bail': [('crpc', '438'), ('bnss', '482')],
    'pre-arrest bail': [('crpc', '438'), ('bnss', '482')],
    'regular bail': [('crpc', '439'), ('bnss', '483')],
    'cancellation of bail': [('crpc', '439'), ('crpc', '437')],
    'default bail': [('crpc', '167'), ('bnss', '187')],
    'dowry death': [('ipc', '304B'), ('bns', '80')],
    'cheque bounce': [('ni', '138')],
    'dishonour of cheque': [('ni', '138')],
    'breach of contract': [('ica', '73')],
    'personal liberty': [('coi', '21')],
}

# Lay phrasing -> statute phrasing (extra query variant terms).
SYNONYMS = {
    'chargesheet': 'charge-sheet charge sheet final report',
    'charge sheet': 'charge-sheet chargesheet final report',
    'fir': 'first information report',
    'pre-arrest bail': 'anticipatory bail',
    'damages': 'compensation loss',
    'surety': 'guarantee surety',
    'minor': 'age of majority competent to contract',
    'cheating': 'fraud dishonestly inducing',
    'definition': 'defined means',
    'define': 'defined means',
}


def act_mappings():
    """Bidirectional {(act, section): {(act, section), ...}}."""
    out = {}
    for (old, new), table in OLD_TO_NEW.items():
        for a, b in table.items():
            out.setdefault((old, a), set()).add((new, b))
            out.setdefault((new, b), set()).add((old, a))
    return out
