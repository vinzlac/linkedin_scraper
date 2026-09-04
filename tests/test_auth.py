"""Tests for authentication functions."""
import pytest
from linkedin_scraper import BrowserManager
from linkedin_scraper.core.auth import has_login_form, is_logged_in
from linkedin_scraper.core.exceptions import AuthenticationError
from linkedin_scraper.scrapers.base import BaseScraper


@pytest.mark.asyncio
async def test_is_logged_in_false():
    """Test is_logged_in returns False when not logged in."""
    async with BrowserManager(headless=True) as browser:
        await browser.page.goto("https://www.linkedin.com")
        logged_in = await is_logged_in(browser.page)
        # Should not be logged in to a fresh page
        assert isinstance(logged_in, bool)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_is_logged_in_with_session(browser_with_session):
    """Test is_logged_in returns True with valid session."""
    # Navigate to LinkedIn first
    await browser_with_session.page.goto("https://www.linkedin.com/feed/")
    await browser_with_session.page.wait_for_load_state("domcontentloaded", timeout=15000)
    logged_in = await is_logged_in(browser_with_session.page)
    assert logged_in is True

# ---------------------------------------------------------------------------
# Rebond de connexion (incident du 2026-09-04)
# ---------------------------------------------------------------------------


class _FakeLocator:
    def __init__(self, n):
        self._n = n

    async def count(self):
        return self._n


class _FakePage:
    """Page factice : suit une chronologie d'URL, avec ou sans formulaire."""

    def __init__(self, urls, login_form_count=0):
        self._urls = list(urls)
        self._login_form_count = login_form_count
        self.url = self._urls[0]

    def advance(self):
        if len(self._urls) > 1:
            self._urls.pop(0)
            self.url = self._urls[0]

    def locator(self, selector):
        if "session_key" in selector or "username" in selector:
            return _FakeLocator(self._login_form_count)
        # sélecteurs de nav : présents dès qu'on est sur le feed
        return _FakeLocator(1 if "/feed" in self.url else 0)


@pytest.mark.asyncio
async def test_has_login_form_distinguishes_bounce_from_real_logout():
    """Le rebond passe par /login/ SANS formulaire ; une vraie déconnexion en a un."""
    bounce = _FakePage(["https://www.linkedin.com/login/?session_redirect=x"], login_form_count=0)
    logout = _FakePage(["https://www.linkedin.com/login/"], login_form_count=1)

    assert await has_login_form(bounce) is False
    assert await has_login_form(logout) is True


@pytest.mark.asyncio
async def test_ensure_logged_in_waits_through_the_login_bounce(monkeypatch):
    """BUG 2026-09-04 : LinkedIn route /feed/ par /uas/login puis /login/ avant de
    revenir authentifié (~8 s mesurées en prod). L'ancien budget de 3 s expirait
    pendant ce rebond et levait un faux « Not logged in » sur une session valide."""
    page = _FakePage([
        "https://www.linkedin.com/uas/login?session_redirect=x",
        "https://www.linkedin.com/login/?session_redirect=x",
        "https://www.linkedin.com/login/?session_redirect=x",
        "https://www.linkedin.com/feed/",
    ])

    slept = []

    async def fake_sleep(d):
        slept.append(d)
        page.advance()

    monkeypatch.setattr("linkedin_scraper.scrapers.base.asyncio.sleep", fake_sleep)

    scraper = BaseScraper(page)
    await scraper.ensure_logged_in()  # ne doit pas lever

    assert sum(slept) >= 6, f"budget d'attente trop court : {slept}"


@pytest.mark.asyncio
async def test_ensure_logged_in_fails_fast_on_a_real_login_page(monkeypatch):
    """Une session réellement morte ne doit pas faire attendre le budget complet."""
    page = _FakePage(["https://www.linkedin.com/login/"], login_form_count=1)

    slept = []

    async def fake_sleep(d):
        slept.append(d)

    monkeypatch.setattr("linkedin_scraper.scrapers.base.asyncio.sleep", fake_sleep)

    scraper = BaseScraper(page)
    with pytest.raises(AuthenticationError):
        await scraper.ensure_logged_in()

    assert sum(slept) <= 1, f"attente inutile devant un vrai écran de connexion : {slept}"

@pytest.mark.asyncio
async def test_ensure_logged_in_reports_a_security_checkpoint_distinctly(monkeypatch):
    """Un checkpoint LinkedIn n'est pas une session expirée : il demande une action
    humaine, et réessayer l'aggrave. Il doit donc être signalé pour lui-même."""
    from linkedin_scraper.core.exceptions import CheckpointError

    page = _FakePage(["https://www.linkedin.com/checkpoint/challenge/AgH..."])

    slept = []

    async def fake_sleep(d):
        slept.append(d)

    monkeypatch.setattr("linkedin_scraper.scrapers.base.asyncio.sleep", fake_sleep)

    scraper = BaseScraper(page)
    with pytest.raises(CheckpointError) as exc:
        await scraper.ensure_logged_in()

    assert "checkpoint" in str(exc.value).lower()
    # CheckpointError reste une AuthenticationError pour les appelants existants
    assert isinstance(exc.value, AuthenticationError)
    assert sum(slept) <= 1, f"ne pas insister devant un checkpoint : {slept}"
