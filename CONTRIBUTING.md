# Contributing

Thanks for helping people tame their folders. The bar is simple: **never lose a user's file.**

## Good first contributions
- New file types in `TYPE_EXTS` or smarter default `rules` (regional document names are very welcome: tax forms, school records, ID cards)
- Localized screenshot patterns (`SCREENSHOT_RE`)
- More Chaos Score signals (with a test)
- Translations of the README

## Ground rules
1. Standard library only. No dependencies.
2. Nothing is ever deleted or overwritten. Anything that moves files must be journaled and undoable.
3. Every behavior change needs a test in `tests/test_organize.py` that proves bytes are never lost.
4. Run `python -m unittest discover -s tests -v` on your OS before opening a PR.

## Reporting bugs
Include your OS, Python version, the command you ran, and the plan output. Never paste file contents.
