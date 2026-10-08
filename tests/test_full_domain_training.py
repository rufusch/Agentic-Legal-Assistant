import json
from training.train_full_domain import blocks


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
