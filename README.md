# Chapter Tracker

Chapter Tracker keeps tabs on your manga and novel feeds, refreshing them automatically so the freshest chapters appear in the browser without manual checking. The UI presents each category (main, manga, novel, etc.) with dedicated panels showing the latest activity, save buttons, and quick history overlays.

## What You Can Do

- **Monitor multiple categories** – navigate between main/manga/novel views; each category remembers when it was last polled and how often it should be refreshed.
- **Track favorites & free-only feeds** – mark a link as a favorite, limit scraping to free chapters if supported, and review past updates via the history modal.
- **Let the scheduler handle updates** – APScheduler and the built-in database store coordinate so that categories only refresh when due, and you see live progress indicators powered by Socket.IO.
- **Add or edit links on the fly** – use the floating add button to register new URLs (with frequency and free-only toggles) or edit existing entries without touching the database directly.

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

The first launch seeds `data/chapters.db` with default categories (`main`, `manga`, `novel`). After that, scheduling logic keeps refreshing each category only when its stored interval has elapsed.

## Using the Interface

- The homepage shows “New” and “Saved” sections side by side; watch the live “Last Updated” badge for each chapter entry.
- Click the add button to bring up the modal, fill in the name/URL, set how often you want updates, and optionally enforce free-only scraping.
- Use the menu next to each row to favorite, remove, or view history; the history panel displays last saved values plus metadata like when the link was added or last attempted.
- Your actions immediately persist to `chapters.db`, so restarts won’t lose your configuration.

## Next Steps (Optional)

- Drop new scraper modules into `scrapers/` if you need more sources—the frontend automatically discovers new domains.
- Use `scrapers/example_template.py` as a reference implementation that documents the inputs/outputs, scraping advice, and Selenium fallback guidance.
- Visit `/api/categories` (via AJAX/CLI) for a JSON view of active categories, their next scheduled run, and last-checked timestamp.
