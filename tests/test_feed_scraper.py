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
        # L'URL du DOM porte l'activity URN : il devient l'identifiant canonique,
        # le compkey (éphémère) est conservé pour le debug uniquement.
        assert posts[0].urn == "urn:li:activity:777888999"
        assert posts[0].feed_compkey == "urn:li:compkey:expandedSomeComponentKey"
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


    # --- BUG #1 (2026-09-03) : urn compkey exposé au lieu de l'activity URN ---

    def test_canonical_activity_urn_from_share_slug(self):
        scraper = self._make_scraper()
        url = (
            "https://www.linkedin.com/posts/thierry-templier-7ba726_mon-code-"
            "d%C3%A9viait-lentement-et-aucun-de-share-7500824506219909120-mYgS/"
        )
        assert (
            scraper._canonical_activity_urn_from_url(url)
            == "urn:li:activity:7500824506219909120"
        )

    def test_canonical_activity_urn_from_ugcpost_slug(self):
        scraper = self._make_scraper()
        url = (
            "https://www.linkedin.com/posts/akshay-pachaar_ai-agents-"
            "ugcPost-7500865995637538816-ayfc/"
        )
        assert (
            scraper._canonical_activity_urn_from_url(url)
            == "urn:li:activity:7500865995637538816"
        )

    def test_canonical_activity_urn_from_feed_update_url(self):
        scraper = self._make_scraper()
        url = "https://www.linkedin.com/feed/update/urn:li:activity:7500989467147542528/"
        assert (
            scraper._canonical_activity_urn_from_url(url)
            == "urn:li:activity:7500989467147542528"
        )

    def test_canonical_activity_urn_returns_none_for_non_post_urls(self):
        scraper = self._make_scraper()
        assert scraper._canonical_activity_urn_from_url("") is None
        assert scraper._canonical_activity_urn_from_url(None) is None
        assert scraper._canonical_activity_urn_from_url(
            "https://www.linkedin.com/in/someone/"
        ) is None
        # Slug id too short to be an activity id
        assert scraper._canonical_activity_urn_from_url(
            "https://www.linkedin.com/posts/someone_x-share-1234-abcd/"
        ) is None

    @pytest.mark.asyncio
    async def test_extract_posts_normalizes_compkey_urn_from_copy_link_permalink(self):
        """BUG #1 : la branche copy-link résolvait l'URL mais laissait urn=compkey.

        Le compkey est une clé de carte de feed, éphémère : l'utiliser comme clé
        d'unicité en base crée un doublon à chaque scrape du même post.
        """
        scraper = self._make_scraper()
        compkey = "urn:li:compkey:Lw7YuVgrCpRzKyza7-4l0u-sEsDCcoEn6hQg1beb8XY"
        scraper.page.evaluate = AsyncMock(
            return_value=[
                {
                    "urn": compkey,
                    "permalinkUrl": (
                        "https://www.linkedin.com/posts/thierry-templier-7ba726_mon-code-"
                        "share-7500824506219909120-mYgS/"
                    ),
                    "uiPermalinkFallbackStatus": "resolved_via_copy_link_clipboard",
                    "authorName": "Thierry Templier",
                    "content": "Contenu suffisamment long pour passer le filtre de contenu.",
                    "publishedAt": "7 h",
                    "images": [],
                }
            ]
        )

        posts = await scraper._extract_posts_from_feed()

        assert posts[0].urn == "urn:li:activity:7500824506219909120"
        assert posts[0].feed_compkey == compkey
        # linkedin_url reste le permalien /posts/ qui fonctionne : le id du slug
        # est un share/ugcPost id, /feed/update/urn:li:activity:<id>/ peut 404.
        assert "/posts/" in posts[0].linkedin_url

    @pytest.mark.asyncio
    async def test_extract_posts_keeps_compkey_urn_when_no_permalink_resolved(self):
        scraper = self._make_scraper()
        compkey = "urn:li:compkey:expandedSomeComponentKey"
        scraper.page.evaluate = AsyncMock(
            return_value=[
                {
                    "urn": compkey,
                    "authorName": "Camille",
                    "content": "Post dont aucun permalien n'a pu être résolu, texte long.",
                    "publishedAt": "1 j",
                    "images": [],
                }
            ]
        )

        posts = await scraper._extract_posts_from_feed()

        assert posts[0].urn == compkey
        assert posts[0].feed_compkey == compkey
        assert posts[0].linkedin_url is None

    # --- BUG #4 (2026-09-03) : top_comment, champ séparé de comments ---

    @pytest.mark.asyncio
    async def test_extract_posts_exposes_top_comment(self):
        scraper = self._make_scraper()
        scraper.page.evaluate = AsyncMock(
            return_value=[
                {
                    "urn": "urn:li:activity:123456",
                    "authorName": "Alice",
                    "content": "Contenu du post de test suffisamment long pour le filtre.",
                    "publishedAt": "2h",
                    "commentsText": "9",
                    "topComment": "Excellent retour d'expérience, merci !\nJ'aime\nRépondre",
                    "comments": [],
                    "images": [],
                }
            ]
        )

        posts = await scraper._extract_posts_from_feed()

        assert posts[0].top_comment == "Excellent retour d'expérience, merci !"
        assert posts[0].comments == []

    def test_clean_comment_text_strips_action_lines(self):
        scraper = self._make_scraper()
        raw = "Bruno Martin\n• 2e\nSuper post\nJ'aime\nRépondre\n2 j"
        assert scraper._clean_comment_text(raw) == "Bruno Martin\n• 2e\nSuper post"
        assert scraper._clean_comment_text("") is None
        assert scraper._clean_comment_text("J'aime\nRépondre") is None


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


class TestFeedCardCountsAndCommentsDom:
    """Exercises the real feed-card JS against a headless page.

    Regression coverage for the 2026-09-03 report:
    - BUG #5b : `reposts_count` était systématiquement `null` (le JS ne
      produisait jamais `repostsText`, que le Python lisait déjà).
    - BUG #4 : `comments` ne contient que les commentaires porteurs d'un lien
      externe (par design, pour le pipeline liens) — d'où `top_comment`,
      alimenté par le premier commentaire visible quel qu'il soit.
    """

    FEED_CARD_HTML = """
    <html><body>
      <div data-urn="urn:li:activity:7500930546110382080">
        <a href="/in/alexxubyte/"><span aria-hidden="true"></span>Alex Xu</a>
        <span>&bull; 1er</span>
        <a href="/feed/update/urn:li:activity:7500930546110382080/">2 h</a>
        <div>9 Distributed Systems Patterns You Should Know, un contenu de test
        suffisamment long pour passer les filtres du scraper.</div>
        <button aria-label="1457 r&eacute;actions">1457</button>
        <button aria-label="52 commentaires">52</button>
        <button aria-label="12 republications">12</button>
        <button>J'aime</button>
        <button>Commenter</button>
        <button>Republier</button>
        <div class="comments-comment-item">
          <span class="comments-post-meta__name-text">Bruno Martin</span>
          <div class="comments-comment-item-content-body">
            Le pattern CQRS m&eacute;riterait une mention.
          </div>
          <button>J'aime</button>
          <button>R&eacute;pondre</button>
        </div>
      </div>
    </body></html>
    """

    @pytest.mark.asyncio
    async def test_extracts_reposts_count_and_top_comment(self):
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch()
            try:
                page = await browser.new_page()
                await page.set_content(self.FEED_CARD_HTML)
                scraper = FeedScraper(page)
                posts = await scraper._extract_posts_from_feed()
            finally:
                await browser.close()

        assert len(posts) == 1
        post = posts[0]
        assert post.urn == "urn:li:activity:7500930546110382080"
        assert post.reactions_count == 1457
        assert post.comments_count == 52
        assert post.reposts_count == 12
        assert post.top_comment is not None
        assert "CQRS" in post.top_comment


class TestFeedCardActorAndCountsDom:
    """Cartes d'activité du rendu LinkedIn de septembre 2026 (vérifié en live).

    Trois écarts constatés sur le feed réel le 2026-09-03 :
    - une ligne de wrapper « Post du fil d'actualité » ouvre désormais chaque
      carte, donc la ligne d'acteur n'est plus à un index fixe ;
    - l'acteur peut être annoncé en préfixe (« Suivi par X ») et non plus
      seulement en suffixe (« X a republié ce contenu ») — d'où BUG #3 :
      sans acteur détecté, le premier bloc auteur rencontré est celui du
      contact réseau, pas celui de l'auteur du contenu ;
    - plus aucun compteur dans les aria-labels de boutons, et les réactions
      passent en preuve sociale (« Réaction de X et N autres personnes ») dès
      qu'une relation a réagi — d'où BUG #5a, `reactions_count` à null ;
    - les commentaires ne portent plus les classes `.comments-comment-item`
      mais un `componentkey` `replaceableComment_urn:li:comment:(...)`.
    """

    # Calquée sur la carte live « Suivi par Raphaël Lemaire » / Martin Fowler.
    PREFIX_ACTOR_CARD_HTML = """
    <html><body>
      <div>
        <div>Post du fil d&rsquo;actualit&eacute;</div>
        <div>Suivi par <a href="/in/raphael-lemaire-71b99910/">Rapha&euml;l Lemaire</a></div>
        <div><a href="/in/martin-fowler-com/">Martin Fowler</a></div>
        <div>&bull; Suivi</div>
        <div><a href="/feed/update/urn:li:activity:7500975950243909634/">2 h</a></div>
        <div>Maybe we shouldn't be reviewing all this code : un contenu de test
        suffisamment long pour passer les filtres du scraper.</div>
        <div>&hellip; plus</div>
        <div>R&eacute;action de Michel Bodet et 154 autres personnes</div>
        <div>85 commentaires</div>
        <div>7 republications</div>
        <div><button>J&rsquo;aime</button></div>
        <div><button>Commenter</button></div>
        <div><button>Republier</button></div>
        <div><button>Envoyer</button></div>
        <div componentkey="replaceableComment_urn:li:comment:(urn:li:activity:7500975950243909634,7501)">
          <div>Guillaume DUMAS</div>
          <div>&bull; 2e</div>
          <div>19 h</div>
          <div>C'est la logique du build-up appliqu&eacute;e &agrave; l'IA.</div>
          <div>4 r&eacute;actions</div>
        </div>
      </div>
    </body></html>
    """

    # Forme suffixe historique — doit continuer de fonctionner.
    SUFFIX_ACTOR_CARD_HTML = """
    <html><body>
      <div>
        <div>Post du fil d&rsquo;actualit&eacute;</div>
        <div>Nicolas Martignole a republi&eacute; ce contenu</div>
        <div><a href="/in/nmartignole/">Nicolas Martignole</a></div>
        <div><a href="/in/carlosdiazprofile/">Carlos Diaz</a></div>
        <div>&bull; 2e</div>
        <div><a href="/feed/update/urn:li:activity:7500975950243909635/">21 h</a></div>
        <div>Stripe vient de payer 50 fois les revenus d'une bo&icirc;te de 90
        personnes, contenu de test assez long.</div>
        <div>97 r&eacute;actions</div>
        <div>16 commentaires</div>
        <div>3 republications</div>
        <div><button>J&rsquo;aime</button></div>
        <div><button>Commenter</button></div>
        <div><button>Republier</button></div>
      </div>
    </body></html>
    """

    async def _scrape(self, html):
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch()
            try:
                page = await browser.new_page()
                await page.set_content(html)
                scraper = FeedScraper(page)
                return await scraper._extract_posts_from_feed()
            finally:
                await browser.close()

    @pytest.mark.asyncio
    async def test_prefix_actor_card_attributes_content_to_its_real_author(self):
        posts = await self._scrape(self.PREFIX_ACTOR_CARD_HTML)

        assert len(posts) == 1
        post = posts[0]
        # BUG #3 : c'était Raphaël Lemaire (le contact réseau) qui sortait ici.
        assert post.author_name == "Martin Fowler"
        assert post.author_url == "https://www.linkedin.com/in/martin-fowler-com"
        assert post.actor_name == "Raphaël Lemaire"
        assert post.actor_url == "https://www.linkedin.com/in/raphael-lemaire-71b99910"

    @pytest.mark.asyncio
    async def test_prefix_actor_card_counts_and_top_comment(self):
        posts = await self._scrape(self.PREFIX_ACTOR_CARD_HTML)
        post = posts[0]

        # BUG #5a : preuve sociale « X et 154 autres personnes » = 155 réactions,
        # et surtout pas les « 4 réactions » du commentaire affiché en dessous.
        assert post.reactions_count == 155
        assert post.comments_count == 85
        assert post.reposts_count == 7
        assert post.top_comment is not None
        assert "build-up" in post.top_comment

    @pytest.mark.asyncio
    async def test_suffix_actor_card_still_works(self):
        posts = await self._scrape(self.SUFFIX_ACTOR_CARD_HTML)
        post = posts[0]

        assert post.author_name == "Carlos Diaz"
        assert post.actor_name == "Nicolas Martignole"
        assert post.actor_url == "https://www.linkedin.com/in/nmartignole"
        assert post.reactions_count == 97
        assert post.reposts_count == 3


class TestExpandVisibleCommentsDom:
    """Ouverture des fils de commentaires dans le rendu de septembre 2026.

    Vérifié en live le 2026-09-03 : le contrôle « N commentaires » est un
    `div[role="button"]` SANS aria-label. L'ancienne implémentation ne cliquait
    que des `button[aria-label*="commentaire"]` : elle ne trouvait plus rien, et
    `comments` / `top_comment` ne remontaient que sur les cartes dont LinkedIn
    pré-affiche un commentaire. Un clic JS sur ce div déclenche bien React
    (mesuré : 3 → 18 commentaires rendus).
    """

    EXPANDABLE_CARD_HTML = """
    <html><body>
      <div>
        <div>Post du fil d&rsquo;actualit&eacute;</div>
        <div><a href="/in/someone/">Someone</a></div>
        <div><a href="/feed/update/urn:li:activity:7500000000000000001/">2 h</a></div>
        <div>Contenu du post de test suffisamment long pour passer les filtres.</div>
        <div>12 r&eacute;actions</div>
        <div id="expand" role="button" onclick="
             var d = document.createElement('div');
             d.setAttribute('componentkey', 'replaceableComment_urn:li:comment:(urn:li:activity:7500000000000000001,42)');
             d.innerHTML = '<div>Bruno Martin</div><div>3 h</div><div>Commentaire r&eacute;v&eacute;l&eacute; par le clic.</div>';
             document.getElementById('comments').appendChild(d);">3 commentaires</div>
        <div><button>J&rsquo;aime</button></div>
        <div><button>Commenter</button></div>
        <div><button>Republier</button></div>
        <div id="comments"></div>
      </div>
    </body></html>
    """

    @pytest.mark.asyncio
    async def test_clicks_comment_count_control_without_aria_label(self):
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch()
            try:
                page = await browser.new_page()
                await page.set_content(self.EXPANDABLE_CARD_HTML)
                scraper = FeedScraper(page)
                opened = await scraper._expand_visible_comments_for_url_scrape()
                rendered = await page.eval_on_selector_all(
                    '[componentkey^="replaceableComment_"]', "els => els.length"
                )
            finally:
                await browser.close()

        assert opened == 1
        assert rendered == 1

    @pytest.mark.asyncio
    async def test_does_not_click_the_comment_composer(self):
        from playwright.async_api import async_playwright

        html = """
        <html><body>
          <div>
            <div><button id="composer">Commenter</button></div>
            <div role="button">&Eacute;crire un commentaire</div>
            <div><button>Republier</button></div>
          </div>
          <script>
            window.__clicks = 0;
            document.getElementById('composer').addEventListener('click', function(){ window.__clicks++; });
          </script>
        </body></html>
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            try:
                page = await browser.new_page()
                await page.set_content(html)
                scraper = FeedScraper(page)
                opened = await scraper._expand_visible_comments_for_url_scrape()
                clicks = await page.evaluate("window.__clicks")
            finally:
                await browser.close()

        assert opened == 0
        assert clicks == 0


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

