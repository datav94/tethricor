# test-harness

Fixtures for the self-contained local test stack ([`../docker-compose.test.yaml`](../docker-compose.test.yaml)):

- `harness.yaml` — the config the demo harness runs with (clones `sample-repo`).
- `sample-repo/` — a tiny source repo, cloned into the sandbox session (code IN).
- `out/` — where the harness writes `changes.zip` (code OUT).

Full walkthrough: [`../docs/TESTING.md`](../docs/TESTING.md).

```bash
docker compose -f ../docker-compose.test.yaml up --build
unzip -l out/changes.zip
```
