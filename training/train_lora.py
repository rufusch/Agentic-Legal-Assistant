"""LoRA / QLoRA SFT of the LexiMind chat model on sft.jsonl (backend.chat grounded-proposition format).

python training/train_lora.py --data datasets/<name>/sft.jsonl --out runs/chat-ft --dry-run
python training/train_lora.py --data datasets/<name>/sft.jsonl --out runs/chat-ft --epochs 2 --rank 16 --load-4bit

Heavy dependencies (torch, transformers, peft, trl, unsloth) are imported lazily so --dry-run works without them.
Uses Unsloth automatically when importable (faster, less VRAM), otherwise transformers + peft + trl.
Loss is computed on assistant tokens only. Never train on held-out eval rows: pass --eval-file to assert none leak.
Outputs: <out>/adapter (LoRA), <out>/merged (fp16 merged HF model for GGUF export), <out>/train_config.json.
"""
import argparse
import hashlib
import json
import random
from pathlib import Path

DEFAULT_MODEL = 'Qwen/Qwen3-4B-Instruct-2507'
TARGETS = ['q_proj', 'k_proj', 'v_proj', 'o_proj', 'gate_proj', 'up_proj', 'down_proj']


def load_rows(path, eval_file=None):
    rows, problems = [], []
    for n, line in enumerate(Path(path).read_text(encoding='utf-8-sig').splitlines(), 1):
        if not line.strip(): continue
        try: r = json.loads(line)
        except ValueError: problems.append(f'line {n}: invalid JSON'); continue
        m = r.get('messages')
        if not isinstance(m, list) or [x.get('role') for x in m][-1:] != ['assistant'] or not all(isinstance(x.get('content'), str) and x['content'] for x in m):
            problems.append(f'line {n}: needs messages[...] ending with a non-empty assistant turn'); continue
        try:
            answer = json.loads(m[-1]['content'])
            assert isinstance(answer.get('propositions'), list)
        except Exception: problems.append(f'line {n}: assistant content is not the {{"propositions": [...]}} JSON schema'); continue
        rows.append(r)
    if eval_file:
        held = set()
        for line in Path(eval_file).read_text(encoding='utf-8').splitlines():
            if line.strip():
                e = json.loads(line)
                if e.get('split') == 'heldout': held.add(e['id'])
        leaks = [r['meta']['eval_id'] for r in rows if r.get('meta', {}).get('eval_id') in held]
        if leaks: raise SystemExit(f'REFUSING TO TRAIN: {len(leaks)} held-out eval rows are in the SFT data, e.g. {leaks[:3]}')
    return rows, problems


def token_lengths(rows, model, offline_only):
    """Real tokenizer lengths when transformers + tokenizer files are available, else a ~3.2 chars/token estimate."""
    try:
        from transformers import AutoTokenizer
        tok = AutoTokenizer.from_pretrained(model, local_files_only=offline_only)
        return [len(tok.apply_chat_template(r['messages'], tokenize=True)) for r in rows], 'tokenizer'
    except Exception as exc:
        return [int(sum(len(m['content']) for m in r['messages']) / 3.2) + 8 * len(r['messages']) for r in rows], f'estimate ({type(exc).__name__})'


def pct(values, q): return sorted(values)[min(len(values) - 1, int(q * len(values)))] if values else 0


def train(args, rows):
    import torch
    try:
        if args.no_unsloth: raise ImportError
        from unsloth import FastLanguageModel  # noqa: F401  (must import before transformers)
        unsloth = True
    except Exception: unsloth = False
    from datasets import Dataset
    from trl import SFTConfig, SFTTrainer
    if args.load_4bit and not torch.cuda.is_available():
        print('No CUDA GPU: disabling 4-bit loading (bitsandbytes needs NVIDIA). Expect slow CPU training; see training/COLAB.md.')
        args.load_4bit = False
    bf16 = torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    fp16 = torch.cuda.is_available() and not bf16
    if unsloth:
        from unsloth import FastLanguageModel
        model, tok = FastLanguageModel.from_pretrained(args.model, max_seq_length=args.max_seq_len, load_in_4bit=args.load_4bit, dtype=None)
        model = FastLanguageModel.get_peft_model(model, r=args.rank, lora_alpha=args.alpha, lora_dropout=0, target_modules=TARGETS,
                                                 use_gradient_checkpointing='unsloth', random_state=args.seed)
    else:
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from transformers import AutoModelForCausalLM, AutoTokenizer
        tok = AutoTokenizer.from_pretrained(args.model)
        kw = {'dtype': torch.bfloat16 if bf16 else torch.float16 if fp16 else torch.float32}
        if args.load_4bit:
            from transformers import BitsAndBytesConfig
            kw['quantization_config'] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4', bnb_4bit_use_double_quant=True,
                                                           bnb_4bit_compute_dtype=torch.bfloat16 if bf16 else torch.float16)
            kw['device_map'] = 'auto'
        model = AutoModelForCausalLM.from_pretrained(args.model, **kw)
        if args.load_4bit: model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
        model = get_peft_model(model, LoraConfig(r=args.rank, lora_alpha=args.alpha, lora_dropout=args.dropout, target_modules=TARGETS, task_type='CAUSAL_LM'))
    if tok.pad_token is None: tok.pad_token = tok.eos_token
    random.Random(args.seed).shuffle(rows)
    n_eval = int(len(rows) * args.eval_frac) if len(rows) >= 20 else 0
    # Conversational prompt/completion: TRL masks the prompt (completion_only_loss), so only the JSON answer is learned.
    data = [{'prompt': r['messages'][:-1], 'completion': r['messages'][-1:]} for r in rows]
    train_ds, eval_ds = Dataset.from_list(data[n_eval:]), (Dataset.from_list(data[:n_eval]) if n_eval else None)
    cfg = dict(output_dir=str(Path(args.out) / 'checkpoints'), num_train_epochs=args.epochs, learning_rate=args.lr,
               per_device_train_batch_size=args.batch_size, gradient_accumulation_steps=args.grad_accum, lr_scheduler_type='cosine',
               logging_steps=5, save_strategy='epoch', save_total_limit=1, bf16=bf16, fp16=fp16, seed=args.seed,
               gradient_checkpointing=not unsloth, report_to='none',
               eval_strategy='epoch' if eval_ds is not None else 'no', per_device_eval_batch_size=args.batch_size)
    import inspect
    params = inspect.signature(SFTConfig.__init__).parameters
    cfg['max_length' if 'max_length' in params else 'max_seq_length'] = args.max_seq_len
    if 'eval_strategy' not in params: cfg['evaluation_strategy'] = cfg.pop('eval_strategy')
    if 'warmup_steps' in params: cfg['warmup_steps'] = max(1, int(0.05 * len(train_ds) * args.epochs / (args.batch_size * args.grad_accum)))
    if 'completion_only_loss' in params: cfg['completion_only_loss'] = True
    dropped = sorted(k for k in cfg if k not in params)
    if dropped: print('SFTConfig ignores unsupported options:', dropped)
    targs = SFTConfig(**{k: v for k, v in cfg.items() if k in params})
    kw = {'processing_class' if 'processing_class' in inspect.signature(SFTTrainer.__init__).parameters else 'tokenizer': tok}
    trainer = SFTTrainer(model=model, args=targs, train_dataset=train_ds, eval_dataset=eval_ds, **kw)
    trainer.train()
    out = Path(args.out)
    model.save_pretrained(out / 'adapter'); tok.save_pretrained(out / 'adapter')
    metrics = trainer.evaluate() if eval_ds is not None else {}
    if not args.no_merge:
        if unsloth: model.save_pretrained_merged(str(out / 'merged'), tok, save_method='merged_16bit')
        else:
            from peft import AutoPeftModelForCausalLM
            del model, trainer; torch.cuda.empty_cache() if torch.cuda.is_available() else None
            merged = AutoPeftModelForCausalLM.from_pretrained(out / 'adapter', dtype=torch.float16).merge_and_unload()
            merged.save_pretrained(out / 'merged', safe_serialization=True); tok.save_pretrained(out / 'merged')
    return {'backend': 'unsloth' if unsloth else 'transformers+peft+trl', 'eval_metrics': metrics, 'train_rows': len(train_ds), 'eval_rows': n_eval}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--data', required=True); p.add_argument('--out', default='runs/chat-ft')
    p.add_argument('--model', default=DEFAULT_MODEL); p.add_argument('--eval-file', help='eval.jsonl; asserts held-out ids are absent from --data')
    p.add_argument('--epochs', type=float, default=2); p.add_argument('--lr', type=float, default=2e-4)
    p.add_argument('--rank', type=int, default=16); p.add_argument('--alpha', type=int, default=32); p.add_argument('--dropout', type=float, default=0.05)
    p.add_argument('--max-seq-len', type=int, default=8192); p.add_argument('--batch-size', type=int, default=1); p.add_argument('--grad-accum', type=int, default=8)
    p.add_argument('--load-4bit', dest='load_4bit', action='store_true', default=True); p.add_argument('--no-4bit', dest='load_4bit', action='store_false')
    p.add_argument('--eval-frac', type=float, default=0.1, help='fraction of SFT rows held out for loss monitoring (not the judged held-out set)')
    p.add_argument('--drop-long', action='store_true', default=True, help='drop examples longer than --max-seq-len (truncation would cut the answer)')
    p.add_argument('--no-unsloth', action='store_true'); p.add_argument('--no-merge', action='store_true')
    p.add_argument('--seed', type=int, default=42); p.add_argument('--dry-run', action='store_true')
    args = p.parse_args(argv)
    rows, problems = load_rows(args.data, args.eval_file)
    if not rows: raise SystemExit('No valid SFT rows. ' + '; '.join(problems[:5]))
    lengths, method = token_lengths(rows, args.model, offline_only=args.dry_run)
    keep = [r for r, n in zip(rows, lengths) if n <= args.max_seq_len] if args.drop_long else rows
    abstain = sum(not json.loads(r['messages'][-1]['content'])['propositions'] for r in keep)
    steps = int(len(keep) * (1 - (args.eval_frac if len(keep) >= 20 else 0)) * args.epochs / (args.batch_size * args.grad_accum)) + 1
    plan = {'model': args.model, 'data': args.data, 'data_sha256': hashlib.sha256(Path(args.data).read_bytes()).hexdigest(),
            'rows_valid': len(rows), 'rows_invalid': len(problems), 'invalid_examples': problems[:5], 'rows_used': len(keep),
            'rows_dropped_too_long': len(rows) - len(keep), 'abstain_rows': abstain,
            'token_lengths': {'method': method, 'p50': pct(lengths, .5), 'p95': pct(lengths, .95), 'max': max(lengths)},
            'lora': {'rank': args.rank, 'alpha': args.alpha, 'dropout': args.dropout, 'targets': TARGETS}, 'load_4bit': args.load_4bit,
            'epochs': args.epochs, 'lr': args.lr, 'max_seq_len': args.max_seq_len, 'effective_batch': args.batch_size * args.grad_accum,
            'approx_optimizer_steps': steps, 'heldout_leak_check': 'passed' if args.eval_file else 'skipped (pass --eval-file)', 'out': args.out}
    if len(keep) < 50: plan['warning'] = 'Fewer than 50 examples: expect format learning only; consider 3-5 epochs and compare against the base model.'
    print(json.dumps(plan, indent=2))
    if args.dry_run: return plan
    Path(args.out).mkdir(parents=True, exist_ok=True)
    result = train(args, keep)
    (Path(args.out) / 'train_config.json').write_text(json.dumps({**plan, **result}, indent=2, default=str), encoding='utf-8')
    print(json.dumps(result, indent=2, default=str))
    return result


if __name__ == '__main__':
    main()
