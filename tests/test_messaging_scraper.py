"""Tests for Conversation/Message models and MessagingScraper parsing."""

from pathlib import Path

import pytest

from linkedin_scraper.models import Conversation, Message

LIST_FIXTURE = Path(__file__).parent / "fixtures" / "messaging_list.html"
THREAD_FIXTURE = Path(__file__).parent / "fixtures" / "messaging_thread.html"


@pytest.mark.unit
def test_conversation_to_public_dict_excludes_raw():
    conv = Conversation(
        conversation_id="2-abc",
        participant_name="Ada",
        raw_item_text="debug",
    )
    public = conv.to_public_dict()
    assert public["conversation_id"] == "2-abc"
    assert "raw_item_text" not in public


@pytest.mark.unit
def test_message_to_public_dict_excludes_raw():
    msg = Message(
        conversation_id="2-abc",
        text="hi",
        raw_event_text="debug",
    )
    public = msg.to_public_dict()
    assert public["text"] == "hi"
    assert "raw_event_text" not in public


@pytest.mark.unit
@pytest.mark.asyncio
async def test_parse_list_item_from_fixture():
    from playwright.async_api import async_playwright

    from linkedin_scraper.scrapers.messaging import MessagingScraper

    html = LIST_FIXTURE.read_text(encoding="utf-8")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html)
        scraper = MessagingScraper(page)
        item = page.locator("li.msg-conversation-listitem").first
        meta = await scraper._parse_list_item(item)
        await browser.close()

    assert meta["participant_name"] == "Ada Lovelace"
    assert "analytical engine" in (meta["last_message_preview"] or "")
    assert meta["last_activity_at"] == "20:39"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_extract_messages_from_fixture():
    from playwright.async_api import async_playwright

    from linkedin_scraper.scrapers.messaging import MessagingScraper

    html = THREAD_FIXTURE.read_text(encoding="utf-8")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html)
        scraper = MessagingScraper(page)
        messages = await scraper._extract_messages("2-threadid123", limit=10)
        await browser.close()

    assert len(messages) == 2
    assert messages[0].direction == "inbound"
    assert messages[0].sender_name == "Ada Lovelace"
    assert "interested" in (messages[0].text or "")
    assert messages[1].direction == "outbound"
    assert messages[1].text == "Thanks Ada, tell me more."


@pytest.mark.unit
def test_conversation_id_from_url():
    from linkedin_scraper.scrapers.messaging import MessagingScraper

    url = "https://www.linkedin.com/messaging/thread/2-ZTRmZGIyNmMtOWQ2Zi00ZWI2LTg3NzctMTRiY2RiMjc0YTg3XzEwMA==/"
    assert (
        MessagingScraper._conversation_id_from_url(url)
        == "2-ZTRmZGIyNmMtOWQ2Zi00ZWI2LTg3NzctMTRiY2RiMjc0YTg3XzEwMA=="
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_message_requires_text():
    from playwright.async_api import async_playwright

    from linkedin_scraper.core.exceptions import ScrapingError
    from linkedin_scraper.scrapers.messaging import MessagingScraper

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        scraper = MessagingScraper(page)
        with pytest.raises(ScrapingError, match="text is required"):
            await scraper.send_message("2-abc", "   ")
        await browser.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_compose_editor_locator_from_fixture():
    from playwright.async_api import async_playwright

    from linkedin_scraper.scrapers.messaging import MessagingScraper

    html = """
    <form class="msg-form">
      <div class="msg-form__contenteditable" contenteditable="true" role="textbox"
           aria-label="Rédigez un message…"></div>
      <div class="msg-form__hint-text">Appuyez sur Entrée pour envoyer</div>
    </form>
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html)
        scraper = MessagingScraper(page)
        editor = scraper._compose_editor()
        assert await editor.count() == 1
        await browser.close()
