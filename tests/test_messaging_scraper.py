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
def test_conversations_from_graphql_payload_no_click():
    from linkedin_scraper.scrapers.messaging import MessagingScraper

    payload = {
        "data": {
            "messengerConversationsBySyncToken": {
                "elements": [
                    {
                        "conversationUrl": (
                            "https://www.linkedin.com/messaging/thread/"
                            "2-abc123==/"
                        ),
                        "unreadCount": 2,
                        "lastActivityAt": 1786273523965,
                        "backendUrn": "urn:li:messagingThread:2-abc123==",
                        "conversationParticipants": [
                            {
                                "participantType": {
                                    "member": {
                                        "distance": "SELF",
                                        "firstName": {"text": "Vincent"},
                                        "lastName": {"text": "Lacoste"},
                                    }
                                }
                            },
                            {
                                "participantType": {
                                    "member": {
                                        "distance": "DISTANCE_2",
                                        "firstName": {"text": "Ada"},
                                        "lastName": {"text": "Lovelace"},
                                        "profileUrl": "https://www.linkedin.com/in/ada/",
                                    }
                                }
                            },
                        ],
                        "messages": {
                            "elements": [
                                {"body": {"text": "Hello about the engine"}}
                            ]
                        },
                    }
                ]
            }
        }
    }
    convs = MessagingScraper._conversations_from_graphql_payloads([payload], limit=10)
    assert len(convs) == 1
    assert convs[0].conversation_id == "2-abc123=="
    assert convs[0].participant_name == "Ada Lovelace"
    assert convs[0].unread_count == 2
    assert convs[0].last_message_preview == "Hello about the engine"
    assert convs[0].participant_url == "https://www.linkedin.com/in/ada/"


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


MESSAGES_GQL_FIXTURE = Path(__file__).parent / "fixtures" / "messenger_messages_graphql.json"


@pytest.mark.unit
def test_build_messages_graphql_url_encodes_urn():
    from linkedin_scraper.scrapers.messaging import MessagingScraper

    url = MessagingScraper._build_messages_graphql_url(
        "ACoAAAEKNzwB4E69dZJoooWDrlDaPEU8Mpaezoc",
        "2-YjQxNTU2NjAtNzk3My00MjBmLTg5MzItODRjZDc5OTQyYWJjXzEwMA==",
    )
    assert "queryId=messengerMessages." in url
    assert "variables=(conversationUrn:urn%3Ali%3Amsg_conversation%3A" in url
    assert "%2C2-YjQxNTU2NjAtNzk3My00MjBmLTg5MzItODRjZDc5OTQyYWJjXzEwMA%3D%3D" in url


@pytest.mark.unit
def test_messages_from_graphql_fixture_directions():
    import json

    from linkedin_scraper.scrapers.messaging import MessagingScraper

    payload = json.loads(MESSAGES_GQL_FIXTURE.read_text(encoding="utf-8"))
    cid = "2-NjM4Yjc2ODEtMzIzMS00OWMwLWJmOGQtYTU0NDAyMDAxYjVjXzEwMA=="
    messages, token = MessagingScraper._messages_from_graphql_payload(payload, cid)
    assert token
    assert len(messages) >= 1
    assert all(m.conversation_id == cid for m in messages)
    assert all(m.text for m in messages)
    assert {m.direction for m in messages} <= {"inbound", "outbound", "unknown"}
    # At least one direction should be resolved from distance=SELF / other
    assert any(m.direction in ("inbound", "outbound") for m in messages)


@pytest.mark.unit
def test_self_profile_id_from_payloads():
    from linkedin_scraper.scrapers.messaging import MessagingScraper

    payload = {
        "data": {
            "messengerConversationsBySyncToken": {
                "elements": [
                    {
                        "conversationUrl": "https://www.linkedin.com/messaging/thread/2-abc/",
                        "conversationParticipants": [
                            {
                                "hostIdentityUrn": "urn:li:fsd_profile:ACoSelf123",
                                "participantType": {
                                    "member": {"distance": "SELF"}
                                },
                            },
                            {
                                "hostIdentityUrn": "urn:li:fsd_profile:ACoOther",
                                "participantType": {
                                    "member": {
                                        "distance": "DISTANCE_1",
                                        "firstName": {"text": "Ada"},
                                    }
                                },
                            },
                        ],
                    }
                ]
            }
        }
    }
    assert MessagingScraper._self_profile_id_from_payloads([payload]) == "ACoSelf123"
