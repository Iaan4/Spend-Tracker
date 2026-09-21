# How I used AI tools

I used Claude to scaffold the FastAPI/SQLite structure and draft the first pass of the code and tests, then reviewed every file and ran the tests.
I changed: it first built the money handling with floats -> I switched to integer cents; it wanted an in-memory list/global app -> I used an app factory + per-request connections.
Also added delete/remove option for removing accidental entries, Copilot helped for debugging
