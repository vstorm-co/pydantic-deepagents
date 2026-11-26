"""Render reports without access to network or local resources."""

from weasyprint import HTML
from weasyprint.urls import URLFetcher


def render_pdf(html: str) -> bytes:
    """Render sanitized report HTML without fetching any resource URLs."""
    return HTML(string=html, url_fetcher=URLFetcher(allowed_protocols=())).write_pdf()
