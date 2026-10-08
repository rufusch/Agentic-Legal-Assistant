import json
import subprocess
import sys
from pathlib import Path

from backend.chat import SYSTEM, Answer
from scripts.ingest_corpus import rows
from scripts.ingest_dataset import main, mapping, locate, infer_metadata

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests' / 'fixtures' / 'dataset_sample'


def read(path): return [json.loads(l) for l in Path(path).read_text(encoding='utf-8').splitlines() if l.strip()]


def run(tmp_path, source, *extra):
    out = tmp_path / 'bundle'
    report = main([str(source), '--out', str(out), '--force', *extra])
    return out, report


def test_odd_csv_columns_map(tmp_path):
    cols = mapping(['Query Text', 'Model Answer', 'Supporting Passage', 'Source File', 'Split'], {})
    assert cols == {'question': 'Query Text', 'answer': 'Model Answer', 'context': 'Supporting Passage', 'doc': 'Source File', 'split': 'Split'}
    assert mapping(['Q', 'Resp', 'blob'], {'context': 'blob', 'answer': 'Resp'})['context'] == 'blob'
    out, report = run(tmp_path, FIXTURE)
    ev = {r['question']: r for r in read(out / 'eval.jsonl')}
    custody = ev['How long had the applicant been in custody?']
    assert custody['gold'][0]['doc'].endswith('synthetic_bail_order.txt') and custody['split'] == 'dev'  # from Split=train
    # whitespace-normalized match records the exact parsed substring
    amount = ev['What amount does the prosecution allege the applicant received?']['gold'][0]['quote']
    assert amount == 'The prosecution alleges that the applicant received Rs. 2,50,000 from the complainant.'
    assert report['counts']['gold_match_normalized'] >= 1
    for row in read(out / 'eval.jsonl'):
        doc = (out / row['documents'][0]).read_text(encoding='utf-8') if row['documents'] else ''
        assert all(g['quote'] in (out / g['doc']).read_text(encoding='utf-8') for g in row['gold'])
    assert len(list(rows(out / 'manifest.jsonl'))) == report['documents'] == 2  # loadable by ingest_corpus


def test_jsonl_qa_to_eval_and_sft(tmp_path):
    out, report = run(tmp_path, FIXTURE, '--heldout-frac', '0', '--ignore-source-splits')
    sft = read(out / 'sft.jsonl'); ev = read(out / 'eval.jsonl')
    assert {'j1', 'j2', 'j3'} <= {r['id'] for r in ev} and all(r['split'] == 'dev' for r in ev)
    j3 = next(r for r in ev if r['id'] == 'j3'); assert j3['answerable'] is False and j3['gold'] == []
    by = {r['meta']['eval_id']: r for r in sft}
    assert {'j1', 'j2', 'j3'} <= set(by)
    for r in sft:
        system, user, assistant = r['messages']
        assert system['content'] == SYSTEM
        packet = {s['source_id']: s for s in json.loads(user['content'])['sources']}
        answer = Answer.model_validate_json(assistant['content'])
        for p in answer.propositions: assert set(p.source_ids) <= set(packet)
    j2 = Answer.model_validate_json(by['j2']['messages'][2]['content']).propositions[0]
    assert j2.kind == 'legal' and 'non-serious offence' in json.loads(by['j2']['messages'][1]['content'])['sources'][int(j2.source_ids[0][1:]) - 1]['text']
    assert Answer.model_validate_json(by['j3']['messages'][2]['content']).propositions == []
    flagged = {r['id'] for r in read(out / 'eval_flagged.jsonl')}
    assert 'j4' in flagged and 'j4' not in by  # unsupported answer never becomes training data


def test_gold_quote_not_found_is_flagged(tmp_path):
    out, report = run(tmp_path, FIXTURE)
    flagged = read(out / 'eval_flagged.jsonl')
    bond = next(r for r in flagged if r['question'].startswith('What is the personal bond'))
    assert bond['flags'] == ['gold_quote_not_found'] and bond['gold'] == []
    assert bond['id'] not in {r['id'] for r in read(out / 'eval.jsonl')}
    assert report['counts']['eval_flag_gold_quote_not_found'] == 1
    assert locate('remained   in custody\nfor 71 days', [(1, 'has remained in custody for 71 days.')])[3] == 'remained in custody for 71 days'


def test_heldout_never_leaks_into_sft(tmp_path):
    src = tmp_path / 'src'; src.mkdir()
    data = [{'id': f'r{i}', 'question': f'What period applies in example {i}?', 'answer': f'The period is {30 + i} days.',
             'context': f'Example rule {i}. The period is {30 + i} days after the order.'} for i in range(40)]
    data.append({'id': 'dup', 'question': 'What period applies in example 0?', 'answer': 'The period is 30 days.', 'context': 'Example rule 0. The period is 30 days after the order.'})
    (src / 'qa.json').write_text(json.dumps(data), encoding='utf-8')
    out, report = run(tmp_path, src, '--heldout-frac', '0.5', '--group-by', 'id')
    ev = read(out / 'eval.jsonl'); sft = read(out / 'sft.jsonl')
    held = {r['id'] for r in ev if r['split'] == 'heldout'}
    held_q = {r['question'] for r in ev if r['split'] == 'heldout'}
    assert held and sft and report['heldout_leak_check'] == 'passed'
    assert not held & {r['meta']['eval_id'] for r in sft}
    assert not held_q & {json.loads(r['messages'][1]['content'])['question'] for r in sft}
    assert report['counts']['qa_duplicates_dropped'] == 1
    again = read(run(tmp_path / 'b', src, '--heldout-frac', '0.5', '--group-by', 'id')[0] / 'eval.jsonl')
    assert [r['split'] for r in again] == [r['split'] for r in ev]  # deterministic


def test_directory_adapter_infers_judgment_metadata(tmp_path):
    src = tmp_path / 'docs'; src.mkdir()
    (src / 'order.txt').write_text('IN THE SUPREME COURT OF INDIA\nCRIMINAL APPELLATE JURISDICTION\n2024 INSC 999\nA. PERSON ...Appellant\nVERSUS\nSTATE OF EXAMPLE ...Respondent\n'
                                   'JUDGMENT\n1. The appellant seeks bail.\nNEW DELHI\n5th March 2024\n', encoding='utf-8')
    (src / 'page.html').write_text('<html><body><h1>THE EXAMPLE ACT, 2001</h1><p>BE IT ENACTED as follows.</p><p>1. Short title.</p><script>x()</script></body></html>', encoding='utf-8')
    out, report = run(tmp_path, src, '--metadata-defaults', 'jurisdiction=IN')
    meta = {Path(r['path']).name: r['metadata'] for r in read(out / 'manifest.jsonl')}
    j = meta['order.txt']
    assert j['document_type'] == 'judgment' and j['court'] == 'Supreme Court of India' and j['neutral_citation'] == '2024 INSC 999'
    assert j['decided_at'] == '2024-03-05' and j['title'] == 'A. PERSON v. STATE OF EXAMPLE' and 'court' in j['metadata_inferred']
    h = meta['page.txt']
    assert h['document_type'] == 'statute' and h['converted_from'] == 'page.html' and 'x()' not in (out / 'documents/page.txt').read_text(encoding='utf-8')
    assert infer_metadata('(2014) 8 SCC 273 Petitioner versus Respondent JUDGMENT', 'a.txt')['citation'] == '(2014) 8 SCC 273'
    assert len(list(rows(out / 'manifest.jsonl'))) == 2


def test_train_lora_dry_run_without_torch(tmp_path):
    out, _ = run(tmp_path, FIXTURE, '--heldout-frac', '0', '--ignore-source-splits')
    script = ROOT / 'training' / 'train_lora.py'
    code = ('import sys, runpy; sys.modules["torch"] = None; sys.modules["transformers"] = None; '
            f'sys.argv = ["train_lora.py", "--data", {str(out / "sft.jsonl")!r}, "--eval-file", {str(out / "eval.jsonl")!r}, "--dry-run"]; '
            f'runpy.run_path({str(script)!r}, run_name="__main__")')
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan['rows_used'] >= 3 and plan['heldout_leak_check'] == 'passed' and plan['token_lengths']['method'].startswith('estimate')
    # a leaked held-out row must stop training
    ev = read(out / 'eval.jsonl'); ev[0]['split'] = 'heldout'
    sft_ids = {r['meta']['eval_id'] for r in read(out / 'sft.jsonl')}
    ev = [dict(r, split='heldout') if r['id'] in sft_ids else r for r in ev]
    (out / 'eval.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in ev), encoding='utf-8')
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=120)
    assert result.returncode != 0 and 'REFUSING TO TRAIN' in result.stderr
