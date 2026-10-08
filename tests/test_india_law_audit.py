import pytest
from training.audit_india_law import audit_record, split_for


def test_case_identity_keeps_multiple_rows_in_one_split():
    a = audit_record({'case_metadata_id': 'same-case', 'id': 1})
    b = audit_record({'case_metadata_id': 'same-case', 'id': 2})
    assert a['split'] == b['split'] == split_for('same-case')


def test_headnote_is_not_a_supervised_target():
    record = audit_record({'id': 3, 'headnote_text': 'Judgment source passage', 'quality_json': '{bad'})
    assert not record['supervised_training_ready']
    assert record['headnote_characters'] > 0
    assert record['quality']['invalid_json']


def test_missing_identity_is_rejected():
    with pytest.raises(ValueError, match='identifier'):
        audit_record({})
