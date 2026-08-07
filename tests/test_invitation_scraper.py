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
