"""Start the private Codespaces website with a real expiring application session."""
import os
from pathlib import Path
import re
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def configure(environment, root=ROOT):
    env = dict(environment)
    env['BACKEND_DEMO'] = '0'  # Preserve the backend's loopback-only demo boundary.
    env.setdefault('BACKEND_STORAGE', str(root / '.data-codespaces'))
    env.setdefault('LEXIMIND_LLM_PROVIDER', 'groq')
    env.setdefault('LEXIMIND_LLM_MODEL', 'qwen/qwen3.8-27b')
    if env['LEXIMIND_LLM_PROVIDER'] == 'groq':
        env.setdefault('LEXIMIND_VERIFIER_LLM_PROVIDER', 'groq')
        env.setdefault('LEXIMIND_VERIFIER_LLM_MODEL', 'openai/gpt-oss-20b')
    name = env.get('CODESPACE_NAME', '')
    domain = env.get('GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN') or 'app.github.dev'
    origin = None
    if name and domain:
        if not re.fullmatch(r'[a-zA-Z0-9-]+', name) or not re.fullmatch(r'[a-zA-Z0-9.-]+', domain):
            raise ValueError('Invalid Codespaces hostname variables.')
        origin = f'https://{name}-8000.{domain}'
        origins = [x.strip().rstrip('/') for x in env.get('BACKEND_CORS_ORIGINS', '').split(',') if x.strip()]
        if origin not in origins:
            origins.append(origin)
        env['BACKEND_CORS_ORIGINS'] = ','.join(origins)
    return env, origin


def main():
    env, origin = configure(os.environ)
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1', 8000)) == 0:
            raise SystemExit('Port 8000 is already in use. Stop the existing server before starting another.')
    # The offline admin command takes the storage lock before issuing a token.
    result = subprocess.run([sys.executable, '-m', 'backend.admin', '--storage', env['BACKEND_STORAGE'],
                             'issue-session', '--tenant', 'codespaces-workspace', '--hours', '8'],
                            cwd=ROOT, env=env, capture_output=True, text=True)
    if result.returncode:
        raise SystemExit('Unable to issue a session. Dependencies may be incomplete: run '
                         'bash scripts/setup-codespaces.sh and resolve any installation errors first. '
                         'To inspect the underlying error, run .venv/bin/python -m backend.admin '
                         '--storage "$BACKEND_STORAGE" issue-session --tenant codespaces-workspace --hours 8 '
                         '(set BACKEND_STORAGE to .data-codespaces if unset). '
                         'If dependencies are installed, check for another process owning the storage '
                         'and verify its encryption key. Existing data was preserved.')
    token = result.stdout.strip()
    if not token:
        raise SystemExit('Session issuance returned no token; the website was not started.')
    print('\nCaseLens session token (expires in 8 hours; paste into Connect to CaseLens):', flush=True)
    print(token, flush=True)
    print('\nOpen ' + (origin or 'http://127.0.0.1:8000') + '\nKeep the forwarded port private. Ctrl+C stops the website.', flush=True)
    if env.get('LEXIMIND_LLM_PROVIDER') == 'groq' and not any(env.get(k) for k in ('GROQ_API_KEY', 'LEXIMIND_LLM_API_KEY', 'LEXIMIND_CHAT_API_KEY', 'LEXIMIND_REVIEW_API_KEY')):
        print('No Groq key found: website and document tools can start, but hosted AI needs a Codespaces GROQ_API_KEY secret.', flush=True)
    os.chdir(ROOT)
    os.environ.update(env)
    import uvicorn
    uvicorn.run('backend.app:app', host='0.0.0.0', port=8000, workers=1,
                proxy_headers=True, forwarded_allow_ips='127.0.0.1,::1')


if __name__ == '__main__':
    main()
