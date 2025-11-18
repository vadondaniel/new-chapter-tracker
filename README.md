# Chapter Tracker

Chapter Tracker keeps tabs on your manga and novel feeds, refreshing them automatically so the freshest chapters appear in the browser without manual checking. The UI presents each category (main, manga, novel, etc.) with dedicated panels showing the latest activity, save buttons, and quick history overlays.

## What You Can Do

- **Organize multiple categories** - the app seeds a single `main` bucket but you can create manga/novel/etc. via the Category Manager, and each remembers when it was last polled plus its refresh interval.
- **Track favorites & free-only feeds** - mark a link as a favorite, limit scraping to free chapters if supported, and review past updates via the history modal.
- **Let the scheduler handle updates** - APScheduler and the built-in database store coordinate so that categories only refresh when due, and you see live progress indicators powered by Socket.IO.
- **Add or edit links on the fly** - use the floating add button to register new URLs (with frequency and free-only toggles) or edit existing entries without touching the database directly. Edited links can even be reassigned to a different category from the same modal.
- **Curate categories visually** - open *Settings → Manage Categories* to add new categories, rename them, toggle whether they appear in the nav, adjust intervals, and reorder them with up/down controls that persist immediately.

## Getting Started

1. Install requirements in a virtual environment:

   ```bash
   python -m venv .venv
   .venv\\Scripts\\Activate.ps1  # PowerShell
   pip install -r requirements.txt
   ```

2. Start the Flask server:

   ```bash
   python new_chapters.py
   ```

   Then open `http://localhost:555` in your browser.

The first launch seeds `data/chapters.db` with the `main` category. Use the Category Manager to add more (manga, novel, etc.); once they exist, scheduling logic refreshes each category when its stored interval elapses.

## Using the Interface

- The homepage shows "New" and "Saved" sections side by side; watch the live "Last Updated" badge for each chapter entry.
- Click the add button to bring up the modal, fill in the name/URL, set how often you want updates, and optionally enforce free-only scraping.
- Use the menu next to each row to favorite, remove, move to another category, or view history; the history panel displays last saved values plus metadata like when the link was added or last attempted.
- Your actions immediately persist to `chapters.db`, so restarts won't lose your configuration.

### Managing Categories

- Open **Settings → Manage Categories** to review all categories in a compact table.
- Click **Add Category** to insert a highlighted editable row; fill in its slug, display name, interval, and whether it should appear in the nav, then save.
- Drag-free reordering: use the ▲ / ▼ controls to shift a category up or down; the navigation sidebar and API consumers adopt the new order instantly.
- Existing rows can be renamed or hidden from the nav without restarting the server.

## Next Steps (Optional)

- Drop new scraper modules into `scrapers/` if you need more sources-the frontend automatically discovers new domains.
- Use `scrapers/example_template.py` as a reference implementation that documents the inputs/outputs, scraping advice, and Selenium fallback guidance.
- Visit `/api/categories` (via AJAX/CLI) for a JSON view of active categories, their next scheduled run, and last-checked timestamp.
- Run the automated test suite with `pytest` to verify helper logic, scraper utilities, and any future refactors.
