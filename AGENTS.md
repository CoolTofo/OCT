# Code Rules for AI Updates

These rules apply to the entire repository.

1. Keep features modular: place reusable frontend constants/helpers in dedicated files under `static/` and backend logic in focused modules under `app/` instead of growing monolithic route or HTML files.
2. Preserve existing behavior while refactoring: make small, reversible changes, keep legacy data readable when possible, and avoid deleting compatibility paths unless explicitly requested.
3. Use clear names that describe the domain intent, prefer pure helper functions for shared UI metadata, and avoid duplicating node/type lists across the canvas code.
4. Do not introduce broad dependencies for simple helpers; favor plain JavaScript/Python utilities already consistent with the project.
5. Run at least one syntax or smoke check for every changed runnable surface and document any environment limitation.
