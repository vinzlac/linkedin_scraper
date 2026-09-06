"""Tests de la détection de rate limit (faux positif du 2026-09-06)."""
import pytest

from linkedin_scraper.core.exceptions import RateLimitError
from linkedin_scraper.core.utils import detect_rate_limit


class TestRateLimitDetection:
    """`detect_rate_limit` cherchait « rate limit », « slow down » et « try again
    later » dans TOUT le texte de la page. Sur un feed rempli de posts techniques
    en anglais, un post parlant de « per-domain rate limits » suffisait à faire
    échouer le scrape — constaté en production le 2026-09-06, feed parfaitement
    chargé et session valide."""

    FEED_WITH_INNOCENT_POST = """
    <html><body>
      <nav><a href="/feed/">Accueil</a></nav>
      <main>
        <article>
          <p>Crawl: multi-page crawl with BFS, DFS, sitemap, or map-only modes,
             per-domain rate limits, and robots.txt compliance. Extract structured
             data from any page. %s</p>
        </article>
      </main>
    </body></html>
    """ % ("Contenu de remplissage pour un feed réaliste. " * 60)

    ERROR_PAGE = """
    <html><body>
      <h1>Too many requests</h1>
      <p>You have made too many requests recently. Please try again later.</p>
    </body></html>
    """

    async def _run(self, html):
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            try:
                page = await browser.new_page()
                await page.set_content(html)
                await detect_rate_limit(page)
            finally:
                await browser.close()

    @pytest.mark.asyncio
    async def test_a_post_mentioning_rate_limits_is_not_a_rate_limit(self):
        await self._run(self.FEED_WITH_INNOCENT_POST)   # ne doit pas lever

    @pytest.mark.asyncio
    async def test_a_real_error_page_is_still_detected(self):
        with pytest.raises(RateLimitError):
            await self._run(self.ERROR_PAGE)
