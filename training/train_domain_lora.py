"""Small legal-text adaptation trial. This does NOT train workflow output schemas.

Input JSONL: {text, document_id, split: train|validation|test, provenance}.
The untouched test split is never read by the optimizer or validation routine.
"""
import argparse
import hashlib
import json
from pathlib import Path
import random
import time


def load_corpus(path):
    rows = [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]
    ids, hashes = {}, {}
    for row in rows:
        if row.get('split') not in {'train', 'validation', 'test'} or not row.get('document_id') or not isinstance(row.get('text'), str) or not row['text'].strip():
            raise ValueError('Every row needs text, document_id and a valid split.')
        digest = hashlib.sha256(' '.join(row['text'].split()).encode()).hexdigest()
        for mapping, key in ((ids, row['document_id']), (hashes, digest)):
            previous = mapping.setdefault(key, row['split'])
            if previous != row['split']:
                raise ValueError('Document or identical text appears across splits; refusing training.')
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--model', default='unsloth/Qwen3-4B-Instruct-2507-bnb-4bit')
    parser.add_argument('--revision', required=True)
    parser.add_argument('--steps', type=int, default=32)
    parser.add_argument('--sequence-length', type=int, default=256)
    parser.add_argument('--gradient-accumulation', type=int, default=4)
    parser.add_argument('--learning-rate', type=float, default=5e-5)
    parser.add_argument('--max-training-blocks', type=int, default=1024)
    parser.add_argument('--max-validation-blocks', type=int, default=16)
    args = parser.parse_args()
    if min(args.steps, args.sequence_length, args.gradient_accumulation, args.max_training_blocks, args.max_validation_blocks) <= 0:
        parser.error('Steps, sequence length and accumulation must be positive.')
    rows = load_corpus(args.data)
    if not any(r['split'] == 'train' for r in rows) or not any(r['split'] == 'validation' for r in rows):
        raise SystemExit('Separate training and validation documents are required.')
    args.out.mkdir(parents=True, exist_ok=False)
    status = {'complete': False, 'objective': 'raw legal-text causal language modeling; feasibility pilot only',
              'model': args.model, 'revision': args.revision, 'data_file': str(args.data), 'data_sha256': hashlib.sha256(args.data.read_bytes()).hexdigest(),
              'requested_steps': args.steps, 'sequence_length': args.sequence_length,
              'gradient_accumulation': args.gradient_accumulation, 'learning_rate': args.learning_rate,
              'max_training_blocks': args.max_training_blocks, 'max_validation_blocks': args.max_validation_blocks,
              'trained_workflow_specialists': [], 'production_activated': False}
    def save_status():
        (args.out / 'status.json').write_text(json.dumps(status, indent=2), encoding='utf-8')
    save_status()
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        if not torch.cuda.is_available():
            raise RuntimeError('CUDA unavailable; refusing unintended full-size CPU training.')
        torch.manual_seed(42)
        random.seed(42)
        status['gpu'] = torch.cuda.get_device_name(0)
        status['torch_version'] = torch.__version__
        print('Loading pinned quantized 4B base...', flush=True)
        tokenizer = AutoTokenizer.from_pretrained(args.model, revision=args.revision)
        compute_dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        model = AutoModelForCausalLM.from_pretrained(args.model, revision=args.revision,
            device_map={'': 0}, dtype=compute_dtype, attn_implementation='sdpa')
        model.config.use_cache = False
        model = prepare_model_for_kbit_training(model, gradient_checkpointing_kwargs={'use_reentrant': False})
        model = get_peft_model(model, LoraConfig(r=8, lora_alpha=16, lora_dropout=0.05,
            target_modules=['q_proj', 'v_proj'], task_type='CAUSAL_LM'))
        sequences = {'train': [], 'validation': []}
        random.shuffle(rows)
        limits = {'train': args.max_training_blocks, 'validation': args.max_validation_blocks}
        validation_documents = set()
        for row in rows:
            if row['split'] not in sequences:
                continue
            if len(sequences[row['split']]) >= limits[row['split']]:
                continue
            if row['split'] == 'validation' and row['document_id'] in validation_documents:
                continue
            tokens = tokenizer.encode(row['text'], add_special_tokens=False) + [tokenizer.eos_token_id]
            for start in range(0, len(tokens), args.sequence_length):
                block = tokens[start:start + args.sequence_length]
                if len(block) >= 32:
                    sequences[row['split']].append(block)
                    if row['split'] == 'validation':
                        validation_documents.add(row['document_id'])
                        break
                if len(sequences[row['split']]) >= limits[row['split']]:
                    break
        if not all(sequences.values()):
            raise ValueError('No usable token blocks in training or validation.')
        status['token_blocks'] = {k: len(v) for k, v in sequences.items()}
        status['validation_documents'] = len(validation_documents)
        def loss_for(block):
            x = torch.tensor([block], device='cuda', dtype=torch.long)
            loss = model(input_ids=x, attention_mask=torch.ones_like(x), labels=x).loss
            if not torch.isfinite(loss):
                raise RuntimeError('Non-finite loss; refusing to save an invalid adapter.')
            return loss
        def evaluate():
            model.eval()
            with torch.no_grad():
                losses = [float(loss_for(block)) for block in sequences['validation'][:16]]
            return sum(losses) / len(losses)
        with model.disable_adapter():
            status['base_validation_loss'] = evaluate()
        save_status()
        optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=args.learning_rate)
        model.train()
        model.print_trainable_parameters()
        blocks = sequences['train']
        random.shuffle(blocks)
        started = time.monotonic()
        with (args.out / 'progress.jsonl').open('w', encoding='utf-8') as stream:
            for step in range(args.steps):
                optimizer.zero_grad(set_to_none=True)
                losses = []
                for micro in range(args.gradient_accumulation):
                    block = blocks[(step * args.gradient_accumulation + micro) % len(blocks)]
                    loss = loss_for(block)
                    losses.append(float(loss.detach()))
                    (loss / args.gradient_accumulation).backward()
                torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0, error_if_nonfinite=True)
                optimizer.step()
                record = {'step': step + 1, 'loss': sum(losses) / len(losses)}
                stream.write(json.dumps(record) + '\n'); stream.flush()
                print(record, flush=True)
                status['completed_steps'] = step + 1
                save_status()
        status['adapter_validation_loss'] = evaluate()
        status['training_and_validation_seconds'] = time.monotonic() - started
        status['peak_gpu_allocated_bytes'] = torch.cuda.max_memory_allocated()
        model.save_pretrained(args.out / 'adapter')
        tokenizer.save_pretrained(args.out / 'adapter')
        status['complete'] = True
        save_status()
        print(json.dumps(status, indent=2), flush=True)
    except Exception as exc:
        status['error_type'] = type(exc).__name__
        save_status()
        raise


if __name__ == '__main__':
    main()
