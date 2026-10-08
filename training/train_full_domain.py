"""One streaming epoch over every training row, with resumable adapter/optimizer checkpoints.

This is domain adaptation; no workflow-specialist competence is implied.
"""
import argparse
import hashlib
import json
from pathlib import Path
import random
import time


def blocks(folder, tokenizer, length, cursor=None, split='train'):
    cursor = cursor or {'shard': 0, 'line': 0, 'block': 0}
    for si, path in enumerate(sorted(folder.glob('part-*.jsonl'))):
        if si < cursor['shard']: continue
        with path.open(encoding='utf-8') as stream:
            for li, line in enumerate(stream):
                if si == cursor['shard'] and li < cursor['line']: continue
                row = json.loads(line)
                if row['split'] != split: continue
                tokens = tokenizer.encode(row['text'], add_special_tokens=False) + [tokenizer.eos_token_id]
                for bi, start in enumerate(range(0, len(tokens), length)):
                    if si == cursor['shard'] and li == cursor['line'] and bi < cursor['block']: continue
                    block = tokens[start:start+length]
                    if len(block) >= 2:
                        yield block, {'shard': si, 'line': li, 'block': bi+1}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--corpus', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--model', default='.runtime/training-base-qwen4b')
    p.add_argument('--checkpoint-every', type=int, default=100)
    p.add_argument('--sequence-length', type=int, default=256)
    p.add_argument('--gradient-accumulation', type=int, default=4)
    p.add_argument('--resume', action='store_true')
    p.add_argument('--max-steps', type=int, help='Optional segmented run limit; never marks the full epoch complete.')
    a = p.parse_args()
    if min(a.checkpoint_every,a.sequence_length,a.gradient_accumulation) <= 0: p.error('Positive settings required.')
    if a.max_steps is not None and a.max_steps<=0:p.error('max-steps must be positive.')
    manifest_path = a.corpus / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    if not manifest.get('complete'): raise SystemExit('Full corpus preparation is incomplete.')
    if sorted(manifest['shards']) != [p.name for p in sorted(a.corpus.glob('part-*.jsonl'))]:
        raise SystemExit('Corpus shard list differs from its manifest.')
    for name,expected in manifest.get('shard_sha256',{}).items():
        if Path(name).name!=name:raise SystemExit('Invalid corpus shard path.')
        digest=hashlib.sha256()
        with (a.corpus/name).open('rb') as stream:
            for part in iter(lambda:stream.read(8*1024*1024),b''):digest.update(part)
        if digest.hexdigest()!=expected:raise SystemExit('Corpus shard checksum mismatch.')
    identity = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    a.out.mkdir(parents=True,exist_ok=a.resume)
    status = {'complete':False,'objective':'one full streaming domain-adaptation epoch',
              'corpus_manifest_sha256':identity,'model':a.model,'steps':0,'tokens':0,
              'sequence_length':a.sequence_length,'gradient_accumulation':a.gradient_accumulation,
              'production_activated':False,'trained_workflow_specialists':[],
              'cursor':{'shard':0,'line':0,'block':0}}
    def save_status():
        temp=a.out/'status.tmp';temp.write_text(json.dumps(status,indent=2));temp.replace(a.out/'status.json')
    save_status()
    try:
        import torch
        from transformers import AutoModelForCausalLM,AutoTokenizer
        from peft import LoraConfig,get_peft_model,prepare_model_for_kbit_training,PeftModel
        if not torch.cuda.is_available(): raise RuntimeError('CUDA is required.')
        torch.manual_seed(42);random.seed(42)
        checkpoint=None
        if a.resume:
            checkpoint=a.out/json.loads((a.out/'latest.json').read_text())['checkpoint']
            previous=json.loads((checkpoint/'state.json').read_text())
            for key in ('corpus_manifest_sha256','model','sequence_length','gradient_accumulation'):
                if previous[key]!=status[key]: raise ValueError('Checkpoint settings or corpus do not match.')
            status=previous;status['complete']=False;status.pop('error_type',None)
        tokenizer=AutoTokenizer.from_pretrained(a.model,local_files_only=True)
        model=AutoModelForCausalLM.from_pretrained(a.model,local_files_only=True,device_map={'':0},
            dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16,attn_implementation='sdpa')
        model.config.use_cache=False
        model=prepare_model_for_kbit_training(model,gradient_checkpointing_kwargs={'use_reentrant':False})
        model=PeftModel.from_pretrained(model,checkpoint/'adapter',is_trainable=True) if checkpoint else get_peft_model(model,
            LoraConfig(r=8,lora_alpha=16,lora_dropout=.05,target_modules=['q_proj','v_proj'],task_type='CAUSAL_LM'))
        optimizer=torch.optim.AdamW([v for v in model.parameters() if v.requires_grad],lr=5e-5)
        if checkpoint:
            saved=torch.load(checkpoint/'optimizer.pt',weights_only=True,map_location='cpu')
            optimizer.load_state_dict(saved['optimizer'])
            torch.set_rng_state(saved['cpu_rng']);torch.cuda.set_rng_state(saved['cuda_rng'])
        def loss(block):
            x=torch.tensor([block],device='cuda',dtype=torch.long)
            value=model(input_ids=x,attention_mask=torch.ones_like(x),labels=x).loss
            if not torch.isfinite(value): raise RuntimeError('Non-finite training loss.')
            return value
        def evaluate():
            model.eval();values=[]
            with torch.no_grad():
                for block,_ in blocks(a.corpus,tokenizer,a.sequence_length,split='validation'):
                    values.append(float(loss(block)))
                    if len(values)>=16:break
            model.train()
            return sum(values)/len(values) if values else None
        if not checkpoint:
            with model.disable_adapter(): status['base_validation_loss']=evaluate()
        def save_checkpoint():
            name=f"checkpoint-{status['steps']:09d}"
            from uuid import uuid4
            target=a.out/name;temp=a.out/(name+'.'+uuid4().hex+'.tmp');temp.mkdir()
            model.save_pretrained(temp/'adapter');tokenizer.save_pretrained(temp/'adapter')
            torch.save({'optimizer':optimizer.state_dict(),'cpu_rng':torch.get_rng_state(),
                        'cuda_rng':torch.cuda.get_rng_state()},temp/'optimizer.pt')
            (temp/'state.json').write_text(json.dumps(status,indent=2))
            temp.replace(target)
            pointer=a.out/'latest.tmp';pointer.write_text(json.dumps({'checkpoint':name}));pointer.replace(a.out/'latest.json')
            save_status()
            # Retain two completed optimizer checkpoints, never delete the latest on failure.
            import shutil
            finished=[d for d in sorted(a.out.glob('checkpoint-*')) if d.is_dir() and not d.name.endswith('.tmp')]
            for old in finished[:-2]:
                if old.resolve().parent!=a.out.resolve() or old.is_symlink():raise RuntimeError('Checkpoint cleanup path is outside the run directory.')
                shutil.rmtree(old)
        model.train();optimizer.zero_grad(set_to_none=True);micro=0;total_loss=0
        started=time.monotonic()
        stream=blocks(a.corpus,tokenizer,a.sequence_length,status['cursor'])
        exhausted=False
        while not exhausted:
            batch=[]
            for _ in range(a.gradient_accumulation):
                try:batch.append(next(stream))
                except StopIteration:exhausted=True;break
            if not batch:break
            optimizer.zero_grad(set_to_none=True);total_loss=0
            for block,cursor in batch:
                value=loss(block);total_loss+=float(value.detach())
                (value/len(batch)).backward();status['tokens']+=len(block)
            torch.nn.utils.clip_grad_norm_([v for v in model.parameters() if v.requires_grad],1,error_if_nonfinite=True)
            optimizer.step();status['steps']+=1;status['cursor']=cursor
            status['last_loss']=total_loss/len(batch);status['current_process_seconds']=time.monotonic()-started
            save_status()
            if status['steps']%10==0:print(json.dumps(status),flush=True)
            if status['steps']%a.checkpoint_every==0:save_checkpoint()
            if a.max_steps is not None and status['steps']>=a.max_steps:
                if status['steps']%a.checkpoint_every:save_checkpoint()
                status['stage']='segment_limit_reached';save_status();return
        status['adapter_validation_loss']=evaluate();status['complete']=True
        # Avoid overwriting a checkpoint made on the exact final step.
        final=a.out/'final-adapter';model.save_pretrained(final);tokenizer.save_pretrained(final)
        save_status();print(json.dumps(status),flush=True)
    except BaseException as exc:
        status['complete']=False;status['error_type']=type(exc).__name__;save_status();raise


if __name__=='__main__':main()
