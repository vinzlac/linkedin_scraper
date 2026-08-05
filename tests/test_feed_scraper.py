"""Tests for FeedScraper."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from linkedin_scraper.scrapers.feed import FeedScraper, FEED_URL
from linkedin_scraper.models.post import Post

# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


class TestFeedScraperUnit:

    def _make_scraper(self):
        page = MagicMock()
        page.evaluate = AsyncMock()
        page.wait_for_timeout = AsyncMock()
        page.wait_for_load_state = AsyncMock()
        page.keyboard = MagicMock()
        page.keyboard.press = AsyncMock()
        page.goto = AsyncMock()
        return FeedScraper(page)

    def test_clean_date(self):
        scraper = self._make_scraper()
        assert scraper._clean_date("2h • something") == "2h"
        assert scraper._clean_date("3 j •") == "3 j"
        assert scraper._clean_date("1 sem") == "1 sem"
        assert scraper._clean_date("") is None
        assert scraper._clean_date(None) is None

    def test_parse_count(self):
        scraper = self._make_scraper()
        assert scraper._parse_count("1,234") == 1234
        assert scraper._parse_count("42 reactions") == 42
        assert scraper._parse_count("") is None
        assert scraper._parse_count(None) is None

    def test_finalize_linkedin_url_prefers_dom_over_compkey_urn(self):
        scraper = self._make_scraper()
        assert scraper._finalize_linkedin_url(
            "https://www.linkedin.com/feed/update/urn:li:activity:999/",
            "urn:li:compkey:expandedFeedType_xyz",
            [],
        ) == "https://www.linkedin.com/feed/update/urn:li:activity:999/"

    def test_finalize_linkedin_url_adds_trailing_slash_on_feed_update(self):
        scraper = self._make_scraper()
        assert scraper._finalize_linkedin_url(
            "https://www.linkedin.com/feed/update/urn:li:activity:1",
            "urn:li:compkey:x",
            [],
        ) == "https://www.linkedin.com/feed/update/urn:li:activity:1/"

    def test_finalize_linkedin_url_ignores_company_posts_feed_listing(self):
        scraper = self._make_scraper()
        listing = "https://www.linkedin.com/company/salon-amif/posts/"
        good = "https://www.linkedin.com/feed/update/urn:li:activity:123/"
        assert scraper._finalize_linkedin_url(listing, "urn:li:compkey:x", [good]) == good

    def test_finalize_linkedin_url_falls_back_to_activity_when_only_listing(self):
        scraper = self._make_scraper()
        listing = "https://www.linkedin.com/company/foo/posts/"
        assert scraper._finalize_linkedin_url(
            listing,
            "urn:li:activity:999",
            [listing],
        ) == "https://www.linkedin.com/feed/update/urn:li:activity:999/"

    def test_looks_like_linkedin_post_url(self):
        scraper = self._make_scraper()
        assert scraper._looks_like_linkedin_post_url(
            "https://www.linkedin.com/feed/update/urn:li:activity:1/"
        )
        assert scraper._looks_like_linkedin_post_url(
            "https://www.linkedin.com/posts/john_activity-123"
        )
        assert not scraper._looks_like_linkedin_post_url("https://example.com/x")

    def test_is_post_detail_url(self):
        scraper = self._make_scraper()
        assert scraper._is_post_detail_url(
            "https://www.linkedin.com/posts/nmartignole_test-share-123/"
        )
        assert scraper._is_post_detail_url(
            "https://www.linkedin.com/feed/update/urn:li:activity:1/"
        )
        assert not scraper._is_post_detail_url("https://www.linkedin.com/feed/")

    @pytest.mark.asyncio
    async def test_correct_author_on_detail_page_replaces_wrong_author(self):
        scraper = self._make_scraper()
        post = Post(
            author_name="Vincent Lacoste",
            author_url="https://www.linkedin.com/in/vincent-lacoste",
            text="Post de test",
        )
        with patch.object(
            scraper,
            "_extract_author_from_post_card",
            new=AsyncMock(
                return_value={
                    "name": "Nicolas Martignole",
                    "url": "https://www.linkedin.com/in/nmartignole",
                    "source": "post_card_actor",
                }
            ),
        ):
            with patch.object(
                scraper,
                "_get_session_user_profile",
                new=AsyncMock(
                    return_value={
                        "name": "Vincent Lacoste",
                        "url": "https://www.linkedin.com/in/vincent-lacoste",
                    }
                ),
            ):
                await scraper._correct_author_on_detail_page(
                    post,
                    "https://www.linkedin.com/posts/nmartignole_test-share-123/",
                )

        assert post.author_name == "Nicolas Martignole"
        assert post.author_url == "https://www.linkedin.com/in/nmartignole"

    @pytest.mark.asyncio
    async def test_correct_author_on_detail_page_clears_session_user_fallback(self):
        scraper = self._make_scraper()
        post = Post(
            author_name="Vincent Lacoste",
            author_url="https://www.linkedin.com/in/vincent-lacoste",
            text="Post de test",
        )
        with patch.object(
            scraper,
            "_extract_author_from_post_card",
            new=AsyncMock(return_value={"name": None, "url": None, "source": "none"}),
        ):
            with patch.object(
                scraper,
                "_get_session_user_profile",
                new=AsyncMock(
                    return_value={
                        "name": "Vincent Lacoste",
                        "url": "https://www.linkedin.com/in/vincent-lacoste",
                    }
                ),
            ):
                await scraper._correct_author_on_detail_page(
                    post,
                    "https://www.linkedin.com/posts/unknown-share-123/",
                )

        assert post.author_name is None
        assert post.author_url is None

    def test_normalize_clipboard_post_url(self):
        scraper = self._make_scraper()
        assert scraper._normalize_clipboard_post_url(
            "https://www.linkedin.com/feed/update/urn:li:activity:1\n"
        ) == "https://www.linkedin.com/feed/update/urn:li:activity:1/"

    @pytest.mark.asyncio
    async def test_scroll_for_more_posts_uses_mouse_wheel(self):
        scraper = self._make_scraper()
        scraper.page.mouse = MagicMock()
        scraper.page.mouse.move = AsyncMock()
        scraper.page.mouse.wheel = AsyncMock()
        scraper.page.viewport_size = {"width": 1280, "height": 720}
        await scraper._scroll_for_more_posts()
        assert scraper.page.mouse.wheel.call_count >= 1

    @pytest.mark.asyncio
    async def test_extract_posts_builds_post_objects(self):
        scraper = self._make_scraper()
        scraper.page.evaluate = AsyncMock(
            return_value=[
                {
                    "urn": "urn:li:activity:123456",
                    "authorName": "Alice Dupont",
                    "authorUrl": "https://www.linkedin.com/in/alicedupont/",
                    "content": "Contenu du post de test suffisamment long pour passer le filtre.",
                    "publishedAt": "2h",
                    "reactionsText": "42",
                    "commentsText": "7",
                    "repostsText": "3",
                    "comments": [
                        {
                            "authorName": "Bob",
                            "text": "Regarde ce lien utile",
                            "url": "https://example.com/resource",
                        }
                    ],
                    "images": [],
                }
            ]
        )

        posts = await scraper._extract_posts_from_feed()

        assert len(posts) == 1
        post = posts[0]
        assert isinstance(post, Post)
        assert post.urn == "urn:li:activity:123456"
        assert post.author_name == "Alice Dupont"
        assert post.author_url == "https://www.linkedin.com/in/alicedupont/"
        assert post.reactions_count == 42
        assert post.comments_count == 7
        assert post.reposts_count == 3
        assert post.posted_date == "2h"
        assert post.linkedin_url == "https://www.linkedin.com/feed/update/urn:li:activity:123456/"
        assert len(post.comments) == 1
        assert post.comments[0]["url"] == "https://example.com/resource"

    @pytest.mark.asyncio
    async def test_extract_posts_compkey_urn_uses_permalink_from_dom(self):
        scraper = self._make_scraper()
        scraper.page.evaluate = AsyncMock(
            return_value=[
                {
                    "urn": "urn:li:compkey:expandedSomeComponentKey",
                    "permalinkUrl": "https://www.linkedin.com/feed/update/urn:li:activity:777888999/",
                    "authorName": "Camille",
                    "authorUrl": "https://www.linkedin.com/in/camille/",
                    "content": "Texte du post avec urn interne compkey mais URL activity dans le DOM.",
                    "publishedAt": "1 j",
                    "reactionsText": "10",
                    "commentsText": "2",
                    "repostsText": "",
                    "images": [],
                }
            ]
        )

        posts = await scraper._extract_posts_from_feed()
        assert len(posts) == 1
        assert posts[0].urn == "urn:li:compkey:expandedSomeComponentKey"
        assert (
            posts[0].linkedin_url
            == "https://www.linkedin.com/feed/update/urn:li:activity:777888999/"
        )

    @pytest.mark.asyncio
    async def test_extract_posts_empty_author_becomes_none(self):
        scraper = self._make_scraper()
        scraper.page.evaluate = AsyncMock(
            return_value=[
                {
                    "urn": "urn:li:activity:999",
                    "authorName": "",
                    "authorUrl": "",
                    "content": "Post sans auteur détecté mais texte suffisant.",
                    "publishedAt": "",
                    "reactionsText": "",
                    "commentsText": "",
                    "repostsText": "",
                    "images": [],
                }
            ]
        )

        posts = await scraper._extract_posts_from_feed()
        assert posts[0].author_name is None
        assert posts[0].author_url is None

    @pytest.mark.asyncio
    async def test_scrape_posts_deduplicates_by_urn(self):
        scraper = self._make_scraper()

        duplicate_post = Post(
            urn="urn:li:activity:111",
            linkedin_url="https://www.linkedin.com/feed/update/urn:li:activity:111/",
            author_name="Bob",
            text="Post unique qui doit apparaître une seule fois.",
        )

        # First call returns 1 post, second returns same post (duplicate), then empty
        call_results = [[duplicate_post], [duplicate_post], []]

        async def mock_extract():
            return call_results.pop(0) if call_results else []

        with patch.object(scraper, "_extract_posts_from_feed", side_effect=mock_extract):
            with patch.object(scraper, "_scroll_for_more_posts", new=AsyncMock()):
                posts = await scraper._scrape_posts(limit=5)

        urns = [p.urn for p in posts]
        assert len(urns) == len(set(urns)), "Duplicate URNs detected"
        assert len(posts) == 1


class TestExtractAuthorFromPostCardDom:
    """Exercises the real DOM-scraping JS against a headless page.

    Regression coverage for the 2026-08-05 report: LinkedIn's single-post
    detail page (/posts/...) migrated to hashed atomic-CSS classes, so the
    legacy .feed-shared-actor/.update-components-actor selectors match
    nothing there, and the connected account's own promo/profile link
    (visually first in the DOM) was being returned as the post author.
    """

    ATOMIC_CSS_PAGE_HTML = """
    <html><body>
      <a href="/posts/pierre-evrard-dashboard_share-7485978261278138368-33uY/"
         class="_74151fd5 _3adf7052">
        Essayez Premium All-in-One pour 0 &euro;
      </a>
      <a href="/in/vincent-lacoste-590a145/" class="_29e627b8 f5c61f47">
        <span aria-hidden="true"></span>
        Vincent Lacoste Architecte Applicatif, Technique &amp; Solution
      </a>
      <div class="_8342bca6 _30d5560e">
        <a href="/in/pierre-evrard-dashboard/" class="a75602c0 d7b82b1d">
          <span aria-hidden="true"></span>
          Pierre Evrard &bull; 1er
        </a>
      </div>
    </body></html>
    """

    @pytest.mark.asyncio
    async def test_finds_real_author_via_degree_suffix_when_classes_are_hashed(self):
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch()
            try:
                page = await browser.new_page()
                await page.set_content(self.ATOMIC_CSS_PAGE_HTML)
                scraper = FeedScraper(page)
                result = await scraper._extract_author_from_post_card()
            finally:
                await browser.close()

        assert result["name"] == "Pierre Evrard"
        assert result["url"] == "https://www.linkedin.com/in/pierre-evrard-dashboard"
        assert result["source"] == "degree_suffix_anchor"


# ---------------------------------------------------------------------------
# Integration tests (require a real LinkedIn session)
# ---------------------------------------------------------------------------


class TestFeedScraperIntegration:

    @pytest.mark.integration
    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_scrape_returns_posts(self, browser_with_session):
        scraper = FeedScraper(browser_with_session.page)
        posts = await scraper.scrape(limit=5)

        assert len(posts) > 0
        assert len(posts) <= 5

        for post in posts:
            assert post.urn is not None
            assert post.text is not None and len(post.text) > 0
            assert post.linkedin_url is not None
            assert "linkedin.com" in post.linkedin_url

    @pytest.mark.integration
    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_scrape_posts_have_author(self, browser_with_session):
        scraper = FeedScraper(browser_with_session.page)
        posts = await scraper.scrape(limit=5)

        posts_with_author = [p for p in posts if p.author_name]
        assert len(posts_with_author) > 0, "No posts had an author name"

    @pytest.mark.integration
    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_scrape_no_duplicates(self, browser_with_session):
        scraper = FeedScraper(browser_with_session.page)
        posts = await scraper.scrape(limit=10)

        urns = [p.urn for p in posts]
        assert len(urns) == len(set(urns)), "Duplicate URNs in results"

    @pytest.mark.integration
    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_scrape_post_by_url_author_not_session_user(self, browser_with_session):
        post_url = (
            "https://www.linkedin.com/posts/nmartignole_je-rentre-de-2-jours-de-conf"
            "%C3%A9rences-passionnants-share-7474414301475213312-8xjU/"
        )
        scraper = FeedScraper(browser_with_session.page)
        session_user = await scraper._get_session_user_profile()
        posts = await scraper.scrape_post_by_url(post_url)

        assert len(posts) == 1
        post = posts[0]
        assert post.text and "voxxed" in post.text.lower()

        author = (post.author_name or "").lower()
        session_name = (session_user.get("name") or "").lower()
        if session_name:
            assert post.author_name != session_user["name"], (
                "author_name must not be the logged-in session user on a third-party post"
            )
        assert "martignole" in author or "nicolas" in author

