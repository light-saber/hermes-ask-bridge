# hermes-ask-bridge

Give a remote agent a narrow, read-only way to ask your [Hermes Agent](https://github.com/light-saber/hermes-agent) a question.

One MCP tool. Streamable HTTP. Bearer protected. It answers questions and does
nothing else: no terminal, no file writes, no messaging, no purchases, no trades.

```
   remote agent                internet                 your machine
 +---------------+          +-----------+          +---------------------------+
 |  MCP client   |  HTTPS   |   nginx   | loopback |  ask-bridge  ->  hermes   |
 |  + bearer key | -------> | TLS +     | -------> |  (one MCP tool)   chat    |
 |               |          | exact     |          |       |        --oneshot  |
 +---------------+          | route     |          |       v                   |
                            +-----------+          |  memory + ledger context  |
                                                   +---------------------------+
```

## Why

Agents are useful in proportion to what they can reach, and dangerous in
proportion to how much they can touch. This bridge takes the middle path: a
remote agent can *ask* the agent running on your machine, using the context that
machine has - long-term memory, past sessions, a shared scratchpad - without
getting a shell on it.

It is deliberately one tool with one argument, and everything else is refused
upstream of the model.

## Quickstart

```sh
git clone https://github.com/<you>/hermes-ask-bridge
cd hermes-ask-bridge
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 1. bearer key. Generated, never chosen, never copied, never shared between
#    deployments. It refuses to overwrite an existing key, and it never prints
#    the value, so it cannot leak into your shell history.
.venv/bin/python server.py --generate-key --key-file ./bearer.key

# 2. isolation gate. Replace the interpreter path with the one that has Hermes
#    installed, since the gate imports Hermes' own tool definitions. Install
#    Hermes first if it is missing: the gate cannot run without it.
/path/to/hermes-env/bin/python verify_isolation.py

# 3. run it, loopback only
.venv/bin/python server.py --port 8646 --key-file ./bearer.key
```

Put a TLS reverse proxy in front (`deploy/ask-bridge-nginx.conf`), point the remote
platform's MCP configuration at that HTTPS URL with the same key, then check from
the outside:

```sh
BRIDGE_URL=https://your-host/mcp-ask BRIDGE_KEY_FILE=./bearer.key \
  .venv/bin/python examples/ask.py "Reply with exactly: ok"
```

For a persistent install, use `deploy/ask-bridge.service` (a systemd **user**
unit): `systemctl --user enable --now`, plus `loginctl enable-linger $USER` if it
must survive logout.

## For Hermes agents: implementation runbook

This section is for an AI agent doing the install on behalf of its user, without
human judgement calls. Every step ends in a check, and that check is the evidence
to report. If a check fails, stop and report it verbatim rather than working
around it.

### Ask the user first

Two things are inputs, not guesses:

1. The public HTTPS hostname this will be served on. Do not invent one.
2. Confirmation that the user wants a remote agent to reach their local agent, and
   which remote agent that is.

Never ask for, accept, print, or store the bearer key value in chat. The user
enters it into the remote platform themselves, through that platform's own secret
field. If a user pastes a key into chat, tell them to rotate it.

### Step 1. Locate the Hermes environment

The isolation gate imports Hermes' own tool definitions, so it needs the
interpreter that has Hermes installed, not the bridge venv.

```sh
command -v hermes
python3 -c "import hermes_cli, model_tools; print('hermes import OK')"
```

If that import fails under the system python, find the environment that owns the
`hermes` launcher and use its `bin/python` for step 3.

### Step 2. Clone and install

```sh
git clone https://github.com/<you>/hermes-ask-bridge ~/bridges/ask-bridge
cd ~/bridges/ask-bridge
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

Use an absolute path. A relative working directory breaks the unit later.

### Step 3. Check the toolset, then run the gate

`BRIDGE_TOOLSETS` defaults to `search,session_search`. Keep the default unless the
user asks otherwise: it is the narrowest set that still answers real questions.

```sh
/path/to/hermes-env/bin/python verify_isolation.py
```

Expect a `PASS: toolsets=...` line. A `BLOCKED` line means the tool catalogue does
not match its declared expectation. Do not proceed, and do not edit `EXPECTED` to
make it pass: report the mismatch, because it means the safety claim in this README
no longer holds on that machine. If the user asks for a different toolset, add its
expectation deliberately and say so in your report.

### Step 4. Generate the key without printing it

```sh
.venv/bin/python server.py --generate-key --key-file ./bearer.key
ls -l bearer.key     # confirm -rw------- ; never cat it
```

One command. It writes a unique key at mode `0600`, never prints the value, and
refuses to overwrite an existing key: silently replacing a live key breaks whoever
was already using it.

### Step 5. Test

```sh
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m compileall -q server.py tests verify_isolation.py examples/ask.py
```

Expect `OK` and no other output. Do not continue past a failure.

### Step 6. Smoke test on loopback, before any proxy exists

```sh
.venv/bin/python server.py --port 8646 --key-file ./bearer.key &
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8646/mcp \
  -H 'Content-Type: application/json' -d '{}'
```

Expect `401`. Then ask one authenticated question with `examples/ask.py`, pointed at
loopback. Expect a real answer, not an error string.

### Step 7. Install the service

Copy `deploy/ask-bridge.service` into `~/.config/systemd/user/`, replace the
interpreter path and the `%h/...` paths to match step 2, set the `BRIDGE_*` values
the deployment needs, then:

```sh
systemctl --user daemon-reload
systemctl --user enable --now ask-bridge.service
systemctl --user is-active ask-bridge.service
loginctl enable-linger "$USER"     # only if it must survive logout
```

`BRIDGE_HERMES_BIN` must be an absolute path if `hermes` is not on the unit's
`PATH`, and a systemd user unit usually excludes `~/.local/bin`. The failure symptom
is a generic error on every question with no `hermes chat exited` line in the log.

### Step 8. Put the proxy in front

Add both exact locations from `deploy/ask-bridge-nginx.conf` to the TLS server block
for the user's hostname. The upstream `Host` header must be rewritten to the
loopback address, because the middleware trusts it. Apply with
`nginx -t && nginx -s reload`.

### Step 9. Verify from outside, then hand over

Unauthenticated POST to the public URL must return `401`. An authenticated question
must return an answer. Then give the user the key file path and tell them to enter
the value into the remote platform themselves.

Report in exactly this shape:

```
installed: <absolute path>, unit <name> (<active|failed>)
gate:      PASS, or BLOCKED plus the line
tests:     N passed
loopback:  401 unauthenticated, answered authenticated
public:    401 unauthenticated, answered authenticated
key:       written to <path>, mode 0600, value never displayed
not done:  <anything skipped, or "nothing">
```

Never claim a step succeeded without the command output that shows it.

### Step 10. Rollback

```sh
systemctl --user disable --now ask-bridge.service
# remove the two locations from the proxy config, then nginx -s reload
# delete bearer.key, and revoke the key on the remote platform
```

### Hard rules

- Never print, echo, log, or commit the bearer key value, and never pass it on a
  command line.
- Do not add the `web` toolset. From a bridge host it can reach internal services
  and cloud metadata.
- Do not give the remote side any action capability: no terminal, no writes, no
  messaging, no spending.
- Do not relax the `Origin` or `Host` checks to make a browser client work. A
  browser client is out of scope.
- One tool, one argument. If a task seems to need more, that task does not belong
  on this wire.

## Configuration

Every value is an environment override with a generic default, so the source runs
unchanged on someone else's machine. Put deployment values in the service unit.

| Variable | Default | Purpose |
|---|---|---|
| `BRIDGE_TOOL_NAME` | `ask_agent` | Tool name the remote client sees and calls |
| `BRIDGE_SERVER_NAME` | `ask-bridge` | Server name reported over MCP |
| `BRIDGE_KEY_FILE` | `bearer.key` beside `server.py` | Bearer key file, mode `0600` |
| `BRIDGE_HERMES_BIN` | `hermes` (on `PATH`) | Hermes CLI to invoke |
| `BRIDGE_TOOLSETS` | `search,session_search` | Toolsets the answering agent gets |
| `BRIDGE_MODEL` | *(unset)* | Pin the answering model; unset inherits local config |
| `BRIDGE_PROVIDER` | *(unset)* | Pin the provider; unset inherits local config |
| `BRIDGE_ASK_LIMIT_PER_HOUR` | `30` | Rolling hourly question cap |
| `BRIDGE_MAX_CONCURRENT` | `2` | In-flight question cap |
| `BRIDGE_RUNNER_TIMEOUT` | `120` | Seconds allowed per question |
| `BRIDGE_KEY_BYTES` | `48` | Bytes per generated key; floored at 32 so config cannot weaken it |
| `BRIDGE_LEDGER_PATH` | `bridge-ledger.md` beside `server.py` | Shared scratchpad; `off`/`none`/`-` disables |
| `BRIDGE_LEDGER_TAIL_CHARS` | `2000` | Characters of ledger tail injected as context |
| `BRIDGE_RUN_BUDGET` | `100` | Wall-clock budget passed to the runner |
| `BRIDGE_MEMORY_URL` | *(unset)* | Memory lookup endpoint; unset disables |
| `BRIDGE_MEMORY_HEADERS` | *(unset)* | Extra headers for it, see below |
| `BRIDGE_MEMORY_TIMEOUT` | `10` | Seconds allowed for the memory lookup |
| `BRIDGE_MEMORY_LIMIT` | `4` | Records requested per question |

Relative defaults resolve against the directory holding `server.py`, not the
process working directory, so both path defaults are safe to leave unset.

The isolation gate and the example client carry their own settings:
`BRIDGE_HERMES_LIB` (where Hermes is installed, default
`/usr/local/lib/hermes-agent`) for the gate, and `BRIDGE_URL`, `BRIDGE_KEY_FILE`,
`BRIDGE_TOOL_NAME`, and `BRIDGE_TIMEOUT` for `examples/ask.py`.

`BRIDGE_HERMES_BIN` is the one to watch when installing. A systemd *user* unit's
default `PATH` usually does not include `~/.local/bin`, so if Hermes lives there,
set it explicitly - otherwise every question fails with the generic error, which
tells you nothing.

Because systemd strips nested double quotes from `Environment=` values, set
`BRIDGE_MEMORY_HEADERS` in the simple form rather than as JSON:

```
Environment=BRIDGE_MEMORY_HEADERS=X-Account=hermes;X-User=default;X-Agent=agent
```

A JSON object works too, if you set it from a shell that does not quote-strip.

## What actually enforces the boundary

Be precise here; only some of these layers are real boundaries.

| Layer | Enforces |
|---|---|
| Bearer key, constant-time compared | Who may call the tool at all |
| Loopback bind + exact proxy route | Who may reach the process |
| `verify_isolation.py` at service start | Which tools the answering agent can use |
| `validate_message` filter | Refuses obvious action/secret requests |
| Wrapper prompt around the remote text | Marks it untrusted data, not instructions |

The tool schema is **not** the boundary, and neither is the prompt filter - both
are defence in depth. The boundary is the bearer key plus a toolset allowlist that
is verified at boot. A static key grants any holder the question tool, so rotate it
if it may have leaked.

The isolation gate fails **closed**: an unknown `BRIDGE_TOOLSETS` value, or a tool
catalogue that changed after a Hermes upgrade, refuses to start the service. It runs
from the bundled unit's `ExecStartPre`, so starting `server.py` by hand skips it:
run the gate yourself when testing outside the service. Add an
expectation to `EXPECTED` in `verify_isolation.py` only after deciding what the new
toolset may expose.

One notable non-goal: the `web` toolset is excluded on purpose. From a machine like
this, a URL-fetching tool can reach internal services and cloud metadata - an SSRF
hole. Understand that trade before widening toolsets.

## Key hygiene

One key per deployment. The threat is not a lucky guess. `secrets.token_urlsafe(48)`
is 384 bits, so two independent runs land on the same key with probability around
2^-384: not zero, but far below the odds of the hardware failing first. Every
realistic way to end up sharing a credential is human:

- **Generate, do not choose.** `server.py --generate-key` writes a unique key at
  mode `0600` and never prints the value, so it cannot land in shell history, a
  terminal log, or a chat transcript.
- **Never reuse a value from a test, an example, or a doc.** A key published
  anywhere is a public key. `_read_key` refuses the placeholder values that used to
  sit in this repo's tests, so copying one will not start the service.
- **Validation cannot do this part for you.** The check rejects short and known
  placeholder values, but it cannot tell a real key from any other 32-plus character
  string. Someone determined to reuse a published identifier of that shape will
  still be accepted, which is why the rule matters more than the check.
- **A minimum length is enforced.** Keys under 32 characters are rejected at
  startup, because a short key is a shared key.
- **One key, one bridge.** Do not point two deployments at one key, and do not let
  a test share a key with a live bridge.
- **Rotate on suspicion, and rotate both ends.** The key lives in the key file and
  in the remote platform's secret store. Changing one without the other breaks the
  wire; changing neither leaves the bridge open.
- **Fail closed on a bad key file.** It must be a regular file, owned by the service
  user, mode `0600`, and not a symlink. The bridge checks all of that at startup and
  refuses to run otherwise, rather than quietly accepting something predictable.

## Behaviour

- **Throttle** - 30 questions per rolling hour, 2 in flight. Both are held in
  memory and reset on restart, so a burst of test calls cannot lock a peer out.
- **Timeout** - up to 120s of runner wall clock per question.
- **Errors** - the caller always gets one generic message; the real reason goes to
  journald, never to the remote side. Keeping that server-side breadcrumb is
  deliberate: losing it is the biggest time sink when debugging a wire like this.
- **Question text** - reaches the answering agent only through a private
  `--query-file`, never through a shell, argv, or the environment.

## Optional context: memory and ledger

Two features, both optional.

**Shared ledger.** The bridge appends a one-line Q/A summary after each answer and
injects the recent tail as context before the next one, so two agents stop losing
open loops between them. It is plain markdown, so either side can read it. Keep it
out of version control - it accumulates whatever the two agents discuss.

**Memory lookup.** With `BRIDGE_MEMORY_URL` set, the bridge POSTs a query and
prepends the results as context:

```jsonc
// request
{"query": "…up to 512 chars…", "limit": 4}

// response - any of these shapes is accepted
{"result": {"memories": [ {"uri": "mem://a", "abstract": "…"} ]}}
{"memories": [ … ]}
{"results": [ … ]}   {"data": [ … ]}   {"items": [ … ]}   {"hits": [ … ]}
[ {"uri": "…", "abstract": "…"} ]
```

Each record needs a text-ish field (`abstract`, `summary`, `text`, or `content`).
An id-ish field (`uri`, `id`, or `path`) is shown when present and rendered as `?`
when not, and a record with no usable text is skipped. Transport, HTTP, and JSON
failures are logged to the server log. A reply that simply matches none of the
shapes above yields no context and is not logged. Either way the question is still
answered from the rest of the context: memory is an enhancement, never a dependency.

Tested against `http://127.0.0.1:1933/api/v1/search/find` (OpenViking) using the
header form above.

## Troubleshooting: "the remote agent cannot reach it"

Work the chain in order. The answer is always in one of these five places.

1. `systemctl --user status <unit>` - a crash loop shows as `203/EXEC` or
   exit-code restarts, not a dead port. A `ModuleNotFoundError: ruamel` here means
   `ExecStartPre` ran a bare `python3` instead of the Hermes environment's
   interpreter.
2. `journalctl --user -u <unit> -n 50` - three line kinds, each prefixed with your
   tool name: `admitted N/30 this hour` (the question reached the runner),
   `rejected, …` (concurrency or the hourly cap), and `hermes chat exited N: …`
   (the runner's own provider error). **No admitted line means the request never
   reached the runner**, so the fault is above it: auth, origin, path, or proxy.
3. The proxy's access log for the route - client IP, status, User-Agent. Zero rows
   while the caller reports failure means the request never left their side.
4. Unauthenticated `POST` to the route must return `401`. A `403` on `GET`, or on
   any request carrying a non-local `Origin`, is by design. A connection failure
   means the proxy or the service is down.
5. Runner liveness, independent of the bridge:
   `hermes chat -q 'Reply with exactly: ok' --oneshot --quiet --toolsets
   search,session_search`. Exit 0 means the bridge is fine and the fault is
   elsewhere. Exit 1 with a provider complaint on stdout means the **model**, not
   the bridge, is broken.

Failure modes worth knowing before they bite:

- **A pinned model rots silently.** A model id can stop being servable for an
  account - shared-plan caps, delisting, provider reshuffles - while the code looks
  fine. Every question then fails identically with the generic error. That is the
  argument for leaving `BRIDGE_MODEL` unset.
- **A trailing slash can be answered by the wrong route.** If the bridge is served
  from an exact-match location, `/path/` misses it and falls through to the site
  default - which on a basic-auth site returns a `401` indistinguishable from a bad
  bearer key. Serve both exact paths.
- **Non-local `Origin` is rejected.** Server-side clients do not send it; browsers
  do. Intentional, but it means a browser client cannot use this bridge as-is.
- **A stale key looks exactly like a wrong one** (`401`). The key lives in two
  places: the key file and the remote platform's secret store. Rotating one without
  the other breaks the wire.

## Security notes

- The key file must be a regular file, owned by the service user, mode `0600`.
  `_read_key` refuses anything else, including symlinks.
- The key is compared with `hmac.compare_digest`, and never written to logs,
  source, argv, or the environment.
- Request bodies are capped, malformed bodies are rejected, and duplicate
  `Authorization`/`Host`/`Origin`/`Content-Type` headers are refused outright.
- The listener binds `127.0.0.1` only. The proxy is what makes it reachable, and
  the middleware trusts the upstream `Host` value, so the proxy must rewrite it.

## Tested with

- **Remote agent:** [Fo](https://wajo.ai), calling over Streamable HTTP with a
  bearer key. Its client is server-side Go and does not send an `Origin` header.
- **Answering agent:** [Hermes Agent](https://github.com/light-saber/hermes-agent),
  invoked as a one-shot `hermes chat` subprocess.

Any MCP client that speaks Streamable HTTP and can set an `Authorization: Bearer`
header should work; these are simply what it was built and exercised against. A
client that sends `Origin`, or cannot set custom headers, will not work as-is.

## Contributing

See `CONTRIBUTING.md`. Run the three checks - the isolation gate, the tests, and
`compileall` - and paste their raw output in the PR.

## Licence

MIT. See `LICENSE`.
