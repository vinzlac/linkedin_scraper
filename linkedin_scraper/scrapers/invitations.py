"""Scraper for LinkedIn pending connection invitations."""

from __future__ import annotations

import logging
import re
from typing import Literal, Optional
from urllib.parse import unquote, urlparse

from playwright.async_api import Locator, Page

from ..callbacks import ProgressCallback, SilentCallback
from ..core.exceptions import ScrapingError
from ..models.invitation import Invitation
from .base import BaseScraper

logger = logging.getLogger(__name__)

INVITATIONS_URL = "https://www.linkedin.com/mynetwork/invitation-manager/received/"

_ACCEPT_RE = re.compile(r"\b(accept|accepter)\b", re.IGNORECASE)
_IGNORE_RE = re.compile(r"\b(ignore|ignorer|delete|supprimer)\b", re.IGNORECASE)
_SHARED_RE = re.compile(
    r"(\d+)\s*(relations?\s+en\s+commun|mutual\s+connections?)",
    re.IGNORECASE,
)
_PROFILE_RE = re.compile(r"/in/([^/?#]+)/?", re.IGNORECASE)
_COMPANY_RE = re.compile(r"/company/([^/?#]+)/?", re.IGNORECASE)
# LinkedIn UI chrome on invitation cards (not the person's headline)
_UI_CONTEXT_RE = re.compile(
    r"(vous\s+invite\s+à\s+suivre|"
    r"invited\s+you\s+to\s+follow|"
    r"vous\s+a\s+invité|"
    r"parce\s+que\s+vous\s+avez\s+interagi)",
    re.IGNORECASE,
)


class InvitationScraper(BaseScraper):
    """Scrape and act on pending LinkedIn invitations (received)."""

    def __init__(self, page: Page, callback: Optional[ProgressCallback] = None):
        super().__init__(page, callback or SilentCallback())

    async def list_pending(self, limit: int = 20) -> list[Invitation]:
        """List pending received invitations.

        Args:
            limit: Max invitations to return.

        Returns:
            List of Invitation objects.
        """
        logger.info("Listing pending invitations (limit=%s)", limit)
        await self.callback.on_start("Invitations", INVITATIONS_URL)
        await self._open_invitations_page()
        await self.ensure_logged_in()
        await self.check_rate_limit()
        await self._scroll_to_load_invitations(target=limit)
        invitations = await self._extract_invitations(limit=limit)
        await self.callback.on_complete("Invitations", invitations)
        return invitations

    async def accept(self, invitation_id: str) -> bool:
        """Accept a pending invitation by id (profile/company slug or data-id)."""
        return await self._act_on_invitation(invitation_id, "accept")

    async def ignore(self, invitation_id: str) -> bool:
        """Ignore/decline a pending invitation by id."""
        return await self._act_on_invitation(invitation_id, "ignore")

    async def _open_invitations_page(self) -> None:
        if "/mynetwork/invitation-manager" not in (self.page.url or ""):
            await self.navigate_and_wait(INVITATIONS_URL)
        await self.page.wait_for_timeout(1500)
        await self.check_rate_limit()

    async def _scroll_to_load_invitations(self, target: int = 20, max_rounds: int = 25) -> None:
        """Scroll the main content pane so LinkedIn lazy-loads invitation cards.

        Window-level End is not enough: invitations load inside ``main``.
        """
        previous = -1
        stable = 0
        for _ in range(max_rounds):
            count = await self.page.evaluate(
                """() => [...document.querySelectorAll('button')].filter(b => {
                    const label = ((b.getAttribute('aria-label') || '') + ' ' + (b.innerText || '')).toLowerCase();
                    return /\\b(accept|accepter)\\b/.test(label);
                }).length"""
            )
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
                    const main = document.querySelector('main');
                    if (main) {
                        main.scrollTop = main.scrollHeight;
                    } else {
                        window.scrollTo(0, document.body.scrollHeight);
                    }
                }"""
            )
            await self.page.wait_for_timeout(500)
        await self.check_rate_limit()

    async def _extract_invitations(self, limit: int = 20) -> list[Invitation]:
        cards = self.page.locator('[role="listitem"]')
        count = await cards.count()
        results: list[Invitation] = []

        for i in range(count):
            if len(results) >= limit:
                break
            card = cards.nth(i)
            if not await self._card_has_actions(card):
                continue
            invitation = await self._parse_card(card)
            if invitation is not None:
                results.append(invitation)

        logger.info("Extracted %s invitations from %s listitems", len(results), count)
        return results

    async def _card_has_actions(self, card: Locator) -> bool:
        buttons = card.locator("button")
        n = await buttons.count()
        for i in range(n):
            label = await self._button_label(buttons.nth(i))
            if _ACCEPT_RE.search(label) or _IGNORE_RE.search(label):
                return True
        return False

    async def _parse_card(self, card: Locator) -> Optional[Invitation]:
        raw_text = (await card.inner_text() or "").strip()
        profile_url, profile_name = await self._extract_profile(card)

        data_id = await card.get_attribute("data-invitation-id")
        invitation_id = data_id or self._id_from_url(profile_url) or self._slugify_name(
            profile_name
        )
        if not invitation_id:
            logger.debug("Skipping card without invitation_id: %r", raw_text[:80])
            return None

        headline = self._extract_headline(raw_text, profile_name)
        shared = self._extract_shared_count(raw_text)
        message = await self._extract_message(card, raw_text, profile_name, headline)

        return Invitation(
            invitation_id=invitation_id,
            profile_name=profile_name,
            profile_url=profile_url,
            headline=headline,
            shared_connection_count=shared,
            message=message,
            raw_card_text=raw_text,
        )

    async def _extract_profile(self, card: Locator) -> tuple[Optional[str], Optional[str]]:
        links = card.locator('a[href*="/in/"], a[href*="/company/"]')
        n = await links.count()
        best_url: Optional[str] = None
        best_name: Optional[str] = None
        for i in range(n):
            link = links.nth(i)
            href = await link.get_attribute("href")
            text = (await link.inner_text() or "").strip()
            if not href:
                continue
            if href.startswith("/"):
                href = f"https://www.linkedin.com{href}"
            if best_url is None:
                best_url = href.split("?")[0]
            if text and (best_name is None or len(text) > len(best_name)):
                best_name = text
                best_url = href.split("?")[0]
        return best_url, best_name

    @staticmethod
    def _id_from_url(url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        path = urlparse(url).path
        m = _PROFILE_RE.search(path) or _COMPANY_RE.search(path)
        return unquote(m.group(1)) if m else None

    @staticmethod
    def _slugify_name(name: Optional[str]) -> Optional[str]:
        if not name:
            return None
        slug = re.sub(r"\s+", "-", name.strip().lower())
        slug = re.sub(r"[^a-z0-9\-._]", "", slug)
        return slug or None

    @staticmethod
    def _extract_headline(raw_text: str, profile_name: Optional[str]) -> Optional[str]:
        lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
        # Drop duplicated name lines and action labels
        skip = {
            "ignorer",
            "accepter",
            "ignore",
            "accept",
            "… voir plus",
            "... see more",
            "voir plus",
            "see more",
        }
        candidates: list[str] = []
        for line in lines:
            low = line.lower()
            if profile_name and (
                line == profile_name or line.startswith(f"{profile_name} ")
            ):
                # Skip name + LinkedIn UI context glued on the same line
                if line == profile_name or _UI_CONTEXT_RE.search(line):
                    continue
            if low in skip:
                continue
            if _SHARED_RE.search(line):
                continue
            if _ACCEPT_RE.search(line) or _IGNORE_RE.search(line):
                continue
            if _UI_CONTEXT_RE.search(line):
                continue
            candidates.append(line)
        if not candidates:
            return None
        # First remaining line is typically the headline
        return candidates[0]

    @staticmethod
    def _extract_shared_count(raw_text: str) -> Optional[int]:
        m = _SHARED_RE.search(raw_text)
        return int(m.group(1)) if m else None

    async def _extract_message(
        self,
        card: Locator,
        raw_text: str,
        profile_name: Optional[str],
        headline: Optional[str],
    ) -> Optional[str]:
        box = card.locator('[data-testid="expandable-text-box"]')
        if await box.count() > 0:
            text = (await box.first.inner_text() or "").strip()
            text = re.sub(r"\s*[….]+\s*(voir plus|see more)\s*$", "", text, flags=re.I)
            if text:
                return text
        # Do not guess a message from headline/UI lines — only explicit intro notes.
        return None

    def _find_action_button(
        self, card: Locator, action: Literal["accept", "ignore"]
    ) -> Locator:
        # Match accessible name (aria-label) or visible text — bilingual.
        if action == "accept":
            return card.get_by_role(
                "button", name=re.compile(r"accept|accepter", re.IGNORECASE)
            )
        return card.get_by_role(
            "button",
            name=re.compile(r"ignore|ignorer|delete|supprimer", re.IGNORECASE),
        )

    async def _button_label(self, button: Locator) -> str:
        aria = await button.get_attribute("aria-label")
        text = (await button.inner_text() or "").strip()
        return f"{aria or ''} {text}".strip()

    async def _find_card_by_id(self, invitation_id: str) -> Optional[Locator]:
        cards = self.page.locator('[role="listitem"]')
        count = await cards.count()
        needle = invitation_id.strip().lower()
        for i in range(count):
            card = cards.nth(i)
            if not await self._card_has_actions(card):
                continue
            data_id = (await card.get_attribute("data-invitation-id") or "").lower()
            if data_id == needle:
                return card
            hrefs = card.locator('a[href*="/in/"], a[href*="/company/"]')
            n = await hrefs.count()
            for j in range(n):
                href = (await hrefs.nth(j).get_attribute("href") or "").lower()
                if f"/in/{needle}" in href or f"/company/{needle}" in href:
                    return card
            # Fallback: slugified visible name
            parsed = await self._parse_card(card)
            if parsed and parsed.invitation_id.lower() == needle:
                return card
        return None

    async def _act_on_invitation(
        self, invitation_id: str, action: Literal["accept", "ignore"]
    ) -> bool:
        if not invitation_id or not invitation_id.strip():
            raise ScrapingError("invitation_id is required")

        logger.info("%s invitation %s", action, invitation_id)
        await self._open_invitations_page()
        await self.ensure_logged_in()
        await self.check_rate_limit()

        card = await self._find_card_by_id(invitation_id)
        if card is None:
            logger.warning("Invitation not found: %s", invitation_id)
            return False

        button = self._find_action_button(card, action)
        if await button.count() == 0:
            # Fallback: aria-label scan
            buttons = card.locator("button")
            n = await buttons.count()
            button = None
            pattern = _ACCEPT_RE if action == "accept" else _IGNORE_RE
            for i in range(n):
                candidate = buttons.nth(i)
                label = await self._button_label(candidate)
                if pattern.search(label):
                    button = candidate
                    break
            if button is None:
                logger.warning("No %s button for invitation %s", action, invitation_id)
                return False

        await button.first.click()
        await self.page.wait_for_timeout(1200)
        await self.check_rate_limit()

        # Success if card no longer found or no longer has actions
        remaining = await self._find_card_by_id(invitation_id)
        if remaining is None:
            return True
        if not await self._card_has_actions(remaining):
            return True
        # Card may still be animating; treat click without error as success
        return True
