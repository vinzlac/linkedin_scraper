"""Tests for Conversation/Message models and MessagingScraper parsing."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

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


SELF_ID = "ACoAAAEKNzwB4E69dZJoooWDrlDaPEU8Mpaezoc"
THREAD_ID = "2-YjQxNTU2NjAtNzk3My00MjBmLTg5MzItODRjZDc5OTQyYWJjXzEwMA=="
SELF_URN = f"urn:li:fsd_profile:{SELF_ID}"
CONVERSATION_URN = f"urn:li:msg_conversation:({SELF_URN},{THREAD_ID})"


@pytest.mark.unit
def test_build_create_message_body_matches_captured_format():
    from linkedin_scraper.scrapers.messaging import MessagingScraper

    body = MessagingScraper._build_create_message_body(
        SELF_ID,
        THREAD_ID,
        "Bonjour Cindy,\n\nMerci.",
        origin_token="0b6f3c1e-1111-4222-8333-944455556666",
        tracking_id="\x8a\x01\xf0abcdefghijklm",
    )
    assert body == {
        "message": {
            "body": {"attributes": [], "text": "Bonjour Cindy,\n\nMerci."},
            "renderContentUnions": [],
            "conversationUrn": CONVERSATION_URN,
            "originToken": "0b6f3c1e-1111-4222-8333-944455556666",
        },
        "mailboxUrn": SELF_URN,
        "trackingId": "\x8a\x01\xf0abcdefghijklm",
        "dedupeByClientGeneratedToken": False,
    }


@pytest.mark.unit
def test_build_create_message_body_decodes_url_encoded_thread_id():
    from linkedin_scraper.scrapers.messaging import MessagingScraper

    body = MessagingScraper._build_create_message_body(
        SELF_ID, THREAD_ID.replace("==", "%3D%3D"), "hi", origin_token="t", tracking_id="x" * 16
    )
    assert body["message"]["conversationUrn"] == CONVERSATION_URN


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    [
        {"entityUrn": "urn:li:msg_message:(x,y)", "originToken": "tok"},
        {"entityUrn": "urn:li:msg_message:(x,y)"},
    ],
)
def test_created_message_urn_accepts_the_created_message(value):
    from linkedin_scraper.scrapers.messaging import MessagingScraper

    assert MessagingScraper._created_message_urn({"value": value}, "tok") == (
        "urn:li:msg_message:(x,y)"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "data",
    [
        {},
        {"value": {}},
        {"value": {"originToken": "tok"}},
        {"value": {"entityUrn": "urn:li:msg_message:(x,y)", "originToken": "other"}},
    ],
)
def test_unconfirmed_errors_lead_with_the_do_not_replay_warning(data):
    # The worker's Telegram notice cuts the error at 160 chars after an MCP
    # prefix: the warning must come first or a human may re-approve the draft.
    from linkedin_scraper.core.exceptions import ScrapingError
    from linkedin_scraper.scrapers.messaging import MessagingScraper

    with pytest.raises(ScrapingError) as excinfo:
        MessagingScraper._created_message_urn(data, "tok")
    assert str(excinfo.value).startswith("createMessage: ne pas rejouer")


@pytest.mark.unit
@pytest.mark.parametrize(
    "data",
    [
        {},
        {"value": {}},
        {"value": {"originToken": "tok"}},
        {"value": {"entityUrn": "urn:li:msg_message:(x,y)", "originToken": "other"}},
    ],
)
def test_created_message_urn_rejects_unconfirmed_responses(data):
    from linkedin_scraper.core.exceptions import ScrapingError
    from linkedin_scraper.scrapers.messaging import MessagingScraper

    with pytest.raises(ScrapingError, match="createMessage.*ne pas rejouer"):
        MessagingScraper._created_message_urn(data, "tok")


@pytest.mark.unit
@pytest.mark.parametrize(
    "data",
    [
        {"miniProfile": {"dashEntityUrn": SELF_URN}},
        {"miniProfile": {"entityUrn": f"urn:li:fs_miniProfile:{SELF_ID}"}},
        {
            "miniProfile": {
                "entityUrn": f"urn:li:fs_miniProfile:{SELF_ID}",
                "dashEntityUrn": SELF_URN,
            },
            "plainId": 123,
        },
    ],
)
def test_self_profile_id_from_me_reads_the_account_urn(data):
    from linkedin_scraper.scrapers.messaging import MessagingScraper

    assert MessagingScraper._self_profile_id_from_me(data) == SELF_ID


@pytest.mark.unit
@pytest.mark.parametrize(
    "data",
    [
        {},
        {"miniProfile": {}},
        {"a": "urn:li:fsd_profile:ACoAAA1", "b": "urn:li:fsd_profile:ACoAAA2"},
    ],
)
def test_self_profile_id_from_me_returns_none_when_unclear(data):
    from linkedin_scraper.scrapers.messaging import MessagingScraper

    assert MessagingScraper._self_profile_id_from_me(data) is None


ME_PAYLOAD = {"miniProfile": {"dashEntityUrn": SELF_URN}}


def _fake_scraper(
    url="https://www.linkedin.com/messaging/",
    status=200,
    response=None,
    me_status=200,
    me_payload=None,
):
    """MessagingScraper over a fake page: answers /me and records the createMessage POST."""
    from linkedin_scraper.scrapers.messaging import MessagingScraper

    page = MagicMock()
    page.url = url
    calls = []

    async def evaluate(script, arg=None):
        calls.append(arg)
        if arg["body"] is None:  # GET /voyager/api/me
            return {"status": me_status, "text": json.dumps(me_payload or ME_PAYLOAD)}
        token = json.loads(arg["body"])["message"]["originToken"]
        payload = response
        if payload is None:
            payload = {"value": {"entityUrn": "urn:li:msg_message:(a,b)", "originToken": token}}
        return {"status": status, "text": json.dumps(payload)}

    page.evaluate = evaluate
    scraper = MessagingScraper(page)
    scraper._open_messaging = AsyncMock()
    scraper.ensure_logged_in = AsyncMock()
    scraper.check_rate_limit = AsyncMock()
    scraper._resolve_self_profile_id = AsyncMock(return_value=SELF_ID)
    return scraper, calls


def _posts(calls):
    return [c for c in calls if c["body"] is not None]


@pytest.mark.unit
@pytest.mark.parametrize(
    "conversation_id, text, error",
    [
        ("2-abc", "   ", "text is required"),
        ("  ", "hi", "conversation_id is required"),
    ],
)
async def test_send_message_requires_text(conversation_id, text, error):
    from linkedin_scraper.core.exceptions import ScrapingError

    scraper, calls = _fake_scraper()
    with pytest.raises(ScrapingError, match=error):
        await scraper.send_message(conversation_id, text)
    assert calls == []


@pytest.mark.unit
async def test_send_message_posts_create_message_with_text_verbatim():
    scraper, calls = _fake_scraper()
    text = "Bonjour Cindy,\n\nMerci pour votre retour.\n\nVincent"

    assert await scraper.send_message(THREAD_ID, text) is True

    posts = _posts(calls)
    assert len(posts) == 1
    assert posts[0]["url"].endswith("voyagerMessagingDashMessengerMessages?action=createMessage")
    body = json.loads(posts[0]["body"])
    assert body["message"]["body"]["text"] == text
    assert body["message"]["conversationUrn"] == CONVERSATION_URN
    assert len(body["trackingId"]) == 16
    assert len(body["message"]["originToken"]) == 36


@pytest.mark.unit
async def test_send_message_from_a_parked_tab_navigates_once_and_reads_the_id_from_me():
    """Real prod case: MCP parks the tab on about:blank, new scraper per call."""
    scraper, calls = _fake_scraper(url="about:blank")

    assert await scraper.send_message(THREAD_ID, "hi") is True

    scraper._open_messaging.assert_awaited_once()
    scraper.ensure_logged_in.assert_awaited()
    scraper.check_rate_limit.assert_awaited()
    scraper._resolve_self_profile_id.assert_not_awaited()
    assert calls[0]["url"].endswith("/voyager/api/me")
    assert len(_posts(calls)) == 1
    assert json.loads(_posts(calls)[0]["body"])["mailboxUrn"] == SELF_URN


@pytest.mark.unit
@pytest.mark.parametrize("me_status, me_payload", [(403, {}), (200, {"miniProfile": {}})])
async def test_send_message_falls_back_to_the_inbox_capture_when_me_fails(me_status, me_payload):
    scraper, calls = _fake_scraper(me_status=me_status, me_payload=me_payload)

    assert await scraper.send_message(THREAD_ID, "hi") is True

    scraper._resolve_self_profile_id.assert_awaited_once()
    assert len(_posts(calls)) == 1


@pytest.mark.unit
async def test_send_message_reuses_a_known_account_id():
    scraper, calls = _fake_scraper()
    scraper._self_profile_id = SELF_ID

    await scraper.send_message(THREAD_ID, "hi")

    assert len(calls) == 1 and calls[0]["body"] is not None  # no /me call
    scraper._resolve_self_profile_id.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.parametrize("status", [400, 403, 429, 999, 500])
async def test_send_message_raises_with_the_http_status_on_failure(status):
    from linkedin_scraper.core.exceptions import ScrapingError

    scraper, calls = _fake_scraper(status=status, response={"message": "nope"})

    with pytest.raises(ScrapingError, match=f"HTTP {status}"):
        await scraper.send_message(THREAD_ID, "hi")
    assert len(_posts(calls)) == 1  # never retried: a retry could send twice


@pytest.mark.unit
async def test_send_message_raises_when_200_does_not_confirm_the_message():
    from linkedin_scraper.core.exceptions import ScrapingError

    scraper, _calls = _fake_scraper(response={"value": {}})

    with pytest.raises(ScrapingError, match="ne pas rejouer.*entityUrn"):
        await scraper.send_message(THREAD_ID, "hi")


@pytest.mark.unit
async def test_send_message_raises_without_replay_on_invalid_json_after_200():
    from linkedin_scraper.core.exceptions import ScrapingError

    scraper, calls = _fake_scraper()

    async def evaluate(script, arg=None):
        calls.append(arg)
        if arg["body"] is None:
            return {"status": 200, "text": json.dumps(ME_PAYLOAD)}
        return {"status": 200, "text": "<html>"}

    scraper.page.evaluate = evaluate
    with pytest.raises(ScrapingError, match="ne pas rejouer"):
        await scraper.send_message(THREAD_ID, "hi")
    assert len(_posts(calls)) == 1


@pytest.mark.unit
async def test_send_message_reports_an_uncertain_send_when_the_page_breaks_mid_post():
    from linkedin_scraper.core.exceptions import ScrapingError

    scraper, calls = _fake_scraper()

    async def evaluate(script, arg=None):
        calls.append(arg)
        if arg["body"] is None:
            return {"status": 200, "text": json.dumps(ME_PAYLOAD)}
        raise RuntimeError("Execution context was destroyed")

    scraper.page.evaluate = evaluate
    with pytest.raises(ScrapingError, match="^createMessage: envoi incertain, ne pas rejouer"):
        await scraper.send_message(THREAD_ID, "hi")
    assert len(_posts(calls)) == 1
