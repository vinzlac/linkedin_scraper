import logging
import re
from typing import List, Optional
from playwright.async_api import Page

from ..models.post import Post
from ..callbacks import ProgressCallback, SilentCallback
from .base import BaseScraper

logger = logging.getLogger(__name__)

FEED_URL = "https://www.linkedin.com/feed/"


class FeedScraper(BaseScraper):

    def __init__(self, page: Page, callback: Optional[ProgressCallback] = None):
        super().__init__(page, callback or SilentCallback())

    async def scrape(self, limit: int = 10) -> List[Post]:
        logger.info(f"Starting feed scraping (limit={limit})")
        await self.callback.on_start("feed", FEED_URL)

        await self.ensure_logged_in()
        await self.navigate_and_wait(FEED_URL)
        await self.callback.on_progress("Navigated to feed", 10)

        await self.check_rate_limit()

        await self._wait_for_feed_to_load()
        await self.callback.on_progress("Feed loaded", 20)

        posts = await self._scrape_posts(limit)
        await self.callback.on_progress(f"Scraped {len(posts)} posts", 100)
        await self.callback.on_complete("feed", posts)

        logger.info(f"Successfully scraped {len(posts)} posts from feed")
        return posts

    async def _wait_for_feed_to_load(self, timeout: int = 30000) -> None:
        try:
            await self.page.wait_for_load_state('domcontentloaded', timeout=timeout)
        except Exception as e:
            logger.debug(f"DOM load timeout: {e}")

        await self.page.wait_for_timeout(3000)

        for attempt in range(3):
            await self._trigger_lazy_load()

            has_posts = await self.page.evaluate('''() => {
                return document.body.innerHTML.includes('urn:li:activity:');
            }''')

            if has_posts:
                logger.debug(f"Feed posts found after attempt {attempt + 1}")
                return

            await self.page.wait_for_timeout(2000)

        logger.warning("Feed posts may not have loaded fully")

    async def _trigger_lazy_load(self) -> None:
        await self.page.evaluate('''() => {
            const scrollHeight = document.documentElement.scrollHeight;
            const steps = 8;
            const stepSize = Math.min(scrollHeight / steps, 400);
            for (let i = 1; i <= steps; i++) {
                setTimeout(() => window.scrollTo(0, stepSize * i), i * 200);
            }
        }''')
        await self.page.wait_for_timeout(2500)
        await self.page.evaluate('window.scrollTo(0, 400)')
        await self.page.wait_for_timeout(1000)

    async def _scrape_posts(self, limit: int) -> List[Post]:
        posts: List[Post] = []
        scroll_count = 0
        max_scrolls = (limit // 3) + 5

        while len(posts) < limit and scroll_count < max_scrolls:
            new_posts = await self._extract_posts_from_feed()

            for post in new_posts:
                if post.urn and not any(p.urn == post.urn for p in posts):
                    posts.append(post)
                    if len(posts) >= limit:
                        break

            if len(posts) < limit:
                await self._scroll_for_more_posts()
                scroll_count += 1

        return posts[:limit]

    async def _extract_posts_from_feed(self) -> List[Post]:
        posts_data = await self.page.evaluate('''() => {
            const posts = [];
            const html = document.body.innerHTML;

            const urnMatches = html.matchAll(/urn:li:activity:(\\d+)/g);
            const seenUrns = new Set();

            for (const match of urnMatches) {
                const urn = match[0];
                if (seenUrns.has(urn)) continue;
                seenUrns.add(urn);

                const el = document.querySelector(`[data-urn="${urn}"]`);
                if (!el) continue;

                // Filter out ads and sponsored content
                const elHtml = el.innerHTML;
                if (el.querySelector('[data-control-name="promoted"]')) continue;
                const labels = el.querySelectorAll('li, span');
                let isSponsored = false;
                labels.forEach(label => {
                    const t = (label.innerText || '').trim().toLowerCase();
                    if (t === 'promoted' || t === 'sponsorisé' || t === 'sponsored') {
                        isSponsored = true;
                    }
                });
                if (isSponsored) continue;

                // Filter out "People you may know" suggestion widgets
                if (el.querySelector('[data-control-name="pymk"]')) continue;
                if (elHtml.includes('people-you-may-know') || elHtml.includes('pymk')) continue;

                // Author name and URL
                let authorName = '';
                let authorUrl = '';
                const actorNameEl = el.querySelector(
                    '[class*="update-components-actor__name"], ' +
                    '[class*="feed-shared-actor__name"], ' +
                    '.update-components-actor__name'
                );
                if (actorNameEl) {
                    authorName = actorNameEl.innerText?.trim() || '';
                }
                const actorLinkEl = el.querySelector(
                    '[class*="update-components-actor__meta-link"], ' +
                    '[class*="feed-shared-actor__container-link"], ' +
                    'a[href*="/in/"], a[href*="/company/"]'
                );
                if (actorLinkEl) {
                    authorUrl = actorLinkEl.href || '';
                }

                // Text content
                let text = '';
                const textSelectors = [
                    '.feed-shared-update-v2__description',
                    '.update-components-text',
                    '.feed-shared-text',
                    '[data-test-id="main-feed-activity-card__commentary"]',
                    '.break-words.whitespace-pre-wrap'
                ];
                for (const sel of textSelectors) {
                    const textEl = el.querySelector(sel);
                    if (textEl) {
                        const t = textEl.innerText?.trim() || '';
                        if (t.length > text.length && t.length > 20) {
                            text = t;
                        }
                    }
                }

                if (!text || text.length < 20) continue;

                // Time
                const timeEl = el.querySelector(
                    '[class*="actor__sub-description"], ' +
                    '[class*="update-components-actor__sub-description"]'
                );
                const timeText = timeEl ? timeEl.innerText : '';

                // Reactions
                const reactionsEl = el.querySelector(
                    'button[aria-label*="reaction"], [class*="social-details-social-counts__reactions"]'
                );
                const reactions = reactionsEl ? reactionsEl.innerText : '';

                // Comments
                const commentsEl = el.querySelector('button[aria-label*="comment"]');
                const comments = commentsEl ? commentsEl.innerText : '';

                // Reposts
                const repostsEl = el.querySelector('button[aria-label*="repost"]');
                const reposts = repostsEl ? repostsEl.innerText : '';

                // Images
                const images = [];
                el.querySelectorAll('img[src*="media"]').forEach(img => {
                    if (img.src && !img.src.includes('profile') && !img.src.includes('logo')) {
                        images.push(img.src);
                    }
                });

                posts.push({
                    urn,
                    authorName,
                    authorUrl,
                    text: text.substring(0, 2000),
                    timeText,
                    reactions,
                    comments,
                    reposts,
                    images
                });
            }

            return posts;
        }''')

        result: List[Post] = []
        for data in posts_data:
            activity_id = data['urn'].replace('urn:li:activity:', '')
            post = Post(
                linkedin_url=f"https://www.linkedin.com/feed/update/urn:li:activity:{activity_id}/",
                urn=data['urn'],
                author_name=data.get('authorName') or None,
                author_url=data.get('authorUrl') or None,
                text=data['text'],
                posted_date=self._extract_time_from_text(data.get('timeText', '')),
                reactions_count=self._parse_count(data.get('reactions', '')),
                comments_count=self._parse_count(data.get('comments', '')),
                reposts_count=self._parse_count(data.get('reposts', '')),
                image_urls=data.get('images', []),
            )
            result.append(post)

        return result

    def _extract_time_from_text(self, text: str) -> Optional[str]:
        if not text:
            return None
        match = re.search(r'(\d+[hdwmy]|\d+\s*(?:hour|day|week|month|year)s?\s*ago)', text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        parts = text.split('•')
        if parts:
            return parts[0].strip()
        return None

    def _parse_count(self, text: str) -> Optional[int]:
        if not text:
            return None
        try:
            numbers = re.findall(r'[\d,]+', text.replace(',', ''))
            if numbers:
                return int(numbers[0])
        except Exception:
            pass
        return None

    async def _scroll_for_more_posts(self) -> None:
        try:
            await self.page.keyboard.press('End')
            await self.page.wait_for_timeout(2000)
        except Exception as e:
            logger.debug(f"Error scrolling feed: {e}")
