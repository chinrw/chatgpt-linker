# Draft plan: configurable greeting

Change greet() to accept a configurable prefix, while preserving existing
callers. Keep the default output unchanged. Add tests for empty names and a
custom prefix. Do not introduce an external dependency or a background service.

Open question: should empty names raise an exception or return a fallback?
