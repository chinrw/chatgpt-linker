# Contributing

Use Python 3.11+ on Linux/macOS/WSL2. Run:

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src tests scripts
```

Keep the source project read-only. Do not add generic shell, filesystem-write,
model-provider, browser-cookie, or private ChatGPT endpoint tools. Keep write
annotations accurate. New transport capabilities need protocol and authorization
tests. Do not imply a live ChatGPT/GitHub deployment was tested when only local
fixtures ran. Add regressions for any integrity, privacy, concurrency or protocol
fix. Use synthetic fixtures; never include real credentials or private projects.

Protocol code intentionally implements only a narrow documented MCP subset.
If migrating to the official SDK, retain these behavior tests and add SDK-client
and real-account interoperability checks. Do not silently add runtime downloads.
