---
description: Save a durable fact to curated memory
argument-hint: <the fact to remember>
allowed-tools: Bash(python -m oneiros memory:*)
---

Save this to memory: **$ARGUMENTS**

Memory is bounded and lives in every future prompt, so it holds a small number
of facts that stay true. Before writing:

1. **Decide the target.** Facts about the *person* — how they want to be worked
   with, what they know, what annoys them — go to `--target user`. Everything
   else (environment, conventions, hard-won lessons) goes to `memory`.

2. **Decide whether it belongs at all.** Skip anything the repository already
   records, anything trivially re-discoverable, and anything true only for this
   conversation. If the fact fails that test, say so instead of writing it.

3. **Compress it.** One dense, self-contained sentence beats three vague ones.
   It will be read months from now with none of today's context, so name things
   in full rather than referring to "the script" or "that server".

Then run:

```
python -m oneiros memory add "<the compressed fact>" [--target user]
```

Use `python -m oneiros`, not a bare `oneiros`: the console-script shim is not
always installed, and when it is missing the bare form fails with a "not
recognised" error that reads like the plugin is broken.

If the store is full the command fails and lists what is already there. That is
the signal to consolidate — merge overlapping entries with `python -m oneiros
memory replace`, or drop stale ones with `python -m oneiros memory remove` — and
then retry, all in this turn. Do not ask the user to make room; make it.

The write lands on disk now but does not reach the system prompt until the next
session. Say so if the user seems to expect an immediate effect.
