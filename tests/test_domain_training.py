import json
import pytest
from training.prepare_domain_corpus import convert
from training.train_domain_lora import load_corpus


def test_metadata_only_is_not_legal_text():
    assert convert({'case_metadata_id': 'case1', 'indexable_text': 'Metadata ' * 100}, 'file') is None


def test_act_sections_stay_in_one_split():
    a = convert({'act_id': 'act1', 'text': 'First provision ' * 30}, 'file')
    b = convert({'act_id': 'act1', 'text': 'Second provision ' * 30}, 'file')
    assert a['document_id'] == b['document_id'] and a['split'] == b['split']


def test_judgment_chunks_stay_in_one_split():
    a = convert({'case_id': 'SKHC1', 'chunk_id': 'SKHC1_000', 'text': 'First judgment passage ' * 30}, 'file')
    b = convert({'case_id': 'SKHC1', 'chunk_id': 'SKHC1_001', 'text': 'Second judgment passage ' * 30}, 'file')
    assert a['document_id'] == b['document_id'] and a['split'] == b['split']
    assert a['provenance']['field'] == 'text'


@pytest.mark.parametrize('shared', ['document', 'text'])
def test_cross_split_leakage_refuses_training(tmp_path, shared):
    rows = [{'document_id': 'a', 'text': 'first passage', 'split': 'train'},
            {'document_id': 'a' if shared == 'document' else 'b',
             'text': 'second passage' if shared == 'document' else 'first  passage', 'split': 'test'}]
    path = tmp_path / 'corpus.jsonl'
    path.write_text('\n'.join(json.dumps(r) for r in rows))
    with pytest.raises(ValueError, match='across splits'):
        load_corpus(path)
