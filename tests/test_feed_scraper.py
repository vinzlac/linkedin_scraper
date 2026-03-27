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
    async def test_scrape_respects_limit(self, browser_with_session):
        scraper = FeedScraper(browser_with_session.page)
        posts = await scraper.scrape(limit=3)
        assert len(posts) <= 3
