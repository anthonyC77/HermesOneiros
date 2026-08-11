---
description: Inspect curated memory and review staged writes
argument-hint: [show | pending | approve <id> | reject <id>]
allowed-tools: Bash(python -m oneiros memory:*)
---

Run the requested memory operation: **$ARGUMENTS** (default: `show`).

```
python -m oneiros memory show          # memory as the next session will see it
python -m oneiros memory pending       # writes awaiting a verdict, with their diffs
python -m oneiros memory approve <id>  # apply one
python -m oneiros memory reject <id>   # drop one
```

Use `python -m oneiros`, not a bare `oneiros`: the console-script shim is not
always installed, and when it is missing the bare form fails with a "not
recognised" error that reads like the plugin is broken.

When reviewing pending writes, present them to the user with enough context to
decide, and be specific about **who proposed each one**: a write tagged
`review` or `nrem` came from an unattended pass, on a cheaper model, replaying a
conversation from hours ago. Those are the writes most likely to have encoded a
confident-sounding wrong assumption, and the ones the user most needs to see.

Approval re-plans against memory as it is *now*, not as it was when the write
was staged. If that fails — the store filled up, or the entry it meant to
replace is gone — report what happened rather than retrying with a variation the
user did not approve.
