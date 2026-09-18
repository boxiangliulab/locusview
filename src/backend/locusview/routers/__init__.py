"""Feature routers. Each module owns one Data Browser feature (or app-shell page) and exposes a
``router(repo)`` factory returning an :class:`~fastapi.APIRouter`, mirroring the closure-based
route style the app already used before the split (see git history of ``web.py``)."""
