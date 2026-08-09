"""Scraper for LinkedIn messaging (list, get, send)."""

from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import unquote

from playwright.async_api import Locator, Page

from ..callbacks import ProgressCallback, SilentCallback
from ..core.exceptions import ScrapingError
from ..models.conversation import Conversation
from ..models.message import Message, MessageDirection
from .base import BaseScraper

logger = logging.getLogger(__name__)

MESSAGING_URL = "https://www.linkedin.com/messaging/"
THREAD_URL_TMPL = "https://www.linkedin.com/messaging/thread/{conversation_id}/"

_THREAD_RE = re.compile(r"/messaging/thread/([^/?#]+)/?", re.IGNORECASE)
_UNREAD_RE = re.compile(r"(\d+)\s*(nouvelle|new)", re.IGNORECASE)
_SEND_BUTTON_RE = re.compile(r"^(send|envoyer)$", re.IGNORECASE)


class MessagingScraper(BaseScraper):
    """LinkedIn messaging via DOM scraping (list / get / send)."""

    def __init__(self, page: Page, callback: Optional[ProgressCallback] = None):
        super().__init__(page, callback or SilentCallback())

    async def list_recent(self, limit: int = 20) -> list[Conversation]:
        """List recent conversations from the messaging inbox."""
        logger.info("Listing recent conversations (limit=%s)", limit)
        await self.callback.on_start("Messaging", MESSAGING_URL)
        await self._open_messaging()
        await self.ensure_logged_in()
        await self.check_rate_limit()
        await self._scroll_conversation_list(target=limit)

        items = self.page.locator("li.msg-conversation-listitem")
        count = await items.count()
        results: list[Conversation] = []

        for i in range(min(count, limit)):
            # Re-query — DOM can refresh after clicks
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

        await self.callback.on_complete("Messaging", results)
        logger.info("Listed %s conversations", len(results))
        return results

    async def get_conversation(
        self, conversation_id: str, limit: int = 50
    ) -> list[Message]:
        """Fetch messages for a conversation thread."""
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
        # Type so LinkedIn's Ember handlers enable send mode
        await self.page.keyboard.type(text, delay=15)
        await self.page.wait_for_timeout(400)

        await self._click_send_or_enter()
        await self.page.wait_for_timeout(1500)
        await self.check_rate_limit()
        ok = await self._outbound_contains(text)
        await self.callback.on_complete("MessagingSend", ok)
        return ok

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
