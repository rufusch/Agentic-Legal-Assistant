from uuid import uuid4

import pytest

from backend.evidence import EvidenceBundle


def bundle():
    citation_id = str(uuid4())
    return {'citations': [{'id': citation_id, 'label': 'S1', 'document_id': str(uuid4()), 'document_name': 'contract.txt', 'chunk_id': str(uuid4()), 'quoted_text': 'Payment due', 'start_offset': 100, 'end_offset': 111}], 'claims': [{'id': str(uuid4()), 'text': 'Payment due', 'citation_ids': [citation_id], 'verification_status': 'supported', 'confidence': 0.9}]}


def test_exact_quote_and_offsets():
    evidence = EvidenceBundle.model_validate(bundle())
    def load(document_id, chunk_id):
        return {'document_id': document_id, 'text': 'Payment due in October.', 'start_offset': 100}
    evidence.validate_source_spans(load)
    evidence.citations[0].quoted_text = 'Payment due in November.'
    with pytest.raises(ValueError, match='exact stored span'):
        evidence.validate_source_spans(load)


@pytest.mark.parametrize('mutation', ['unsupported', 'dangling', 'uncited'])
def test_final_claim_gate(mutation):
    data = bundle()
    if mutation == 'unsupported':
        data['claims'][0]['verification_status'] = 'unsupported'
    elif mutation == 'dangling':
        data['claims'][0]['citation_ids'] = [str(uuid4())]
    else:
        data['claims'][0]['citation_ids'] = []
    with pytest.raises(ValueError):
        EvidenceBundle.model_validate(data)
