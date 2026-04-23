"""
Runtime compatibility patches.

This project currently runs on Python 3.14 in some environments.
Django 4.2's `BaseContext.__copy__()` implementation uses `copy(super())`,
which breaks on Python 3.14+ and causes Django admin templates to 500.

Long-term fix: upgrade Django to a version that supports your Python runtime.
This patch keeps the app usable until the environment is aligned.
"""

from __future__ import annotations


def apply_patches() -> None:
    try:
        import django
        from django.template.context import BaseContext
    except Exception:
        return

    if not django.get_version().startswith("4.2"):
        return

    def _basecontext_copy(self):  # type: ignore[no-untyped-def]
        # Avoid calling __init__ (e.g., RequestContext requires a request arg).
        duplicate = self.__class__.__new__(self.__class__)
        if hasattr(self, "__dict__") and hasattr(duplicate, "__dict__"):
            duplicate.__dict__.update(self.__dict__)
        duplicate.dicts = self.dicts[:]
        return duplicate

    BaseContext.__copy__ = _basecontext_copy  # type: ignore[method-assign]


apply_patches()
