import json
import hashlib
import pytest
from training.train_full_domain import blocks
from training.train_full_domain import prepared_shards


class Tokenizer:
    eos_token_id=99
    def encode(self,text,**kwargs):return list(range(len(text.split())))


def test_stream_resume_exactly_continues_after_last_committed_block(tmp_path):
    rows=[{'text':'a b c d e f','split':'train'}, {'text':'never train this','split':'test'},
          {'text':'another training source with words','split':'train'}]
    (tmp_path/'part-000000.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
    all_blocks=list(blocks(tmp_path,Tokenizer(),3))
    assert len(all_blocks)==4
    assert list(blocks(tmp_path,Tokenizer(),3,all_blocks[0][1]))==all_blocks[1:]
    assert list(blocks(tmp_path,Tokenizer(),3,all_blocks[-1][1]))==[]
    assert list(blocks(tmp_path,Tokenizer(),3,split='validation'))==[]


def test_live_preparation_consumes_only_published_shards(tmp_path, monkeypatch):
    raw=b'{"text":"a b c", "split":"train"}\n'
    (tmp_path/'part-000000.jsonl').write_bytes(raw)
    (tmp_path/'part-000001.jsonl').write_text('incomplete active write')
    manifest={'complete':False,'shard_sha256':{'part-000000.jsonl':hashlib.sha256(raw).hexdigest()}}
    path=tmp_path/'manifest.json';path.write_text(json.dumps(manifest))
    stream=prepared_shards(tmp_path)
    assert next(stream).name=='part-000000.jsonl'
    def finish(_):
        (tmp_path/'part-000001.jsonl').write_bytes(raw)
        manifest.update(complete=True,shards=['part-000000.jsonl','part-000001.jsonl'])
        manifest['shard_sha256']['part-000001.jsonl']=hashlib.sha256(raw).hexdigest()
        path.write_text(json.dumps(manifest))
    monkeypatch.setattr('training.train_full_domain.time.sleep',finish)
    assert [p.name for p in stream]==['part-000001.jsonl']


def test_live_preparation_rejects_corrupted_shard(tmp_path):
    (tmp_path/'part-000000.jsonl').write_bytes(b'corrupted')
    (tmp_path/'manifest.json').write_text(json.dumps({'complete':False,'shard_sha256':{'part-000000.jsonl':'0'*64}}))
    with pytest.raises(ValueError,match='checksum mismatch'):
        next(prepared_shards(tmp_path))
