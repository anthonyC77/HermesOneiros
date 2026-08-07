"""Allow ``python -m oneiros`` alongside the ``oneiros`` console script.

The console script depends on pip having been able to write an executable
shim, which is not guaranteed — on Windows a stale shim from a previous install
makes it fail. ``python -m`` always works, so hooks and docs can fall back to it.
"""

from .cli import main

raise SystemExit(main())
