"""Tests for Invitation model and InvitationScraper."""

from pathlib import Path

import pytest

from linkedin_scraper.models import Invitation


FIXTURE = Path(__file__).parent / "fixtures" / "invitation_card.html"


@pytest.mark.unit
def test_invitation_to_public_dict_excludes_raw():
    inv = Invitation(
        invitation_id="abc123",
        profile_name="Ada Lovelace",
        headline="Engineer",
        raw_card_text="secret debug",
    )
    public = inv.to_public_dict()
    assert public["invitation_id"] == "abc123"
    assert public["profile_name"] == "Ada Lovelace"
    assert "raw_card_text" not in public


@pytest.mark.unit
def test_invitation_to_dict_includes_raw():
    inv = Invitation(invitation_id="x", raw_card_text="debug")
    assert inv.to_dict()["raw_card_text"] == "debug"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_parse_invitation_card_from_fixture():
    from playwright.async_api import async_playwright

    from linkedin_scraper.scrapers.invitations import InvitationScraper

    html = FIXTURE.read_text(encoding="utf-8")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html)
        scraper = InvitationScraper(page)
        cards = await scraper._extract_invitations(limit=5)
        await browser.close()

    assert len(cards) >= 1
    assert cards[0].invitation_id == "inv-1"
    assert cards[0].profile_name == "Ada Lovelace"
    assert "Engineer" in (cards[0].headline or "")
    assert cards[0].profile_url and "/in/ada-lovelace" in cards[0].profile_url


@pytest.mark.unit
@pytest.mark.asyncio
async def test_skip_follow_page_ui_context_as_headline():
    from playwright.async_api import async_playwright

    from linkedin_scraper.scrapers.invitations import InvitationScraper

    html = FIXTURE.read_text(encoding="utf-8")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html)
        scraper = InvitationScraper(page)
        cards = await scraper._extract_invitations(limit=10)
        await browser.close()

    kevin = next(c for c in cards if c.invitation_id == "kevin-rousseau01")
    assert kevin.headline == "Founder @ VoiceStudio - AI video localization"
    assert kevin.message is None
    assert "suivre" not in (kevin.headline or "").lower()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_parse_connection_invitation_kind_and_target():
    from playwright.async_api import async_playwright

    from linkedin_scraper.scrapers.invitations import InvitationScraper

    html = FIXTURE.read_text(encoding="utf-8")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html)
        scraper = InvitationScraper(page)
        cards = await scraper._extract_invitations(limit=10)
        await browser.close()

    ada = next(c for c in cards if c.invitation_id == "inv-1")
    assert ada.invitation_kind == "connection"
    assert ada.inviter_name == "Ada Lovelace"
    assert ada.inviter_url and "/in/ada-lovelace" in ada.inviter_url
    assert ada.target_name == "Ada Lovelace"
    assert ada.target_url and "/in/ada-lovelace" in ada.target_url
    assert ada.profile_name == "Ada Lovelace"
    assert ada.shared_connection_count == 3
    assert ada.message == "Hello, interested in a backend role?"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_parse_person_invites_follow_company_gabin_leygacy():
    from playwright.async_api import async_playwright

    from linkedin_scraper.scrapers.invitations import InvitationScraper

    html = FIXTURE.read_text(encoding="utf-8")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html)
        scraper = InvitationScraper(page)
        cards = await scraper._extract_invitations(limit=10)
        await browser.close()

    gabin = next(c for c in cards if "leygacy" in (c.invitation_id or "").lower())
    assert gabin.invitation_id == "leygacy"
    assert gabin.invitation_kind == "follow_company"
    assert gabin.inviter_name == "Gabin Dez"
    assert gabin.inviter_url and "/in/gabindez" in gabin.inviter_url
    assert gabin.target_name == "LEYGACY"
    assert gabin.target_url and "/company/leygacy" in gabin.target_url
    assert gabin.display_text and "suivre" in gabin.display_text.lower()
    assert "LEYGACY" in gabin.display_text
    # Retrocompat: existing person fields stay on the inviter, not overwritten by the page.
    assert gabin.profile_name == "Gabin Dez"
    assert gabin.profile_url and "/in/gabindez" in gabin.profile_url


@pytest.mark.unit
@pytest.mark.asyncio
async def test_parse_direct_company_and_newsletter_kinds():
    from playwright.async_api import async_playwright

    from linkedin_scraper.scrapers.invitations import InvitationScraper

    html = FIXTURE.read_text(encoding="utf-8")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html)
        scraper = InvitationScraper(page)
        cards = await scraper._extract_invitations(limit=10)
        await browser.close()

    acme = next(c for c in cards if c.invitation_id == "direct-acme")
    assert acme.invitation_kind == "follow_company"
    assert acme.target_name == "Direct Acme"
    assert acme.inviter_name == "Direct Acme"

    weekly = next(c for c in cards if c.invitation_id == "weekly-ai-123")
    assert weekly.invitation_kind == "follow_newsletter"
    assert weekly.target_name == "Weekly AI"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_find_follow_company_card_by_target_slug():
    from playwright.async_api import async_playwright

    from linkedin_scraper.scrapers.invitations import InvitationScraper

    html = FIXTURE.read_text(encoding="utf-8")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html)
        scraper = InvitationScraper(page)
        by_target = await scraper._find_card_by_id("leygacy")
        by_inviter = await scraper._find_card_by_id("gabindez")
        await browser.close()

    assert by_target is not None
    assert by_inviter is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_parse_showcase_page_kind():
    from playwright.async_api import async_playwright

    from linkedin_scraper.scrapers.invitations import InvitationScraper

    html = FIXTURE.read_text(encoding="utf-8")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html)
        scraper = InvitationScraper(page)
        cards = await scraper._extract_invitations(limit=10)
        await browser.close()

    nvidia = next(c for c in cards if c.invitation_id == "nvidia-ai")
    assert nvidia.invitation_kind == "follow_showcase_page"
    assert nvidia.target_name == "NVIDIA AI"
    assert nvidia.target_url and "/showcase/nvidia-ai" in nvidia.target_url


@pytest.mark.unit
@pytest.mark.asyncio
async def test_parse_event_invitation_kind():
    from playwright.async_api import async_playwright

    from linkedin_scraper.scrapers.invitations import InvitationScraper

    html = FIXTURE.read_text(encoding="utf-8")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html)
        scraper = InvitationScraper(page)
        cards = await scraper._extract_invitations(limit=10)
        await browser.close()

    event = next(c for c in cards if c.invitation_id == "7123456789012345678")
    assert event.invitation_kind == "event_invitation"
    assert event.inviter_name == "Marie Curie"
    assert event.target_name == "Conférence IA 2026"
    assert event.target_url and "/events/7123456789012345678" in event.target_url


@pytest.mark.unit
@pytest.mark.asyncio
async def test_find_showcase_and_event_cards_by_target_slug():
    from playwright.async_api import async_playwright

    from linkedin_scraper.scrapers.invitations import InvitationScraper

    html = FIXTURE.read_text(encoding="utf-8")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html)
        scraper = InvitationScraper(page)
        by_showcase = await scraper._find_card_by_id("nvidia-ai")
        by_event = await scraper._find_card_by_id("7123456789012345678")
        await browser.close()

    assert by_showcase is not None
    assert by_event is not None


@pytest.mark.unit
def test_invitation_public_dict_includes_kind_fields():
    inv = Invitation(
        invitation_id="leygacy",
        profile_name="Gabin Dez",
        invitation_kind="follow_company",
        inviter_name="Gabin Dez",
        target_name="LEYGACY",
        display_text="Gabin Dez vous a invité(e) à suivre LEYGACY",
    )
    public = inv.to_public_dict()
    assert public["invitation_kind"] == "follow_company"
    assert public["inviter_name"] == "Gabin Dez"
    assert public["target_name"] == "LEYGACY"
    assert public["display_text"].startswith("Gabin Dez")
    assert "raw_card_text" not in public


@pytest.mark.unit
@pytest.mark.asyncio
async def test_find_accept_ignore_buttons_bilingual():
    from playwright.async_api import async_playwright

    from linkedin_scraper.scrapers.invitations import InvitationScraper

    html = FIXTURE.read_text(encoding="utf-8")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html)
        scraper = InvitationScraper(page)
        card = page.locator('[data-invitation-id="inv-1"]').first
        accept_btn = scraper._find_action_button(card, "accept")
        ignore_btn = scraper._find_action_button(card, "ignore")
        assert await accept_btn.count() == 1
        assert await ignore_btn.count() == 1

        card_fr = page.locator('[data-invitation-id="inv-2"]').first
        assert await scraper._find_action_button(card_fr, "accept").count() == 1
        assert await scraper._find_action_button(card_fr, "ignore").count() == 1
        await browser.close()
