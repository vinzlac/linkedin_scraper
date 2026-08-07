#!/usr/bin/env python3
"""Debug script — explore LinkedIn invitation-manager DOM structure."""
import asyncio
import json
from pathlib import Path

from linkedin_scraper.core.browser import BrowserManager

INVITATIONS_URL = "https://www.linkedin.com/mynetwork/invitation-manager/"
SESSION_CANDIDATES = [
    Path("linkedin_session.json"),
    Path.home() / "Library/Application Support/linkedin-mcp/linkedin_session.json",
]


def _resolve_session() -> Path:
    for path in SESSION_CANDIDATES:
        if path.exists():
            return path
    raise FileNotFoundError(
        "No LinkedIn session found. Run `just session` or create linkedin_session.json."
    )


async def main() -> None:
    session = _resolve_session()
    print(f"Using session: {session}")

    async with BrowserManager(headless=True) as browser:
        await browser.load_session(str(session))
        page = browser.page

        print(f"Navigating to {INVITATIONS_URL} ...")
        await page.goto(INVITATIONS_URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(4000)

        print(f"Final URL: {page.url}")
        print(f"Title: {await page.title()}")

        summary = await page.evaluate(
            """() => {
            const pickAttrs = (el) => {
                const attrs = {};
                for (const a of el.attributes || []) {
                    if (
                        a.name.startsWith('data-') ||
                        a.name === 'id' ||
                        a.name === 'class' ||
                        a.name === 'aria-label' ||
                        a.name === 'href'
                    ) {
                        attrs[a.name] = a.value.slice(0, 200);
                    }
                }
                return attrs;
            };

            const cardSelectors = [
                'li.invitation-card',
                '[data-test-invitation-id]',
                '[componentkey*="Invitation"]',
                'div.invitation-card__container',
                'ul.mn-invitation-list li',
                'div.artdeco-list li',
                '[role="listitem"]',
            ];
            const counts = {};
            for (const sel of cardSelectors) {
                counts[sel] = document.querySelectorAll(sel).length;
            }

            const buttons = [...document.querySelectorAll('button')]
                .map(b => (b.getAttribute('aria-label') || b.innerText || '').trim())
                .filter(t => /accept|ignore|accepter|ignorer|delete|supprimer/i.test(t))
                .slice(0, 30);

            const invitationLike = [...document.querySelectorAll('[data-invitation-id],[data-test-invitation-id],[data-urn*="Invitation"],[data-urn*="invitation"]')]
                .slice(0, 10)
                .map(el => ({ tag: el.tagName, attrs: pickAttrs(el), text: (el.innerText || '').slice(0, 180) }));

            const sampleCards = [...document.querySelectorAll('li.invitation-card, ul.mn-invitation-list > li, [componentkey*="Invitation"]')]
                .slice(0, 5)
                .map(el => ({
                    tag: el.tagName,
                    attrs: pickAttrs(el),
                    html: el.outerHTML.slice(0, 1500),
                    text: (el.innerText || '').slice(0, 300),
                }));

            return {
                counts,
                buttons,
                invitationLike,
                sampleCards,
                bodySnippet: document.body.innerText.slice(0, 800),
            };
        }"""
        )

        out = Path("output/debug_invitations.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({k: summary[k] for k in ("counts", "buttons")}, ensure_ascii=False, indent=2))
        print(f"\nFull dump: {out}")
        print(f"\nBody snippet:\n{summary.get('bodySnippet', '')[:500]}")


if __name__ == "__main__":
    asyncio.run(main())
