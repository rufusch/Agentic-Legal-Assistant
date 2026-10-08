# Cloud deployment

The application frontend communicates only with the backend API. End users need a browser; model installations, Python, and API keys are not required on their laptops. A deployment administrator provisions the server once. Local Ollama/LM Studio remains an optional development setup.

## Self-hosted model on a cloud server

Dockerfile and compose.yaml package the backend plus an independent Ollama service. Copy `.env.example` to `.env`, generate the Fernet encryption key with the command in that file, and set exact Antigravity frontend origins. Run `docker compose up --build -d`. Initial startup downloads the configured review and drafting models once (the default shares a base model; each workflow has independent configuration and prompts) into its persistent volume; model initialization must succeed before the backend starts. Only port 8000 is published. Put it behind your cloud HTTPS ingress. The model's HTTP endpoint stays on the private Compose network.

Allow enough memory for both inference and OCR; 16 GB is a practical starting point for the default 4B quantized model. CPU inference works but can be slow; latency depends on server resources and document length. A GPU or stronger server model can be configured without changing the SPA API. No particular cloud provider is required.

Issue a tenant session for acceptance testing using the offline admin command (requires backend stopped to acquire the data-owner lock):

```sh
docker compose stop backend
docker compose run --rm --no-deps backend python -m backend.admin --storage /data issue-session --tenant acceptance --hours 8
docker compose start backend
```

Deliver that short-lived credential privately to the tester. Production user sign-in and session renewal require an identity integration; the offline admin command is not a public login service.

## Separately hosted model service

Deploy the backend image alone with a persistent `/data` volume. Set `LEXIMIND_MODEL_DEPLOYMENT=cloud`, `LEXIMIND_REVIEW_LLM_PROVIDER=compatible`, `LEXIMIND_REVIEW_BASE_URL=https://your-model-service`, `LEXIMIND_REVIEW_LLM_MODEL`, and optionally `LEXIMIND_REVIEW_API_KEY` as a server secret. The service must implement `/v1/models` and `/v1/chat/completions` with JSON-schema structured output. The base URL excludes `/v1`; every “compatible” service is not guaranteed to support this feature. Ollama is also supported remotely using provider=ollama. Plain HTTP remote endpoints require explicit `LEXIMIND_MODEL_ALLOW_HTTP=1`, intended only for a private network.

Documents are transmitted to the configured service for inference. Choose its retention/privacy settings appropriately. API keys are never returned in model metadata or sent to the SPA. No automatic fallback sends documents to another provider.

## Operational limits and validation

This release uses encrypted SQLite and one durable worker. Run one backend instance/worker per data volume. It supports multiple browser clients but is not yet a horizontally scaled multi-replica service. Keep the encryption key separate from backups, preserve volumes, and configure authenticated HTTPS access. Upload limit is 25 MB/file; review scope is 120,000 extracted characters with explicit rejection above the limit.

The Docker package has not been built or deployed here because Docker is unavailable on this laptop. Cloud transport, authentication boundaries and browser-origin handling are covered by automated tests; an actual provider deployment remains to be validated on the chosen host. Future workflows retain their own model configuration/artifacts and approved training data; they are not implemented merely by these deployment files.
