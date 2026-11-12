# Project rules

- Everything for this project lives inside this folder. Never create or edit files outside it.
- Folder layout: `scripts/` for Python code, `data/` for downloaded data, `output/` for charts and result tables. No files loose in the root except README.md, CLAUDE.md, requirements.txt, and .gitignore.
- The virtual environment is `.venv/` inside this folder.
- Scripts build file paths from the project root (using pathlib and the script's own location), so they work no matter where they're run from.
- One script per step. Don't modify earlier scripts unless I ask.
- No test files, scratch files, or extra copies left behind.
