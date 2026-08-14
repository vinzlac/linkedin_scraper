"""Scraper for LinkedIn messaging (list, get, send)."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote, unquote

from playwright.async_api import Locator, Page, Response

from ..callbacks import ProgressCallback, SilentCallback
from ..core.exceptions import ScrapingError
from ..models.conversation import Conversation
from ..models.message import Message, MessageDirection
from .base import BaseScraper

logger = logging.getLogger(__name__)

MESSAGING_URL = "https://www.linkedin.com/messaging/"
THREAD_URL_TMPL = "https://www.linkedin.com/messaging/thread/{conversation_id}/"
MESSAGING_GRAPHQL_URL = (
    "https://www.linkedin.com/voyager/api/voyagerMessagingGraphQL/graphql"
)
# Observed LinkedIn query id for messengerMessagesBySyncToken (may change).
MESSENGER_MESSAGES_QUERY_ID = (
    "messengerMessages.5846eeb71c981f11e0134cb6626cc314"
)

_THREAD_RE = re.compile(r"/messaging/thread/([^/?#]+)/?", re.IGNORECASE)
_UNREAD_RE = re.compile(r"(\d+)\s*(nouvelle|new)", re.IGNORECASE)
_SEND_BUTTON_RE = re.compile(r"^(send|envoyer)$", re.IGNORECASE)
_FSD_PROFILE_RE = re.compile(r"urn:li:fsd_profile:([A-Za-z0-9_-]+)")


class MessagingScraper(BaseScraper):
    """LinkedIn messaging via DOM scraping (list / get / send)."""

    def __init__(self, page: Page, callback: Optional[ProgressCallback] = None):
        super().__init__(page, callback or SilentCallback())
        self._self_profile_id: Optional[str] = None

    async def list_recent(
        self, limit: int = 20, *, allow_click_resolve: bool = False
    ) -> list[Conversation]:
        """List recent conversations from the messaging inbox.

        Resolves ``conversation_id`` from the ``messengerConversations`` GraphQL
        payload captured while loading ``/messaging/`` — **without clicking**
        list items (clicking marks conversations as read on LinkedIn).

        Args:
            limit: Max conversations to return.
            allow_click_resolve: If True and GraphQL capture fails, fall back to
                clicking each row (marks as read). Default False.
        """
        logger.info(
            "Listing recent conversations (limit=%s, allow_click_resolve=%s)",
            limit,
            allow_click_resolve,
        )
        await self.callback.on_start("Messaging", MESSAGING_URL)

        payloads: list[dict[str, Any]] = []

        async def _on_response(response: Response) -> None:
            try:
                url = response.url
                if "messengerConversations" not in url:
                    return
                if response.status != 200:
                    return
                data = await response.json()
                if isinstance(data, dict):
                    payloads.append(data)
            except Exception as exc:
                logger.debug("Ignoring messaging API response: %s", exc)

        self.page.on("response", _on_response)
        try:
            await self._open_messaging()
            await self.ensure_logged_in()
            await self.check_rate_limit()
            # Give GraphQL time to land; scroll may trigger another page of results
            await self.page.wait_for_timeout(2000)
            await self._scroll_conversation_list(target=limit)
            await self.page.wait_for_timeout(1500)
        finally:
            self.page.remove_listener("response", _on_response)

        results = self._conversations_from_graphql_payloads(payloads, limit=limit)
        if results:
            await self.callback.on_complete("Messaging", results)
            logger.info("Listed %s conversations via GraphQL (no click)", len(results))
            return results

        if not allow_click_resolve:
            raise ScrapingError(
                "Could not capture messengerConversations GraphQL payload. "
                "Retry, or call list_recent(allow_click_resolve=True) "
                "(warning: clicking marks conversations as read)."
            )

        logger.warning(
            "GraphQL capture empty — falling back to click resolve (marks as read)"
        )
        results = await self._list_recent_via_click(limit=limit)
        await self.callback.on_complete("Messaging", results)
        logger.info("Listed %s conversations via click fallback", len(results))
        return results

    async def _list_recent_via_click(self, limit: int = 20) -> list[Conversation]:
        """Legacy path: click each row to read thread id (marks as read)."""
        items = self.page.locator("li.msg-conversation-listitem")
        count = await items.count()
        results: list[Conversation] = []

        for i in range(min(count, limit)):
            item = self.page.locator("li.msg-conversation-listitem").nth(i)
            meta = await self._parse_list_item(item)
            conversation_id = await self._resolve_conversation_id(item)
            if not conversation_id:
                logger.warning("Skipping conversation without id at index %s", i)
                continue
            results.append(
                Conversation(
                    conversation_id=conversation_id,
                    participant_name=meta.get("participant_name"),
                    participant_url=meta.get("participant_url"),
                    last_message_preview=meta.get("last_message_preview"),
                    last_activity_at=meta.get("last_activity_at"),
                    unread_count=meta.get("unread_count"),
                    raw_item_text=meta.get("raw_item_text"),
                )
            )
        return results

    @staticmethod
    def _conversations_from_graphql_payloads(
        payloads: list[dict[str, Any]], limit: int = 20
    ) -> list[Conversation]:
        seen: set[str] = set()
        results: list[Conversation] = []
        for payload in payloads:
            for element in MessagingScraper._iter_conversation_elements(payload):
                conv = MessagingScraper._conversation_from_api_element(element)
                if conv is None or conv.conversation_id in seen:
                    continue
                seen.add(conv.conversation_id)
                results.append(conv)
                if len(results) >= limit:
                    return results
        return results

    @staticmethod
    def _iter_conversation_elements(obj: Any):
        """Yield conversation dicts that include conversationUrl / unreadCount."""
        if isinstance(obj, dict):
            if "conversationUrl" in obj or (
                "unreadCount" in obj and "backendUrn" in obj
            ):
                yield obj
            for value in obj.values():
                yield from MessagingScraper._iter_conversation_elements(value)
        elif isinstance(obj, list):
            for item in obj:
                yield from MessagingScraper._iter_conversation_elements(item)

    @staticmethod
    def _conversation_from_api_element(element: dict[str, Any]) -> Optional[Conversation]:
        url = element.get("conversationUrl") or ""
        conversation_id = MessagingScraper._conversation_id_from_url(url)
        if not conversation_id:
            backend = element.get("backendUrn") or ""
            m = re.search(r"messagingThread:(2-[^\s\"']+)", backend)
            if m:
                conversation_id = unquote(m.group(1))
        if not conversation_id:
            return None

        name, profile_url = MessagingScraper._participant_from_api(element)
        preview = MessagingScraper._preview_from_api(element)
        unread = element.get("unreadCount")
        if unread is not None:
            try:
                unread = int(unread)
            except (TypeError, ValueError):
                unread = None

        activity = element.get("lastActivityAt")
        last_activity_at = None
        if isinstance(activity, (int, float)):
            last_activity_at = datetime.fromtimestamp(
                activity / 1000.0, tz=timezone.utc
            ).isoformat()

        return Conversation(
            conversation_id=conversation_id,
            participant_name=name,
            participant_url=profile_url,
            last_message_preview=preview,
            last_activity_at=last_activity_at,
            unread_count=unread,
            raw_item_text=json.dumps(
                {
                    "entityUrn": element.get("entityUrn"),
                    "backendUrn": element.get("backendUrn"),
                },
                ensure_ascii=False,
            ),
        )

    @staticmethod
    def _participant_from_api(
        element: dict[str, Any],
    ) -> tuple[Optional[str], Optional[str]]:
        participants = element.get("conversationParticipants") or []
        for participant in participants:
            member = (
                (participant.get("participantType") or {}).get("member")
                if isinstance(participant, dict)
                else None
            )
            if not isinstance(member, dict):
                continue
            if member.get("distance") == "SELF":
                continue
            first = ((member.get("firstName") or {}).get("text") or "").strip()
            last = ((member.get("lastName") or {}).get("text") or "").strip()
            name = f"{first} {last}".strip() or None
            url = member.get("profileUrl")
            return name, url
        return None, None

    @staticmethod
    def _preview_from_api(element: dict[str, Any]) -> Optional[str]:
        messages = element.get("messages")
        if isinstance(messages, dict):
            elements = messages.get("elements") or []
            if elements and isinstance(elements[0], dict):
                body = elements[0].get("body") or {}
                if isinstance(body, dict):
                    text = (body.get("text") or "").strip()
                    if text:
                        return text
                fallback = (elements[0].get("renderContentFallbackText") or "").strip()
                if fallback:
                    return fallback
        return None

    @staticmethod
    def _self_profile_id_from_payloads(
        payloads: list[dict[str, Any]],
    ) -> Optional[str]:
        """Extract the logged-in member's fsd_profile id from conversation payloads."""
        for payload in payloads:
            for element in MessagingScraper._iter_conversation_elements(payload):
                # Prefer SELF participant urns
                for participant in element.get("conversationParticipants") or []:
                    if not isinstance(participant, dict):
                        continue
                    member = (participant.get("participantType") or {}).get("member")
                    if not isinstance(member, dict) or member.get("distance") != "SELF":
                        continue
                    for key in ("hostIdentityUrn", "entityUrn", "backendUrn"):
                        urn = participant.get(key) or ""
                        m = _FSD_PROFILE_RE.search(urn)
                        if m:
                            return m.group(1)
                    profile_url = member.get("profileUrl") or ""
                    m = re.search(r"/in/(ACo[A-Za-z0-9_-]+)", profile_url)
                    if m:
                        return m.group(1)
                # Fallback: conversation entityUrn embeds self profile id
                for key in ("entityUrn", "backendUrn"):
                    urn = element.get(key) or ""
                    m = re.search(
                        r"msg_conversation:\(urn:li:fsd_profile:([A-Za-z0-9_-]+),",
                        urn,
                    )
                    if m:
                        return m.group(1)
        return None

    @staticmethod
    def _build_messages_graphql_url(
        self_profile_id: str,
        conversation_id: str,
        sync_token: Optional[str] = None,
        *,
        query_id: str = MESSENGER_MESSAGES_QUERY_ID,
    ) -> str:
        """Build voyagerMessagingGraphQL URL for messengerMessagesBySyncToken."""
        conversation_id = unquote(conversation_id.strip())
        urn = (
            f"urn:li:msg_conversation:(urn:li:fsd_profile:{self_profile_id},"
            f"{conversation_id})"
        )
        # Browser encodes the URN value but leaves the `(conversationUrn:…)` wrapper.
        urn_enc = quote(urn, safe="")
        if sync_token:
            variables = (
                f"(conversationUrn:{urn_enc},syncToken:{quote(sync_token, safe='')})"
            )
        else:
            variables = f"(conversationUrn:{urn_enc})"
        return f"{MESSAGING_GRAPHQL_URL}?queryId={query_id}&variables={variables}"

    @staticmethod
    def _message_from_api_element(
        element: dict[str, Any], conversation_id: str
    ) -> Optional[Message]:
        """Parse one messengerMessages GraphQL element into a Message."""
        if not isinstance(element, dict):
            return None

        body = element.get("body") or {}
        text = None
        if isinstance(body, dict):
            text = (body.get("text") or "").strip() or None
        if not text:
            text = (element.get("renderContentFallbackText") or "").strip() or None
        if not text:
            return None

        actor = element.get("actor") or element.get("sender") or {}
        member: dict[str, Any] = {}
        if isinstance(actor, dict):
            member = (actor.get("participantType") or {}).get("member") or {}
            if not isinstance(member, dict):
                member = {}

        direction: MessageDirection = "unknown"
        if member.get("distance") == "SELF":
            direction = "outbound"
        elif member:
            direction = "inbound"

        first = ((member.get("firstName") or {}).get("text") or "").strip()
        last = ((member.get("lastName") or {}).get("text") or "").strip()
        sender_name = f"{first} {last}".strip() or None
        sender_url = member.get("profileUrl")

        delivered = element.get("deliveredAt")
        sent_at = None
        if isinstance(delivered, (int, float)):
            sent_at = datetime.fromtimestamp(
                delivered / 1000.0, tz=timezone.utc
            ).isoformat()

        message_id = element.get("entityUrn") or element.get("backendUrn")
        if isinstance(message_id, str):
            message_id = message_id.strip() or None
        else:
            message_id = None

        return Message(
            conversation_id=conversation_id,
            message_id=message_id,
            sender_name=sender_name,
            sender_url=sender_url,
            direction=direction,
            text=text,
            sent_at=sent_at,
            raw_event_text=json.dumps(
                {"entityUrn": element.get("entityUrn"), "deliveredAt": delivered},
                ensure_ascii=False,
            ),
        )

    @staticmethod
    def _messages_from_graphql_payload(
        payload: dict[str, Any], conversation_id: str
    ) -> tuple[list[Message], Optional[str]]:
        """Return (messages, new_sync_token) from a messengerMessages payload."""
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            return [], None

        block = data.get("messengerMessagesBySyncToken")
        if not isinstance(block, dict):
            for key, value in data.items():
                if (
                    isinstance(key, str)
                    and "Messages" in key
                    and isinstance(value, dict)
                    and "elements" in value
                ):
                    block = value
                    break
        if not isinstance(block, dict):
            return [], None

        messages: list[Message] = []
        for element in block.get("elements") or []:
            if isinstance(element, dict):
                msg = MessagingScraper._message_from_api_element(
                    element, conversation_id
                )
                if msg is not None:
                    messages.append(msg)

        meta = block.get("metadata") or {}
        new_token = meta.get("newSyncToken") if isinstance(meta, dict) else None
        if new_token is not None:
            new_token = str(new_token)
        return messages, new_token

    async def _resolve_self_profile_id(self) -> str:
        """Resolve fsd_profile id via messengerConversations capture on /messaging/."""
        payloads: list[dict[str, Any]] = []

        async def _on_response(response: Response) -> None:
            try:
                if "messengerConversations" not in response.url:
                    return
                if response.status != 200:
                    return
                data = await response.json()
                if isinstance(data, dict):
                    payloads.append(data)
            except Exception as exc:
                logger.debug(
                    "Ignoring conversations payload while resolving self: %s", exc
                )

        self.page.on("response", _on_response)
        try:
            # Always reload inbox so messengerConversations GraphQL fires
            # (no-op navigate when already on /messaging/ leaves payloads empty).
            await self.navigate_and_wait(MESSAGING_URL)
            await self.ensure_logged_in()
            await self.page.wait_for_timeout(2000)
            await self.page.evaluate(
                """() => {
                  const list = document.querySelector(
                    '.msg-conversations-container__conversations-list'
                  );
                  if (list) list.scrollTop = Math.min(400, list.scrollHeight);
                }"""
            )
            await self.page.wait_for_timeout(1500)
        finally:
            self.page.remove_listener("response", _on_response)

        self_id = self._self_profile_id_from_payloads(payloads)
        if not self_id:
            raise ScrapingError(
                "Could not resolve self fsd_profile id from messengerConversations"
            )
        self._self_profile_id = self_id
        return self_id

    async def _voyager_graphql_fetch(self, url: str) -> dict[str, Any]:
        """GET a voyager GraphQL URL using the page's cookies + CSRF token."""
        result = await self.page.evaluate(
            """async (url) => {
                const csrfCookie = document.cookie.split(';')
                    .map(s => s.trim())
                    .find(s => s.startsWith('JSESSIONID='));
                const token = csrfCookie
                    ? csrfCookie.split('=').slice(1).join('=').replace(/"/g, '')
                    : '';
                const res = await fetch(url, {
                    credentials: 'include',
                    headers: {
                        'accept': 'application/graphql',
                        'csrf-token': token,
                        'x-restli-protocol-version': '2.0.0',
                    },
                });
                const text = await res.text();
                return { status: res.status, text };
            }""",
            url,
        )
        status = result.get("status")
        text = result.get("text") or ""
        if status != 200:
            raise ScrapingError(f"voyager GraphQL HTTP {status}: {text[:200]}")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ScrapingError(f"voyager GraphQL invalid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ScrapingError("voyager GraphQL response is not an object")
        return data

    async def get_messages_graphql(
        self,
        conversation_id: str,
        *,
        self_profile_id: Optional[str] = None,
        max_pages: int = 50,
        page_pause_ms: int = 400,
    ) -> list[Message]:
        """Fetch messages via messengerMessages GraphQL (no DOM bubble parsing).

        Lands on ``/messaging/`` for session/CSRF, then pages with ``syncToken``
        until no new message ids appear. Does **not** require opening the thread
        URL for each page.

        Args:
            conversation_id: Thread id (``2-…``).
            self_profile_id: Logged-in ``fsd_profile`` id; resolved automatically
                if omitted.
            max_pages: Safety cap on GraphQL pages.
            page_pause_ms: Pause between pages.
        """
        if not conversation_id or not conversation_id.strip():
            raise ScrapingError("conversation_id is required")
        conversation_id = unquote(conversation_id.strip())
        if max_pages < 1:
            raise ScrapingError("max_pages must be >= 1")

        logger.info(
            "Getting messages via GraphQL conversation=%s max_pages=%s",
            conversation_id,
            max_pages,
        )
        await self.callback.on_start("MessagingGraphQL", conversation_id)

        if "linkedin.com" not in (self.page.url or ""):
            await self._open_messaging()
            await self.ensure_logged_in()
            await self.check_rate_limit()
        elif "/messaging" not in (self.page.url or ""):
            await self._open_messaging()
            await self.ensure_logged_in()

        if not self_profile_id:
            self_profile_id = self._self_profile_id or await self._resolve_self_profile_id()
            self._self_profile_id = self_profile_id
        else:
            self._self_profile_id = self_profile_id

        seen: set[str] = set()
        collected: list[Message] = []
        sync_token: Optional[str] = None

        for page_idx in range(max_pages):
            url = self._build_messages_graphql_url(
                self_profile_id, conversation_id, sync_token
            )
            payload = await self._voyager_graphql_fetch(url)
            batch, new_token = self._messages_from_graphql_payload(
                payload, conversation_id
            )
            new_count = 0
            for msg in batch:
                mid = msg.message_id or f"{msg.sent_at}:{msg.text}"
                if mid in seen:
                    continue
                seen.add(mid)
                collected.append(msg)
                new_count += 1

            logger.debug(
                "GraphQL messages page %s: batch=%s new=%s total=%s",
                page_idx,
                len(batch),
                new_count,
                len(collected),
            )
            if new_count == 0 or not new_token or new_token == sync_token:
                break
            sync_token = new_token
            if page_pause_ms > 0:
                await self.page.wait_for_timeout(page_pause_ms)

        collected.sort(key=lambda m: (m.sent_at or "", m.message_id or ""))
        await self.callback.on_complete("MessagingGraphQL", collected)
        logger.info(
            "GraphQL fetched %s messages for conversation %s",
            len(collected),
            conversation_id,
        )
        return collected

    async def get_conversation(
        self, conversation_id: str, limit: int = 50
    ) -> list[Message]:
        """Fetch messages for a conversation thread (DOM)."""
        if not conversation_id or not conversation_id.strip():
            raise ScrapingError("conversation_id is required")

        conversation_id = unquote(conversation_id.strip())
        url = THREAD_URL_TMPL.format(conversation_id=conversation_id)
        logger.info("Getting conversation %s (limit=%s)", conversation_id, limit)
        await self.callback.on_start("MessagingThread", url)
        await self.navigate_and_wait(url)
        await self.ensure_logged_in()
        await self.check_rate_limit()
        await self.page.wait_for_timeout(1500)

        messages = await self._extract_messages(conversation_id, limit=limit)
        await self.callback.on_complete("MessagingThread", messages)
        return messages

    async def send_message(self, conversation_id: str, text: str) -> bool:
        """Send a text message in an existing conversation.

        Opens the thread, types into the compose box, then sends via the
        primary control (Envoyer/Send button if present, else Enter — LinkedIn
        shows « Appuyez sur Entrée pour envoyer »).

        Args:
            conversation_id: Thread id from ``/messaging/thread/{id}/``.
            text: Message body (non-empty).

        Returns:
            True if an outbound bubble matching the text appears after send.
        """
        if not conversation_id or not conversation_id.strip():
            raise ScrapingError("conversation_id is required")
        if not text or not text.strip():
            raise ScrapingError("text is required")

        conversation_id = unquote(conversation_id.strip())
        text = text.strip()
        url = THREAD_URL_TMPL.format(conversation_id=conversation_id)
        logger.info("Sending message to conversation %s (%s chars)", conversation_id, len(text))
        await self.callback.on_start("MessagingSend", url)
        await self.navigate_and_wait(url)
        await self.ensure_logged_in()
        await self.check_rate_limit()
        await self.page.wait_for_timeout(1500)

        editor = self._compose_editor()
        if await editor.count() == 0:
            raise ScrapingError("Message compose editor not found")

        await editor.click()
        await self.page.wait_for_timeout(200)
        # Clear any leftover draft
        await self.page.keyboard.press("ControlOrMeta+A")
        await self.page.keyboard.press("Backspace")
        # insert_text keeps newlines as characters (keyboard.type would
        # press Enter for each "\n" and send prematurely).
        await self.page.keyboard.insert_text(text)
        await self.page.wait_for_timeout(400)

        # Nudge Ember that content changed (some builds ignore insert_text alone)
        await editor.evaluate(
            """(el) => {
                el.dispatchEvent(new InputEvent('input', { bubbles: true, data: el.innerText }));
            }"""
        )
        await self.page.wait_for_timeout(300)

        await self._click_send_or_enter()
        await self.page.wait_for_timeout(2000)
        # Confirm delivery first: latent reCAPTCHA iframes on /messaging/
        # used to make post-send check_rate_limit() raise even when the
        # outbound bubble was already present (false failure).
        ok = await self._outbound_contains(text)
        if ok:
            await self.callback.on_complete("MessagingSend", True)
            return True
        await self.check_rate_limit()
        await self.callback.on_complete("MessagingSend", False)
        return False

    def _compose_editor(self) -> Locator:
        return self.page.locator(
            '.msg-form__contenteditable[contenteditable="true"], '
            '.msg-form__contenteditable[role="textbox"]'
        ).first

    async def _click_send_or_enter(self) -> bool:
        """Prefer an explicit Send/Envoyer button; fall back to Enter."""
        # Visible primary send button (some UIs / locales)
        send_btn = self.page.get_by_role("button", name=_SEND_BUTTON_RE)
        if await send_btn.count() > 0 and await send_btn.first.is_enabled():
            await send_btn.first.click()
            return True

        # Class-based fallbacks seen on older layouts
        class_btn = self.page.locator(
            "button.msg-form__send-button, "
            "button.msg-form__send-btn, "
            '[data-test-msg-ui-send-button]'
        ).first
        if await class_btn.count() > 0 and await class_btn.is_enabled():
            await class_btn.click()
            return True

        # Current LinkedIn FR UI: "Appuyez sur Entrée pour envoyer"
        await self.page.keyboard.press("Enter")
        return True

    async def _outbound_contains(self, text: str) -> bool:
        """Return True if a recent outbound bubble contains ``text``."""
        needle = text.strip()
        messages = await self._extract_messages(
            self._conversation_id_from_url(self.page.url) or "",
            limit=10,
        )
        for msg in reversed(messages):
            if msg.direction != "outbound":
                continue
            if msg.text and needle in msg.text:
                return True
        # Fallback: any recent event body (direction detection may lag)
        bodies = self.page.locator(".msg-s-event-listitem__body")
        n = await bodies.count()
        for i in range(max(0, n - 5), n):
            body = (await bodies.nth(i).inner_text() or "").strip()
            if needle in body:
                return True
        return False

    async def _open_messaging(self) -> None:
        if "/messaging" not in (self.page.url or ""):
            await self.navigate_and_wait(MESSAGING_URL)
        await self.page.wait_for_timeout(1500)

    async def _scroll_conversation_list(self, target: int = 20, max_rounds: int = 15) -> None:
        previous = -1
        stable = 0
        for _ in range(max_rounds):
            count = await self.page.locator("li.msg-conversation-listitem").count()
            if count >= target:
                break
            if count == previous:
                stable += 1
                if stable >= 3:
                    break
            else:
                stable = 0
            previous = count
            await self.page.evaluate(
                """() => {
                    const list = document.querySelector('.msg-conversations-container__conversations-list')
                        || document.querySelector('ul.msg-conversations-container__conversations-list')
                        || document.querySelector('main');
                    if (list) list.scrollTop = list.scrollHeight;
                }"""
            )
            await self.page.wait_for_timeout(400)

    async def _parse_list_item(self, item: Locator) -> dict:
        raw = (await item.inner_text() or "").strip()
        name_el = item.locator(
            ".msg-conversation-listitem__participant-names, "
            ".msg-conversation-card__participant-names, h3"
        ).first
        participant_name = None
        if await name_el.count():
            participant_name = (await name_el.inner_text() or "").strip() or None

        preview_el = item.locator(
            ".msg-conversation-card__message-snippet, "
            ".msg-conversation-listitem__summary"
        ).first
        preview = None
        if await preview_el.count():
            preview = (await preview_el.inner_text() or "").strip() or None

        time_el = item.locator(
            "time, .msg-conversation-listitem__time-stamp, "
            ".msg-conversation-card__time-stamp"
        ).first
        last_activity = None
        if await time_el.count():
            last_activity = (await time_el.inner_text() or "").strip() or None

        img = item.locator("img[alt]").first
        participant_url = None
        if await img.count() and not participant_name:
            alt = await img.get_attribute("alt")
            if alt:
                participant_name = alt.strip()

        unread = self._parse_unread(raw)
        return {
            "participant_name": participant_name,
            "participant_url": participant_url,
            "last_message_preview": preview,
            "last_activity_at": last_activity,
            "unread_count": unread,
            "raw_item_text": raw,
        }

    @staticmethod
    def _parse_unread(raw: str) -> Optional[int]:
        m = _UNREAD_RE.search(raw)
        if m:
            return int(m.group(1))
        return None

    async def _resolve_conversation_id(self, item: Locator) -> Optional[str]:
        """Click the conversation row and read thread id from the URL."""
        link = item.locator(".msg-conversation-listitem__link, [tabindex='0']").first
        target = link if await link.count() else item
        await target.click()
        try:
            await self.page.wait_for_url("**/messaging/thread/**", timeout=10000)
        except Exception:
            # Already on a thread, or slow navigation
            await self.page.wait_for_timeout(1000)
        return self._conversation_id_from_url(self.page.url)

    @staticmethod
    def _conversation_id_from_url(url: str) -> Optional[str]:
        m = _THREAD_RE.search(url or "")
        return unquote(m.group(1)) if m else None

    async def _extract_messages(
        self, conversation_id: str, limit: int = 50
    ) -> list[Message]:
        events = self.page.locator(".msg-s-event-listitem")
        count = await events.count()
        # LinkedIn lists oldest→newest; take the last `limit` events
        start = max(0, count - limit)
        results: list[Message] = []
        for i in range(start, count):
            event = events.nth(i)
            msg = await self._parse_message(event, conversation_id)
            if msg is not None:
                results.append(msg)
        return results

    async def _parse_message(
        self, event: Locator, conversation_id: str
    ) -> Optional[Message]:
        raw = (await event.inner_text() or "").strip()
        urn = await event.get_attribute("data-event-urn")
        classes = (await event.get_attribute("class") or "").lower()

        body_el = event.locator(".msg-s-event-listitem__body").first
        text = None
        if await body_el.count():
            text = (await body_el.inner_text() or "").strip() or None
        if not text:
            # Skip pure UI chrome events without body
            return None

        sender_el = event.locator(
            ".msg-s-message-group__name, .msg-s-message-group__profile-link"
        ).first
        sender_name = None
        if await sender_el.count():
            sender_name = (await sender_el.inner_text() or "").strip() or None

        sender_link = event.locator('a[href*="/in/"]').first
        sender_url = None
        if await sender_link.count():
            href = await sender_link.get_attribute("href")
            if href:
                sender_url = href if href.startswith("http") else f"https://www.linkedin.com{href}"

        time_el = event.locator("time").first
        sent_at = None
        if await time_el.count():
            sent_at = (
                await time_el.get_attribute("datetime")
                or (await time_el.inner_text() or "").strip()
                or None
            )

        direction: MessageDirection = "unknown"
        if "msg-s-event-listitem--other" in classes:
            direction = "inbound"
        elif "msg-s-event-listitem--self" in classes:
            direction = "outbound"

        return Message(
            conversation_id=conversation_id,
            message_id=urn,
            sender_name=sender_name,
            sender_url=sender_url,
            direction=direction,
            text=text,
            sent_at=sent_at.strip() if isinstance(sent_at, str) else sent_at,
            raw_event_text=raw,
        )
