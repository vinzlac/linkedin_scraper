"""Tests du chargement de session et de l'empreinte du navigateur (incident 2026-09-04)."""
import json

import pytest

from linkedin_scraper import BrowserManager

from linkedin_scraper.core.browser import (
    normalize_headless_user_agent,
    sanitize_storage_state,
)


class TestSanitizeStorageState:
    """Le Chromium partagé du homelab (zenika/alpine-chrome:124, via CDP) rejette
    l'attribut de cookie `partitionKey` (CHIPS) que les Playwright récents écrivent
    dans le storage state : `Storage.setCookies: Invalid parameters`. Toute rotation
    de session cassait donc le démarrage du navigateur."""

    def _state(self, tmp_path, cookies):
        p = tmp_path / "session.json"
        p.write_text(json.dumps({"cookies": cookies, "origins": []}), encoding="utf-8")
        return p

    def test_drops_partition_key(self, tmp_path):
        src = self._state(tmp_path, [
            {"name": "li_at", "value": "x", "domain": ".linkedin.com", "path": "/"},
            {"name": "_px3", "value": "y", "domain": ".linkedin.com", "path": "/",
             "partitionKey": {"sourceOrigin": "https://www.linkedin.com",
                              "hasCrossSiteAncestor": False}},
        ])

        out = sanitize_storage_state(str(src))
        data = json.loads(out.read_text(encoding="utf-8"))

        assert len(data["cookies"]) == 2, "aucun cookie ne doit être perdu"
        assert all("partitionKey" not in c for c in data["cookies"])
        assert data["cookies"][0]["value"] == "x"

    def test_returns_the_original_path_when_nothing_to_clean(self, tmp_path):
        src = self._state(tmp_path, [{"name": "li_at", "value": "x",
                                      "domain": ".linkedin.com", "path": "/"}])
        assert sanitize_storage_state(str(src)) == src

    def test_unreadable_file_is_returned_untouched(self, tmp_path):
        p = tmp_path / "broken.json"
        p.write_text("pas du json", encoding="utf-8")
        assert sanitize_storage_state(str(p)) == p


class TestNormalizeHeadlessUserAgent:
    """Le navigateur partagé annonce `HeadlessChrome/124.0.0.0` : c'est le signal
    d'automatisation le plus bruyant qu'on puisse envoyer, et il a valu au compte une
    vérification de sécurité le 2026-09-04. On retire le marqueur sans inventer une
    autre version — un numéro incohérent avec le reste de l'empreinte serait pire."""

    def test_replaces_the_headless_marker(self):
        ua = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "HeadlessChrome/124.0.0.0 Safari/537.36")
        out = normalize_headless_user_agent(ua)
        assert "HeadlessChrome" not in out
        assert "Chrome/124.0.0.0" in out
        assert out.endswith("Safari/537.36")

    def test_leaves_a_normal_user_agent_alone(self):
        ua = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        assert normalize_headless_user_agent(ua) == ua

    def test_handles_missing_user_agent(self):
        assert normalize_headless_user_agent(None) is None
        assert normalize_headless_user_agent("") is None

# ---------------------------------------------------------------------------
# Contexte persistant (incident 2026-09-04)
# ---------------------------------------------------------------------------


class _FakeCtx:
    def __init__(self, pages=None):
        self.pages = pages or []
        self.added = []
        self.closed = False
        self._new_pages = 0

    async def add_cookies(self, cookies):
        self.added.extend(cookies)

    async def new_page(self):
        self._new_pages += 1
        page = _FakePage()
        self.pages.append(page)
        return page

    async def close(self):
        self.closed = True


class _FakePage:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


class _FakeBrowser:
    def __init__(self, contexts):
        self.contexts = contexts
        self.new_contexts = 0
        self.closed = False

    async def new_context(self, **kwargs):
        self.new_contexts += 1
        ctx = _FakeCtx()
        self.contexts.append(ctx)
        return ctx

    async def close(self):
        self.closed = True


def _session_file(tmp_path):
    p = tmp_path / "session.json"
    p.write_text(json.dumps({"cookies": [
        {"name": "li_at", "value": "x", "domain": ".linkedin.com", "path": "/"},
        {"name": "_px3", "value": "y", "domain": ".linkedin.com", "path": "/",
         "partitionKey": {"sourceOrigin": "https://www.linkedin.com"}},
    ], "origins": []}), encoding="utf-8")
    return p


class TestPersistentContext:
    """LinkedIn traite chaque contexte neuf comme un appareil inconnu et redemande
    une vérification de sécurité. Constaté le 2026-09-04 : un identifiant de
    challenge différent à CHAQUE scrape, quels que soient la session, l'IP ou la
    version du navigateur. Réutiliser le profil persistant du navigateur dédié
    donne un appareil stable, pour lequel une seule vérification suffit."""

    @pytest.mark.asyncio
    async def test_reuses_the_browsers_own_context(self, tmp_path):
        existing = _FakeCtx()
        mgr = BrowserManager(cdp_url="http://x:9222", persistent_context=True)
        mgr._browser = _FakeBrowser([existing])

        await mgr.load_session(str(_session_file(tmp_path)))

        assert mgr._context is existing, "le contexte du navigateur doit être réutilisé"
        assert mgr._browser.new_contexts == 0, "aucun contexte isolé ne doit être créé"
        assert [c["name"] for c in existing.added] == ["li_at", "_px3"]
        assert all("partitionKey" not in c for c in existing.added)

    @pytest.mark.asyncio
    async def test_does_not_close_a_context_it_does_not_own(self, tmp_path):
        existing = _FakeCtx()
        mgr = BrowserManager(cdp_url="http://x:9222", persistent_context=True)
        mgr._browser = _FakeBrowser([existing])
        await mgr.load_session(str(_session_file(tmp_path)))
        page = mgr._page

        assert mgr._context is existing
        await mgr.close()

        assert existing.closed is False, "fermer le contexte partagé casserait les autres clients"
        assert page.closed is True, "la page créée par le scraper, elle, doit être fermée"

    @pytest.mark.asyncio
    async def test_default_behaviour_still_creates_an_isolated_context(self, tmp_path):
        mgr = BrowserManager(cdp_url="http://x:9222")   # persistent_context non demandé
        mgr._browser = _FakeBrowser([_FakeCtx()])

        await mgr.load_session(str(_session_file(tmp_path)))

        assert mgr._browser.new_contexts == 1
        assert mgr._context is not mgr._browser.contexts[0]

    @pytest.mark.asyncio
    async def test_load_session_never_closes_the_shared_context(self, tmp_path):
        """Régression : `load_session()` fermait le contexte existant avant même de
        tester s'il fallait le réutiliser. En mode persistant, ce contexte est celui
        du navigateur : il était donc détruit à chaque chargement de session, et le
        scraper retombait sur un contexte isolé — jusqu'à casser la connexion CDP
        (« Target page, context or browser has been closed »)."""
        existing = _FakeCtx()
        mgr = BrowserManager(cdp_url="http://x:9222", persistent_context=True)
        mgr._browser = _FakeBrowser([existing])
        session = _session_file(tmp_path)

        await mgr.load_session(str(session))
        await mgr.load_session(str(session))   # deuxième appel : le cas qui cassait

        assert existing.closed is False, "le contexte du navigateur ne doit jamais être fermé"
        assert mgr._browser.new_contexts == 0, "aucun repli sur un contexte isolé"
        assert mgr._context is existing
