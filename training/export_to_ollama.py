"""Merged HF model -> GGUF -> Ollama model usable by the app (LEXIMIND_CHAT_LLM_MODEL=<name>).

python training/export_to_ollama.py --merged runs/chat-ft/merged --name leximind-chat-ft [--quant q4_K_M] [--dry-run]

Steps (each skipped when its output already exists; --dry-run prints them only):
 1. git clone --depth 1 https://github.com/ggml-org/llama.cpp (or use --llama-cpp DIR) and
    pip install -r llama.cpp/requirements/requirements-convert_hf_to_gguf.txt
 2. python llama.cpp/convert_hf_to_gguf.py <merged> --outfile <out>/model-f16.gguf --outtype f16
 3. Quantize: `llama-quantize` if on PATH (or --llama-quantize), otherwise Ollama quantizes during create.
 4. Write <out>/Modelfile (Qwen ChatML template, temperature 0, num_ctx 16384) and run
    ollama create <name> -f Modelfile [--quantize q4_K_M]
Works on Windows/macOS/Linux; no shell features are used. Requires `ollama` on PATH for step 4.
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

LLAMA_REPO = 'https://github.com/ggml-org/llama.cpp'
# Qwen ChatML template. System prompt comes from the app's messages (no SYSTEM baked in), so the
# fine-tuned model sees exactly the prompt format it was trained on.
TEMPLATE = '''{{- if .System }}<|im_start|>system
{{ .System }}<|im_end|>
{{ end }}{{- range $i, $_ := .Messages }}{{- $last := eq (len (slice $.Messages $i)) 1 }}{{- if eq .Role "user" }}<|im_start|>user
{{ .Content }}<|im_end|>
{{ else if eq .Role "assistant" }}<|im_start|>assistant
{{ .Content }}{{ if not $last }}<|im_end|>
{{ end }}{{ end }}{{- if and (ne .Role "assistant") $last }}<|im_start|>assistant
{{ end }}{{- end }}'''


def modelfile(gguf_name, ctx):
    return (f'FROM ./{gguf_name}\n'
            f'TEMPLATE """{TEMPLATE}"""\n'
            'PARAMETER temperature 0\n'
            f'PARAMETER num_ctx {ctx}\n'
            'PARAMETER stop "<|im_end|>"\n'
            'PARAMETER stop "<|im_start|>"\n'
            'PARAMETER stop "<|endoftext|>"\n')


def run(cmd, dry, cwd=None):
    print('$ ' + ' '.join(map(str, cmd)) + (f'   (in {cwd})' if cwd else ''), flush=True)
    if not dry: subprocess.run(list(map(str, cmd)), check=True, cwd=cwd)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--merged', required=True, help='merged HF model directory from train_lora.py (<out>/merged)')
    p.add_argument('--name', default='leximind-chat-ft'); p.add_argument('--out', help='GGUF/Modelfile directory (default <merged>/../gguf)')
    p.add_argument('--quant', default='q4_K_M', help='q4_K_M (default), q5_K_M, q8_0, or f16 for none')
    p.add_argument('--llama-cpp', help='existing llama.cpp checkout (default: clone into <out>/../llama.cpp)')
    p.add_argument('--llama-quantize', help='path to llama-quantize binary (optional)')
    p.add_argument('--ctx', type=int, default=16384, help='matches backend num_ctx')
    p.add_argument('--skip-ollama', action='store_true'); p.add_argument('--dry-run', action='store_true')
    args = p.parse_args(argv)
    merged = Path(args.merged).resolve(); out = Path(args.out or merged.parent / 'gguf').resolve()
    if not args.dry_run and not (merged / 'config.json').exists(): raise SystemExit(f'{merged} is not a merged HF model (no config.json)')
    out.mkdir(parents=True, exist_ok=True) if not args.dry_run else None
    llama = Path(args.llama_cpp).resolve() if args.llama_cpp else out.parent / 'llama.cpp'
    if not (llama / 'convert_hf_to_gguf.py').exists():
        run(['git', 'clone', '--depth', '1', LLAMA_REPO, llama], args.dry_run)
        run([sys.executable, '-m', 'pip', 'install', '-r', llama / 'requirements' / 'requirements-convert_hf_to_gguf.txt'], args.dry_run)
    f16 = out / 'model-f16.gguf'
    if not f16.exists(): run([sys.executable, llama / 'convert_hf_to_gguf.py', merged, '--outfile', f16, '--outtype', 'f16'], args.dry_run)
    gguf, ollama_quant = f16, None
    quantize = args.llama_quantize or shutil.which('llama-quantize')
    if args.quant.lower() != 'f16':
        if quantize:
            gguf = out / f'model-{args.quant}.gguf'
            if not gguf.exists(): run([quantize, f16, gguf, args.quant.upper()], args.dry_run)
        else: ollama_quant = args.quant  # Ollama can quantize an F16 GGUF itself
    text = modelfile(gguf.name, args.ctx)
    print(f'--- {out / "Modelfile"}\n{text}---')
    if not args.dry_run: (out / 'Modelfile').write_text(text, encoding='utf-8')
    if not args.skip_ollama:
        if not args.dry_run and not shutil.which('ollama'): raise SystemExit('ollama not on PATH; install it or rerun with --skip-ollama and copy the gguf folder to a machine with Ollama')
        run(['ollama', 'create', args.name, '-f', 'Modelfile'] + (['--quantize', ollama_quant] if ollama_quant else []), args.dry_run, cwd=out)
    print(f'\nDone. Point the app at it (PowerShell):\n  $env:LEXIMIND_CHAT_LLM_MODEL = "{args.name}"\n'
          f'  (bash: export LEXIMIND_CHAT_LLM_MODEL={args.name})  then restart the backend.\n'
          f'Smoke test: ollama run {args.name} "Reply with JSON {{\\"propositions\\": []}}"')


if __name__ == '__main__':
    main()
