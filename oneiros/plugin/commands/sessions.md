---
description: Search past Claude Code sessions on this machine
argument-hint: <what to look for>
allowed-tools: Bash(python -m oneiros sessions:*)
---

Search past sessions for: **$ARGUMENTS**

```
python -m oneiros sessions search "<words>" [--limit N] [--project <dir>]
```

Use `python -m oneiros`, not a bare `oneiros`: the console-script shim is not
always installed, and when it is missing the bare form fails with a "not
recognised" error that reads like the plugin is broken.

Type plain words. The query is translated to full-text syntax for you, so
operators, quotes and wildcards are matched literally rather than interpreted —
there is no syntax to get right and no query that can fail.

This costs nothing: no model call, no tokens. Reach for it before asking the
user to remember something, and before concluding that a past decision was never
made. If the search returns nothing, say that plainly — an empty result means
the index has no record of it, not that it never happened; the index only covers
sessions on this machine.

If the index is empty, build it with `python -m oneiros sessions index` and
search again.
