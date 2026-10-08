# Run CaseLens in GitHub Codespaces

1. In GitHub Settings → Codespaces → Secrets, add `GROQ_API_KEY` and grant this repository access. This powers the default hosted generator and verifier. `GEMINI_API_KEY` is optional for independent evaluation; it is not needed to launch the website. Never put keys in source or the browser. Restart a running Codespace after adding secrets.
2. Open the repository's `codex/ps1-delivery` branch, choose **Code → Codespaces → Create codespace**. The dev container installs Python 3.12, Linux parsing libraries and pinned application dependencies. Initial setup takes time and requires internet access. No model weights or legal datasets are downloaded.
3. In the Codespaces terminal run:

   ```bash
   bash scripts/start-codespaces.sh
   ```

   Alternatively: **Terminal → Run Task → Start CaseLens**.
4. Open **CaseLens website / port 8000** in the Ports panel if it does not open automatically. Leave port visibility **Private**.
5. Copy the session token printed in the terminal into **Connect to CaseLens**. It expires after eight hours. The token is an application login, separate from your API key and GitHub login.

The server stays attached to the terminal. Ctrl+C stops it. Run the start command again for a new session token. A browser tab with an expired token prompts for a new one. Stop the Codespace when finished to avoid unnecessary usage charges.

## Model settings

Defaults are Groq `qwen/qwen3.8-27b` for the workflows and Groq `openai/gpt-oss-20b` for verification. Existing `LEXIMIND_*` environment overrides are preserved. Provider availability and account quotas still apply; a configured key does not guarantee available quota. Upload/parsing tools can start without a key, but hosted AI cannot complete requests without credentials.

To choose another supported configuration, export its variables before the start command, for example:

```bash
export LEXIMIND_CHAT_LLM_PROVIDER=groq
export LEXIMIND_CHAT_LLM_MODEL=your-available-model-id
bash scripts/start-codespaces.sh
```

There is no local Ollama service, GPU training environment, or separate frontend build in this setup. Gemini judging and model training are separate tasks.

## Data and troubleshooting

- Documents, database and development encryption key stay in `.data-codespaces` inside the workspace. They persist across server restarts but must be backed up before deleting the Codespace. They are ignored by Git.
- A custom `BACKEND_ENCRYPTION_KEY` is optional. If configured, preserve it; changing it can prevent reading existing data.
- Port already in use: stop the previous terminal task. Only one worker may own a storage directory.
- Installation failed: run `bash scripts/setup-codespaces.sh` to retry. Startup also reruns setup so a partially installed virtual environment cannot silently skip dependencies. Use Python 3.12 on Debian/glibc as specified by `.devcontainer/devcontainer.json`.
- `onnxruntime` reports no matching distribution and pip downloads `musllinux` wheels: the active container uses musl (for example Alpine). Run **Codespaces: Rebuild Container** to apply this repository's Debian/Python 3.12 container. If `.venv` was created under the old container, rename it with `mv .venv .venv-before-rebuild` before rebuilding, then rerun setup. Preserve `.data-codespaces` and its key.
- `Permission denied` when launching the script directly: use `bash scripts/start-codespaces.sh`.
- Session issuance failed after an installation error: complete setup first. The session command imports backend dependencies, so this message alone does not establish a storage or encryption problem.
- Configuration changed: use **Codespaces: Rebuild Container**. Newly added secrets require stopping and restarting the Codespace.
- The exact forwarded HTTPS origin is configured automatically. The local `/demo/session` endpoint remains loopback-only; Codespaces uses the normal authenticated session flow.
- This is a private development workspace. Do not expose its port publicly as a production deployment.

References: [development containers](https://docs.github.com/en/codespaces/setting-up-your-project-for-codespaces/adding-a-dev-container-configuration/introduction-to-dev-containers), [Codespaces secrets](https://docs.github.com/en/codespaces/managing-your-codespaces/managing-your-account-specific-secrets-for-github-codespaces), [port forwarding](https://docs.github.com/en/codespaces/developing-in-a-codespace/forwarding-ports-in-your-codespace).
