import json
from scripts.ingest_corpus import rows
from backend.parsing import extract, ParseFailure
import pytest

def test_manifest_versions_and_hashes(tmp_path):
    (tmp_path/'law.txt').write_text('Source excerpt',encoding='utf-8')
    manifest=tmp_path/'sources.jsonl';meta={'corpus_id':'laws','corpus_version':'v1','document_type':'statute','jurisdiction':'IN'}
    manifest.write_text(json.dumps({'path':'law.txt','metadata':meta})+'\n',encoding='utf-8')
    first=list(rows(manifest))[0]
    meta['corpus_version']='v2';manifest.write_text(json.dumps({'path':'law.txt','metadata':meta}),encoding='utf-8')
    second=list(rows(manifest))[0]
    assert first[2]==second[2] and first[3]!=second[3]
    meta.pop('jurisdiction');manifest.write_text(json.dumps({'path':'law.txt','metadata':meta}),encoding='utf-8')
    with pytest.raises(ValueError):list(rows(manifest))

def test_legacy_doc_capability_and_invalid_content(monkeypatch):
    monkeypatch.setattr('shutil.which',lambda _:None)
    with pytest.raises(ParseFailure) as e:extract(b'fake','application/msword')
    assert e.value.code=='DOC_PARSER_UNAVAILABLE'
    monkeypatch.setattr('shutil.which',lambda _:'antiword')
    with pytest.raises(ParseFailure) as e:extract(b'fake','application/msword')
    assert e.value.code=='INVALID_CONTENT'
