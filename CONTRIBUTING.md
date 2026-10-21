# Contributing

Small, security-relevant bridge. Please keep changes narrow and evidenced.

## Before you open a pull request

Run all three checks and paste the raw output in the PR description:

```sh
python3 verify_isolation.py                      # toolset gate, fails closed
.venv/bin/python -m unittest discover -s tests   # unit tests
.venv/bin/python -m compileall -q server.py tests verify_isolation.py
```

The isolation gate is the piece that matters most. It asserts the exact raw and
model-facing tool catalogue for the configured toolsets, so if your change widens
what the answering agent can reach, the gate must be updated deliberately - with
the new expected set spelled out and a reason - not silenced.

## Rules

1. **Never commit a credential.** No keys, tokens, or account identifiers in
   source, tests, fixtures, comments, example output, or commit messages.
2. **No new capability without a stated threat model.** This wire answers
   questions and nothing else. Anything that lets the remote side act must come
   with an explanation of why the boundary still holds.
3. **Keep the caller's error generic.** The real reason belongs in the server log
   (`_diagnose` and the per-tool `<tool-name>:` log lines). Exposing internal failure detail to an
   untrusted caller is a bug, and losing the server-side breadcrumb is also a bug.
4. **Add a test for behaviour changes,** including rejection paths. Existing tests
   cover auth, Host/Origin pinning, size caps, the hourly and concurrency limits,
   prompt rejection, and the SDK round trip.
5. **Treat the remote text as hostile.** It is data, never instructions.

## Reporting a security issue

Do not open a public issue for a vulnerability. Contact the maintainer directly
with the smallest reproducible description.
