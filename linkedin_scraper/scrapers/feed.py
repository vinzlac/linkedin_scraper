import logging
import re
from urllib.parse import urlparse
from typing import Any, Dict, List, Optional
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from ..models.post import Post
from ..callbacks import ProgressCallback, SilentCallback
from .base import BaseScraper

logger = logging.getLogger(__name__)

FEED_URL = "https://www.linkedin.com/feed/"

# Wait for at least one Republier/Repost action button to appear (one per feed post)
_WAIT_FOR_FEED_JS = (
    "() => Array.from(document.querySelectorAll('button'))"
    ".some(function(b){var t=(b.innerText||'').trim();return t==='Republier'||t==='Repost';})"
)


class FeedScraper(BaseScraper):

    def __init__(self, page: Page, callback: Optional[ProgressCallback] = None):
        super().__init__(page, callback or SilentCallback())

    async def scrape(self, limit: int = 10) -> List[Post]:
        logger.info(f"Starting feed scraping (limit={limit})")
        await self.callback.on_start("feed", FEED_URL)

        await self.navigate_and_wait(FEED_URL)
        await self.callback.on_progress("Navigated to feed", 10)
        await self.ensure_logged_in()

        await self.check_rate_limit()

        # Bring browser to front and scroll to trigger lazy-loading
        try:
            await self.page.bring_to_front()
        except Exception:
            pass
        await self.page.wait_for_timeout(3000)
        await self.page.evaluate("window.scrollBy(0, 1200)")
        await self.page.wait_for_timeout(2000)

        # Wait for at least one post's action button to appear
        try:
            await self.page.wait_for_function(_WAIT_FOR_FEED_JS, timeout=40000)
        except PlaywrightTimeoutError:
            diag = await self.page.evaluate(r"""() => ({
                url: location.href,
                title: document.title,
                buttons: Array.from(document.querySelectorAll("button"))
                    .map(function(b){ return (b.innerText||"").trim(); })
                    .filter(function(t){ return t.length > 0; })
                    .slice(0, 10),
            })""")
            logger.warning(
                "Feed posts not loaded after 40s. url=%s title=%s buttons=%s",
                diag.get("url"),
                diag.get("title"),
                diag.get("buttons"),
            )
            return []

        await self.page.wait_for_timeout(2000)
        await self.callback.on_progress("Feed loaded", 20)

        posts = await self._scrape_posts(limit)
        await self.callback.on_progress(f"Scraped {len(posts)} posts", 100)
        await self.callback.on_complete("feed", posts)

        logger.info(f"Successfully scraped {len(posts)} posts from feed")
        return posts

    async def _scrape_posts(self, limit: int) -> List[Post]:
        posts: List[Post] = []
        scroll_attempts = 0
        max_scrolls = limit * 3 + 10

        while len(posts) < limit and scroll_attempts < max_scrolls:
            new_posts = await self._extract_posts_from_feed()

            for post in new_posts:
                if post.urn and not any(p.urn == post.urn for p in posts):
                    posts.append(post)
                    if len(posts) >= limit:
                        break

            if len(posts) < limit:
                await self._scroll_for_more_posts()
                scroll_attempts += 1

        return posts[:limit]

    async def _extract_posts_from_feed(self) -> List[Post]:
        posts_data = await self.page.evaluate("""() => {
            var repostBtns = Array.from(document.querySelectorAll("button")).filter(function(b) {
                var t = (b.innerText || "").trim();
                return t === "Republier" || t === "Repost";
            });

            var results = [];
            var seenUrns = {};
            var seenContainers = [];

            // isTimeLine: line starts with a relative time expression and is short enough
            var timeRe = /^(\\d+\\s*(j|h|d|w|sem\\.?|an|min|mois?|y)|maintenant|just now|hier|yesterday)/i;
            function isTimeLine(line) { return line.length < 55 && timeRe.test(line); }
            // isDegree: short line like "• 2e" or "• 3e et +" (degree indicator in reshared headers)
            function isDegree(line) { return line.length < 16 && /\\d+e(\\s+et\\s+\\+)?$/.test(line); }

            function normalizeLinkedInHref(href) {
                if (!href) return "";
                var s = String(href).trim();
                if (!s) return "";
                if (s.indexOf("//") === 0) return "https:" + s;
                if (s.indexOf("http") === 0) return s;
                if (s.charAt(0) === "/") return "https://www.linkedin.com" + s;
                return "";
            }
            function ensureTrailingSlashOnFeedUpdate(url) {
                if (!url || url.indexOf("/feed/update/") === -1) return url;
                return url.charAt(url.length - 1) === "/" ? url : url + "/";
            }
            /** Activity numeric id from any string (href with query, encoded URN, /posts/ slug). */
            function extractActivityIdFromText(text) {
                if (!text) return "";
                var t = String(text);
                var dec = t;
                try { dec = decodeURIComponent(t); } catch (e0) { dec = t; }
                var m = dec.match(/urn:li:activity:(\\d+)/) || t.match(/urn:li:activity:(\\d+)/);
                if (m) return m[1];
                m = dec.match(/activity-(\\d{10,})-/) || t.match(/activity-(\\d{10,})-/);
                if (m) return m[1];
                return "";
            }
            function feedUpdatePermalinkFromActivityId(id) {
                if (!id) return "";
                return ensureTrailingSlashOnFeedUpdate(
                    "https://www.linkedin.com/feed/update/urn:li:activity:" + id
                );
            }
            /**
             * Prefer direct post URL from DOM (href). Handles compkey cards when activity sits in
             * query params, reposts (several ids — prefer /feed/update/ or /posts/), data-urn, innerHTML.
             */
            function extractPermalinkFromContainer(root) {
                if (!root) return "";
                var links = root.querySelectorAll("a[href]");
                var i, raw, k, variants, v, pathOnly, full;
                // 1) Canonical /feed/update/… path with activity in path
                for (i = 0; i < links.length; i++) {
                    raw = links[i].getAttribute("href") || "";
                    if (!raw) continue;
                    variants = [raw];
                    try { variants.push(decodeURIComponent(raw)); } catch (eDec) {}
                    for (k = 0; k < variants.length; k++) {
                        v = variants[k];
                        if (v.indexOf("/feed/update/") === -1) continue;
                        pathOnly = v.split("#")[0].split("?")[0];
                        full = normalizeLinkedInHref(pathOnly);
                        if (full && /urn:li:activity:\\d+/.test(full)) {
                            return ensureTrailingSlashOnFeedUpdate(full);
                        }
                    }
                }
                for (i = 0; i < links.length; i++) {
                    raw = links[i].getAttribute("href") || "";
                    if (!raw) continue;
                    try { v = decodeURIComponent(raw.split("#")[0]); } catch (e2) { v = raw.split("#")[0]; }
                    if (v.indexOf("/feed/update/") === -1) continue;
                    if (/urn:li:activity:\\d+/.test(v)) {
                        full = normalizeLinkedInHref(v.split("?")[0]);
                        if (full) return ensureTrailingSlashOnFeedUpdate(full);
                    }
                }
                // 2) /posts/… slugs
                for (i = 0; i < links.length; i++) {
                    raw = links[i].getAttribute("href") || "";
                    if (!raw) continue;
                    pathOnly = raw.split("#")[0].split("?")[0];
                    full = normalizeLinkedInHref(pathOnly);
                    if (full && full.indexOf("/posts/") !== -1) return full;
                }
                // 3) Activity id anywhere in href (query string, encoded) — typical for newer cards / reposts
                var candidates = [];
                for (i = 0; i < links.length; i++) {
                    raw = links[i].getAttribute("href") || "";
                    var aid = extractActivityIdFromText(raw);
                    if (aid) candidates.push({ id: aid, href: raw });
                }
                if (candidates.length === 1) {
                    return feedUpdatePermalinkFromActivityId(candidates[0].id);
                }
                if (candidates.length > 1) {
                    for (k = 0; k < candidates.length; k++) {
                        if (candidates[k].href.indexOf("/feed/update/") !== -1) {
                            return feedUpdatePermalinkFromActivityId(candidates[k].id);
                        }
                    }
                    try {
                        var decH = "";
                        for (k = 0; k < candidates.length; k++) {
                            try { decH = decodeURIComponent(candidates[k].href); } catch (eH) { decH = candidates[k].href; }
                            if (decH.indexOf("/feed/update/") !== -1) {
                                return feedUpdatePermalinkFromActivityId(candidates[k].id);
                            }
                        }
                    } catch (eK) {}
                    for (k = 0; k < candidates.length; k++) {
                        if (candidates[k].href.indexOf("/posts/") !== -1) {
                            return feedUpdatePermalinkFromActivityId(candidates[k].id);
                        }
                    }
                    return feedUpdatePermalinkFromActivityId(candidates[candidates.length - 1].id);
                }
                // 4) data-urn descendants (may expose activity while card URN stays compkey)
                var duNodes = root.querySelectorAll("[data-urn]");
                for (i = 0; i < duNodes.length; i++) {
                    var du = duNodes[i].getAttribute("data-urn") || "";
                    var aidDu = extractActivityIdFromText(du);
                    if (aidDu) return feedUpdatePermalinkFromActivityId(aidDu);
                }
                // 5) Last activity URN in subtree HTML (repost: nested original often appears after header chrome)
                var html = root.innerHTML || "";
                var reGlob = /urn:li:activity:(\\d+)/g;
                var mm;
                var lastId = "";
                while ((mm = reGlob.exec(html)) !== null) {
                    lastId = mm[1];
                }
                if (lastId) return feedUpdatePermalinkFromActivityId(lastId);
                return "";
            }
            function pushUnique(arr, value) {
                if (!value) return;
                if (arr.indexOf(value) === -1) arr.push(value);
            }
            function collectIdentifiersAndPermalinkCandidates(root, baseUrn, basePermalink, compEls) {
                var identifierCandidates = [];
                var permalinkCandidates = [];
                var componentKeys = [];

                if (baseUrn) pushUnique(identifierCandidates, baseUrn);
                if (basePermalink) pushUnique(permalinkCandidates, ensureTrailingSlashOnFeedUpdate(basePermalink));

                // component keys (raw + normalized compkey urn)
                for (var i = 0; i < compEls.length; i++) {
                    var ck = compEls[i].getAttribute("componentkey") || "";
                    if (!ck) continue;
                    pushUnique(componentKeys, ck);
                    var base = ck.replace(/^expanded/, "").replace(/FeedType_.*$/, "");
                    if (base.length > 10) {
                        pushUnique(identifierCandidates, "urn:li:compkey:" + base);
                    }
                    var aidCk = extractActivityIdFromText(ck);
                    if (aidCk) pushUnique(identifierCandidates, "urn:li:activity:" + aidCk);
                }

                // data-urn and other attrs
                var duNodes = root.querySelectorAll("[data-urn]");
                for (var j = 0; j < duNodes.length; j++) {
                    var du = duNodes[j].getAttribute("data-urn") || "";
                    if (!du) continue;
                    var aidDu = extractActivityIdFromText(du);
                    if (aidDu) {
                        pushUnique(identifierCandidates, "urn:li:activity:" + aidDu);
                        pushUnique(permalinkCandidates, feedUpdatePermalinkFromActivityId(aidDu));
                    }
                }

                // href-based candidates
                var links = root.querySelectorAll("a[href]");
                for (var k = 0; k < links.length; k++) {
                    var href = links[k].getAttribute("href") || "";
                    if (!href) continue;
                    var fullHref = normalizeLinkedInHref(href) || normalizeLinkedInHref(href.split("?")[0]);
                    if (fullHref && (fullHref.indexOf("/feed/update/") !== -1 || fullHref.indexOf("/posts/") !== -1)) {
                        pushUnique(permalinkCandidates, ensureTrailingSlashOnFeedUpdate(fullHref.split("#")[0]));
                    }
                    var aidHref = extractActivityIdFromText(href);
                    if (aidHref) {
                        pushUnique(identifierCandidates, "urn:li:activity:" + aidHref);
                        pushUnique(permalinkCandidates, feedUpdatePermalinkFromActivityId(aidHref));
                    }
                }

                // last resort: activity IDs in HTML
                var html = root.innerHTML || "";
                var reGlob = /urn:li:activity:(\\d+)/g;
                var mm;
                while ((mm = reGlob.exec(html)) !== null) {
                    var urnA = "urn:li:activity:" + mm[1];
                    pushUnique(identifierCandidates, urnA);
                    pushUnique(permalinkCandidates, feedUpdatePermalinkFromActivityId(mm[1]));
                }

                return {
                    identifierCandidates: identifierCandidates,
                    permalinkCandidates: permalinkCandidates,
                    componentKeys: componentKeys,
                };
            }

            for (var bi = 0; bi < repostBtns.length; bi++) {
                var btn = repostBtns[bi];

                var el = btn.parentElement;
                while (el && el !== document.body) {
                    var parent = el.parentElement;
                    if (!parent || parent === document.body) break;
                    var parentCount = Array.from(parent.querySelectorAll("button")).filter(function(b) {
                        var t = (b.innerText || "").trim();
                        return t === "Republier" || t === "Repost";
                    }).length;
                    if (parentCount > 1) break;
                    el = el.parentElement;
                }

                if (!el || el === document.body) continue;
                if (seenContainers.indexOf(el) >= 0) continue;
                seenContainers.push(el);

                // ---- URN + permalink URL extraction ----
                // DOM permalink first (handles urn:li:compkey when href still points to activity URL)
                var urn = "";
                var permalinkUrl = extractPermalinkFromContainer(el);

                // Strategy 0: data-urn attribute — LinkedIn's stable anchor per CLAUDE.md
                var urnEls = el.querySelectorAll("[data-urn]");
                for (var i = 0; i < urnEls.length && !urn; i++) {
                    var du = urnEls[i].getAttribute("data-urn") || "";
                    var m = du.match(/urn:li:activity:(\\d+)/);
                    if (m) urn = m[0];
                }
                if (!urn) {
                    var du = el.getAttribute("data-urn") || "";
                    var m = du.match(/urn:li:activity:(\\d+)/);
                    if (m) urn = m[0];
                }

                var compEls = el.querySelectorAll("[componentkey]");

                if (!urn) {
                for (var i = 0; i < compEls.length && !urn; i++) {
                    var ck = compEls[i].getAttribute("componentkey") || "";
                    var m = ck.match(/urn:li:activity:(\\d+)/);
                    if (m) urn = m[0];
                }
                }

                // Strategy 2: /posts/ permalink — captures the canonical URL directly
                if (!urn || !permalinkUrl) {
                    var postLinks = el.querySelectorAll("a[href*='/posts/']");
                    for (var i = 0; i < postLinks.length; i++) {
                        var href = postLinks[i].getAttribute("href") || "";
                        // Strip query string for clean URL
                        var cleanHref = href.split("?")[0];
                        if (!permalinkUrl && cleanHref.includes("/posts/")) {
                            permalinkUrl = cleanHref.startsWith("http")
                                ? cleanHref
                                : "https://www.linkedin.com" + cleanHref;
                        }
                        if (!urn) {
                            var m = href.match(/activity-(\\d{15,})-/);
                            if (m) urn = "urn:li:activity:" + m[1];
                        }
                        if (urn && permalinkUrl) break;
                    }
                }

                // Strategy 3: /feed/update/ permalink — LinkedIn's standard share URL format,
                // also used as the timestamp anchor link
                if (!urn || !permalinkUrl) {
                    var feedLinks = el.querySelectorAll("a[href*='/feed/update/']");
                    for (var i = 0; i < feedLinks.length; i++) {
                        var href = feedLinks[i].getAttribute("href") || "";
                        var cleanHref = href.split("?")[0];
                        var m = cleanHref.match(/urn:li:activity:(\\d+)/);
                        if (m) {
                            if (!urn) urn = "urn:li:activity:" + m[1];
                            if (!permalinkUrl) {
                                permalinkUrl = cleanHref.startsWith("http")
                                    ? cleanHref
                                    : "https://www.linkedin.com" + cleanHref;
                            }
                        }
                        if (urn && permalinkUrl) break;
                    }
                }

                if (!urn) {
                    var allEls = el.querySelectorAll("*");
                    for (var i = 0; i < allEls.length && !urn; i++) {
                        var attrs = allEls[i].attributes;
                        for (var j = 0; j < attrs.length && !urn; j++) {
                            var m = attrs[j].value.match(/urn:li:activity:(\\d+)/);
                            if (m) urn = m[0];
                        }
                    }
                }

                if (!urn) {
                    var m = (el.innerHTML || "").match(/urn:li:activity:(\\d+)/);
                    if (m) urn = m[0];
                }

                if (!urn) {
                    for (var i = 0; i < compEls.length && !urn; i++) {
                        var ck = compEls[i].getAttribute("componentkey") || "";
                        var base = ck.replace(/^expanded/, "").replace(/FeedType_.*$/, "");
                        if (base.length > 10) { urn = "urn:li:compkey:" + base; break; }
                    }
                }

                if (!urn || seenUrns[urn]) continue;
                seenUrns[urn] = true;

                var elText = el.innerText || "";
                var allLines = elText.split("\\n").map(function(l){ return l.trim(); }).filter(Boolean);

                if (
                    elText.includes("Sponsorisé") || elText.includes("Sponsored") ||
                    elText.includes("Promoted") || el.querySelector("[data-control-name='promoted']")
                ) continue;

                // ---- Detect activity post (liked/commented/reshared) ----
                // allLines[1] = "Y a commenté ce contenu" / "Y aime ce contenu"
                // Y = actor (network contact who triggered the feed entry)
                // X = original author (the person who wrote the post)
                var actorName = "";
                var actorUrl = "";
                var actionTakerName = "";
                var line1 = (allLines[1] || "");
                var actKwPat = /\\s(a\\s+comment|a\\s+r\u00e9pondu|a\\s+republi|aime\\s|a\\s+aim|a\\s+r\u00e9agi|a\\s+partag|commented|liked|reshared|reposted|reacted)/i;
                var actMatch = line1.match(actKwPat);
                if (actMatch && actMatch.index > 0) {
                    actionTakerName = line1.substring(0, actMatch.index).trim().toLowerCase();
                    // Resolve actor's profile URL from the first /in/ link that matches their name
                    var inLinksAll = el.querySelectorAll("a[href*='/in/']");
                    for (var i = 0; i < inLinksAll.length && !actorUrl; i++) {
                        var href = inLinksAll[i].getAttribute("href") || "";
                        var m = href.match(/[/]in[/][^/?#]+/);
                        if (!m) continue;
                        var nameSpan = inLinksAll[i].querySelector("span[aria-hidden='true']");
                        var rawText = nameSpan ? (nameSpan.innerText || "").trim() : (inLinksAll[i].innerText || "").trim();
                        var candidate = rawText.split("\\n")[0].trim()
                            .replace(/\\s*[^\\w\\s]\\s*(\\d+e(\\s+et\\s+\\+)?|Suivi|Following)[\\s\\S]*$/, "").trim();
                        if (candidate.toLowerCase() === actionTakerName) {
                            actorName = candidate;
                            actorUrl = "https://www.linkedin.com" + m[0];
                        }
                    }
                    if (!actorName) actorName = line1.substring(0, actMatch.index).trim();
                }

                // ---- Author (original content creator) ----
                var authorName = "";
                var authorUrl = "";
                var inLinks = el.querySelectorAll("a[href*='/in/']");
                for (var i = 0; i < inLinks.length && !authorName; i++) {
                    var href = inLinks[i].getAttribute("href") || "";
                    var m = href.match(/[/]in[/][^/?#]+/);
                    if (!m) continue;
                    var nameSpan = inLinks[i].querySelector("span[aria-hidden='true']");
                    var rawText = nameSpan ? (nameSpan.innerText || "").trim() : (inLinks[i].innerText || "").trim();
                    var candidate = rawText.split("\\n")[0].trim()
                        .replace(/\\s*[^\\w\\s]\\s*(\\d+e(\\s+et\\s+\\+)?|Suivi|Following)[\\s\\S]*$/, "").trim();
                    if (candidate.length < 2) continue;
                    if (actionTakerName && candidate.toLowerCase() === actionTakerName) continue;
                    authorUrl = "https://www.linkedin.com" + m[0];
                    authorName = candidate;
                }
                if (!authorName) {
                    var compLinks = el.querySelectorAll("a[href*='/company/']");
                    for (var i = 0; i < compLinks.length && !authorName; i++) {
                        var href = compLinks[i].getAttribute("href") || "";
                        var m = href.match(/[/]company[/][^/?#]+/);
                        if (!m) continue;
                        var nameSpan = compLinks[i].querySelector("span[aria-hidden='true']");
                        var rawText = nameSpan ? (nameSpan.innerText || "").trim() : (compLinks[i].innerText || "").trim();
                        var candidate = rawText.split("\\n")[0].trim();
                        if (candidate.length < 2) continue;
                        authorUrl = "https://www.linkedin.com" + m[0];
                        authorName = candidate;
                    }
                }
                if (!authorName) {
                    var fallback = actionTakerName ? (allLines[2] || "") : (allLines[1] || "");
                    fallback = fallback.replace(/\\s*(a\\s+|aime|comment|publi|r\u00e9agi).*$/i, "").trim();
                    if (fallback.length > 1 && !isTimeLine(fallback) && !isDegree(fallback)) {
                        authorName = fallback;
                    }
                }

                // ---- Published date ----
                var publishedAt = "";
                var timeEl = el.querySelector("time");
                if (timeEl) {
                    publishedAt = (timeEl.getAttribute("datetime") || timeEl.innerText || "").trim();
                }
                if (!publishedAt) {
                    for (var i = 0; i < allLines.length && !publishedAt; i++) {
                        if (isTimeLine(allLines[i])) {
                            publishedAt = allLines[i].replace(/\\s*(\\W+\\s*)+$/, "").trim();
                        }
                    }
                }

                // ---- Post text ----
                // Only the bottom action bar terminates the content.
                // Profile-level buttons ("Suivre", "Se connecter") appear BEFORE content
                // in activity posts (liked/commented/reshared) — do NOT treat them as terminators.
                var actionWords = {
                    "J'aime": 1, "Like": 1, "Commenter": 1, "Comment": 1,
                    "Republier": 1, "Repost": 1, "Envoyer": 1, "Send": 1,
                    "Voir plus": 1, "See more": 1,
                    "… plus": 1, "Afficher la traduction": 1, "Show translation": 1,
                };

                var startIdx = -1;
                var endIdx = allLines.length;
                for (var i = 0; i < allLines.length; i++) {
                    if (startIdx < 0 && isTimeLine(allLines[i])) startIdx = i + 1;
                    if (actionWords[allLines[i]]) { endIdx = i; break; }
                }

                // Skip profile-level follow/connect buttons that appear right after the date
                // in activity posts (structure: ... DATE, Suivre, CONTENT...)
                while (startIdx >= 0 && startIdx < endIdx &&
                       (allLines[startIdx] === "Suivre" || allLines[startIdx] === "Follow" ||
                        allLines[startIdx] === "Se connecter" || allLines[startIdx] === "Connect" ||
                        allLines[startIdx] === "Suivi" || allLines[startIdx] === "Following")) {
                    startIdx++;
                }

                // For reshared posts where the reposter added their own commentary:
                // lines after the reposter's date → [commentary], [reshared author block]
                // Detect via degree indicator within 6 lines.
                if (startIdx >= 0) {
                    var degreeAt = -1;
                    for (var k = startIdx; k < Math.min(startIdx + 6, endIdx); k++) {
                        if (isDegree(allLines[k])) { degreeAt = k; break; }
                    }
                    if (degreeAt >= 0) {
                        var commentary = allLines.slice(startIdx, degreeAt).join(" ").trim();
                        if (commentary.length > 15) {
                            endIdx = degreeAt;
                        } else {
                            var nextDateIdx = -1;
                            for (var k = degreeAt + 1; k < endIdx; k++) {
                                if (isTimeLine(allLines[k])) { nextDateIdx = k + 1; break; }
                            }
                            if (nextDateIdx >= 0 && nextDateIdx < endIdx) {
                                startIdx = nextDateIdx;
                                // Also skip follow/connect after the reshared date
                                while (startIdx < endIdx &&
                                       (allLines[startIdx] === "Suivre" || allLines[startIdx] === "Follow" ||
                                        allLines[startIdx] === "Se connecter" || allLines[startIdx] === "Connect")) {
                                    startIdx++;
                                }
                            }
                        }
                    }
                }

                var content = "";
                if (startIdx >= 0 && startIdx < endIdx) {
                    content = allLines.slice(startIdx, endIdx).join("\\n").trim();
                }
                content = content.slice(0, 3000);

                // ---- Images ----
                // Collect LinkedIn CDN image URLs (feedshare images, not avatars/logos).
                // LinkedIn lazy-loads images via data-delayed-url or data-src before setting src.
                var images = [];
                var seenImgUrls = {};
                var imgEls = el.querySelectorAll("img");
                for (var i = 0; i < imgEls.length; i++) {
                    var src = imgEls[i].getAttribute("data-delayed-url") ||
                              imgEls[i].getAttribute("data-src") ||
                              imgEls[i].getAttribute("src") || "";
                    if (!src) continue;
                    // Only keep LinkedIn media CDN images; skip avatars and logos
                    if (!src.includes("media.licdn.com")) continue;
                    if (src.includes("/profile-") || src.includes("ghost-") ||
                        src.includes("/company-logo") || src.includes("logo")) continue;
                    var cleanSrc = src.split("?")[0];
                    if (!seenImgUrls[cleanSrc]) {
                        seenImgUrls[cleanSrc] = true;
                        images.push(src);
                    }
                }

                // ---- Reactions / comments ----
                var reactionsText = "";
                var commentsText = "";
                // Scan button aria-labels for counts — extract the leading number only
                var btns = el.querySelectorAll("button[aria-label]");
                for (var i = 0; i < btns.length; i++) {
                    var label = (btns[i].getAttribute("aria-label") || "").toLowerCase();
                    var btext = (btns[i].innerText || "").trim();
                    // Prefer button text if it's numeric; else extract leading number from label
                    var numMatch = btext.match(/^\\d[\\d.,k\\s]*/) || label.match(/^\\d[\\d.,k\\s]*/);
                    if (label.includes("reaction") || label.includes("réaction") ||
                            label.includes("réagi") || label.includes("personnes")) {
                        if (!reactionsText && numMatch) reactionsText = numMatch[0].trim();
                    } else if (
                        (label.includes("comment") || label.includes("commentaire")) &&
                        label !== "commenter" && label !== "comment"
                    ) {
                        if (!commentsText && numMatch) commentsText = numMatch[0].trim();
                    }
                }
                // Fallback: scan text lines for "NNN réactions" / "NNN commentaires"
                if (!reactionsText || !commentsText) {
                    var reactLineRe = /^(\\d[\\d\\s.,]*k?)\\s*(r\\u00e9actions?|reactions?)/i;
                    var commentLineRe = /^(\\d[\\d\\s.,]*k?)\\s*(commentaires?|comments?)/i;
                    for (var i = 0; i < allLines.length; i++) {
                        if (!reactionsText) {
                            var m = allLines[i].match(reactLineRe);
                            if (m) reactionsText = m[1].trim();
                        }
                        if (!commentsText) {
                            var m = allLines[i].match(commentLineRe);
                            if (m) commentsText = m[1].trim();
                        }
                    }
                }

                // ---- Video ----
                // 1. Native LinkedIn video: <video> element with data-sources JSON or src
                // 2. External embed: <iframe> with youtube.com/embed or similar
                // Note: native LinkedIn video URLs require auth cookies to stream outside LinkedIn.
                var videoUrl = "";
                var videoEl = el.querySelector("video");
                if (videoEl) {
                    // data-sources is a JSON array of {src, type} objects
                    var dataSources = videoEl.getAttribute("data-sources") || "";
                    if (dataSources) {
                        try {
                            var sources = JSON.parse(dataSources);
                            // Prefer MP4, then DASH (.mpd), then HLS (.m3u8)
                            var mp4 = "", dash = "", hls = "";
                            for (var si = 0; si < sources.length; si++) {
                                var s = sources[si].src || "";
                                if (!mp4 && s.includes(".mp4")) mp4 = s;
                                if (!dash && s.includes(".mpd")) dash = s;
                                if (!hls && s.includes(".m3u8")) hls = s;
                            }
                            videoUrl = mp4 || dash || hls || (sources[0] && sources[0].src) || "";
                        } catch(e) {}
                    }
                    if (!videoUrl) {
                        videoUrl = videoEl.getAttribute("src") ||
                                   videoEl.querySelector("source") && videoEl.querySelector("source").getAttribute("src") || "";
                    }
                }
                // External embed (YouTube, Vimeo, etc.)
                if (!videoUrl) {
                    var iframeEl = el.querySelector("iframe[src]");
                    if (iframeEl) videoUrl = iframeEl.getAttribute("src") || "";
                }
                // Reject blob: URLs — they are browser-internal and not portable
                if (videoUrl.startsWith("blob:")) videoUrl = "";

                // ---- External link (lnkd.in shortlinks and other non-LinkedIn URLs) ----
                // Collect first external link for article_url; lnkd.in ones are resolved in Python.
                var externalUrl = "";
                var allLinks = el.querySelectorAll("a[href]");
                for (var i = 0; i < allLinks.length && !externalUrl; i++) {
                    var href = allLinks[i].getAttribute("href") || "";
                    if (!href || href.startsWith("#") || href.startsWith("javascript")) continue;
                    var full = href.startsWith("http") ? href : "https://www.linkedin.com" + href;
                    // Skip LinkedIn-internal URLs; keep external ones and lnkd.in shortlinks
                    if (full.includes("linkedin.com") && !full.includes("lnkd.in")) continue;
                    externalUrl = full;
                }

                if (!permalinkUrl) {
                    permalinkUrl = extractPermalinkFromContainer(el);
                }
                var debugCandidates = collectIdentifiersAndPermalinkCandidates(el, urn, permalinkUrl, compEls);

                results.push({
                    urn: urn,
                    permalinkUrl: permalinkUrl,
                    identifierCandidates: debugCandidates.identifierCandidates,
                    permalinkCandidates: debugCandidates.permalinkCandidates,
                    componentKeys: debugCandidates.componentKeys,
                    authorName: authorName,
                    authorUrl: authorUrl,
                    actorName: actorName,
                    actorUrl: actorUrl,
                    publishedAt: publishedAt,
                    content: content,
                    reactionsText: reactionsText,
                    commentsText: commentsText,
                    images: images,
                    videoUrl: videoUrl,
                    externalUrl: externalUrl,
                });
            }

            return results;
        }""")
        posts_data = await self._fill_missing_permalinks_from_ui(posts_data)

        result: List[Post] = []
        for data in posts_data:
            urn = data["urn"]
            permalink = data.get("permalinkUrl") or None
            permalink_candidates = data.get("permalinkCandidates", []) or []
            linkedin_url = self._finalize_linkedin_url(permalink, urn, permalink_candidates)

            external_url = data.get("externalUrl") or None
            if external_url:
                external_url = await self._resolve_url(external_url)

            post = Post(
                linkedin_url=linkedin_url,
                urn=urn,
                identifier_candidates=data.get("identifierCandidates", []),
                permalink_candidates=permalink_candidates,
                component_keys=data.get("componentKeys", []),
                ui_permalink_fallback_status=data.get("uiPermalinkFallbackStatus") or None,
                ui_permalink_fallback_error=data.get("uiPermalinkFallbackError") or None,
                author_name=data.get("authorName") or None,
                author_url=data.get("authorUrl") or None,
                actor_name=data.get("actorName") or None,
                actor_url=data.get("actorUrl") or None,
                text=data.get("content") or None,
                posted_date=self._clean_date(data.get("publishedAt", "")),
                reactions_count=self._parse_count(data.get("reactionsText", "")),
                comments_count=self._parse_count(data.get("commentsText", "")),
                reposts_count=self._parse_count(data.get("repostsText", "")),
                image_urls=data.get("images", []),
                video_url=data.get("videoUrl") or None,
                article_url=external_url,
            )
            result.append(post)

        return result

    async def _fill_missing_permalinks_from_ui(
        self,
        posts_data: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Try to recover missing permalinks via resilient UI interactions.

        This is a best-effort fallback for feed cards exposing only `compkey` in DOM.
        It must never fail scraping: errors are returned in per-post attributes.
        """
        for data in posts_data:
            if data.get("permalinkUrl"):
                data["uiPermalinkFallbackStatus"] = "not_needed"
                continue

            data["uiPermalinkFallbackStatus"] = "no_permalink_found"
            errors: List[str] = []
            component_keys = data.get("componentKeys", []) or []

            # Keep only likely card-level keys (skip random UUID-like component keys).
            card_keys: List[str] = []
            for key in component_keys:
                if not isinstance(key, str):
                    continue
                base = key.replace("expanded", "")
                if "FeedType_" in base:
                    base = base.split("FeedType_", 1)[0]
                if len(base) < 16:
                    continue
                if base.count("-") >= 4:
                    continue
                if base not in card_keys:
                    card_keys.append(base)

            card_locator = None
            for key in card_keys:
                try:
                    locator = self.page.locator(f'[componentkey*="{key}"]').first
                    count = await locator.count()
                    if count > 0:
                        card_locator = locator
                        break
                except Exception as e:
                    errors.append(f"card_lookup_failed:{e}")

            if card_locator is None:
                data["uiPermalinkFallbackError"] = "; ".join(errors + ["card_not_found"])
                continue

            # 1) Liens uniquement dans la carte (sans menu) — évite les faux positifs globaux
            card_dom_candidates: List[str] = []
            try:
                card_dom_candidates = await card_locator.evaluate(
                    """(root) => {
                        function abs(href) {
                            if (!href) return "";
                            if (href.startsWith("//")) return "https:" + href;
                            if (href.startsWith("http")) return href;
                            if (href.startsWith("/")) return "https://www.linkedin.com" + href;
                            return "";
                        }
                        function junk(u) {
                            if (!u) return true;
                            try {
                                var p = new URL(u).pathname.replace(/\\/+$/, "");
                                if (/^\\/company\\/[^\\/]+\\/posts$/.test(p)) return true;
                            } catch (e) {}
                            return false;
                        }
                        function addIf(list, url) {
                            if (!url || junk(url)) return;
                            if (url.indexOf("/feed/update/") !== -1 && url.charAt(url.length - 1) !== "/") url = url + "/";
                            if (list.indexOf(url) === -1) list.push(url);
                        }
                        const out = [];
                        const links = root.querySelectorAll("a[href]");
                        for (var i = 0; i < links.length; i++) {
                            var href = links[i].getAttribute("href") || "";
                            var dec = href;
                            try { dec = decodeURIComponent(href); } catch (e2) {}
                            if (href.indexOf("/feed/update/") !== -1 || dec.indexOf("/feed/update/") !== -1) {
                                var pick = dec.indexOf("/feed/update/") !== -1 ? dec : href;
                                addIf(out, abs(pick.split("#")[0].split("?")[0]));
                            }
                            if (href.indexOf("/posts/") !== -1) addIf(out, abs(href.split("#")[0].split("?")[0]));
                            var m = dec.match(/urn:li:activity:(\\d+)/) || href.match(/urn:li:activity:(\\d+)/);
                            if (m) addIf(out, "https://www.linkedin.com/feed/update/urn:li:activity:" + m[1] + "/");
                        }
                        return out.slice(0, 12);
                    }"""
                )
            except Exception as e:
                errors.append(f"card_dom_scan_failed:{e}")

            if card_dom_candidates:
                data["permalinkCandidates"] = list(
                    dict.fromkeys((data.get("permalinkCandidates", []) or []) + card_dom_candidates)
                )
                data["permalinkUrl"] = data["permalinkUrl"] or card_dom_candidates[0]
                data["uiPermalinkFallbackStatus"] = "resolved_via_card_dom"
                try:
                    await self.page.keyboard.press("Escape")
                except Exception:
                    pass
                continue

            menu_button_selectors = [
                'button[aria-label*="Plus"]',
                'button[aria-label*="More"]',
                'button[aria-label*="menu"]',
                'button[aria-label*="Menu"]',
                'button[data-control-name*="overflow"]',
                '[data-control-name="overflow_menu"]',
            ]
            menu_btn = None
            for selector in menu_button_selectors:
                try:
                    candidate = card_locator.locator(selector).first
                    if await candidate.count() and await candidate.is_visible():
                        menu_btn = candidate
                        break
                except Exception:
                    continue

            if menu_btn is None:
                data["uiPermalinkFallbackError"] = "; ".join(errors + ["menu_button_not_found"])
                continue

            try:
                await menu_btn.click(timeout=3000)
                await self.page.wait_for_timeout(350)
            except Exception as e:
                data["uiPermalinkFallbackError"] = "; ".join(errors + [f"menu_click_failed:{e}"])
                continue

            try:
                menu_candidate = await self.page.evaluate(
                    """() => {
                        function abs(href) {
                            if (!href) return "";
                            if (href.startsWith("//")) return "https:" + href;
                            if (href.startsWith("http")) return href;
                            if (href.startsWith("/")) return "https://www.linkedin.com" + href;
                            return "";
                        }
                        function junk(u) {
                            if (!u) return true;
                            try {
                                var p = new URL(u).pathname.replace(/\\/+$/, "");
                                if (/^\\/company\\/[^\\/]+\\/posts$/.test(p)) return true;
                            } catch (e) {}
                            return false;
                        }
                        function addIf(list, url) {
                            if (!url || junk(url)) return;
                            if (url.includes("/feed/update/") && !url.endsWith("/")) url = url + "/";
                            if (!list.includes(url)) list.push(url);
                        }
                        const out = [];
                        const menuRoots = Array.from(document.querySelectorAll(
                            '[role="menu"], [data-test-artdeco-dropdown-content], .artdeco-dropdown__content--is-open, [data-floating-ui-portal] [role="menu"]'
                        ));
                        if (!menuRoots.length) return [];
                        for (const root of menuRoots) {
                            root.querySelectorAll("a[href]").forEach(function(a) {
                                const href = a.getAttribute("href") || "";
                                const decoded = (() => { try { return decodeURIComponent(href); } catch (_) { return href; } })();
                                if (href.includes("/feed/update/") || decoded.includes("/feed/update/")) {
                                    const pick = decoded.includes("/feed/update/") ? decoded : href;
                                    addIf(out, abs(pick.split("#")[0].split("?")[0]));
                                }
                                if (href.includes("/posts/")) addIf(out, abs(href.split("#")[0].split("?")[0]));
                                const m = decoded.match(/urn:li:activity:(\\d+)/) || href.match(/urn:li:activity:(\\d+)/);
                                if (m) addIf(out, "https://www.linkedin.com/feed/update/urn:li:activity:" + m[1] + "/");
                            });
                        }
                        return out.slice(0, 10);
                    }"""
                )
                if menu_candidate:
                    data["permalinkCandidates"] = list(
                        dict.fromkeys((data.get("permalinkCandidates", []) or []) + menu_candidate)
                    )
                    data["permalinkUrl"] = data.get("permalinkUrl") or menu_candidate[0]
                    data["uiPermalinkFallbackStatus"] = "resolved_via_ui_menu"
                else:
                    clip_url = await self._try_read_permalink_via_copy_link_menu()
                    if clip_url:
                        merged = (data.get("permalinkCandidates", []) or []) + [clip_url]
                        data["permalinkCandidates"] = list(dict.fromkeys(merged))
                        data["permalinkUrl"] = data.get("permalinkUrl") or clip_url
                        data["uiPermalinkFallbackStatus"] = "resolved_via_copy_link_clipboard"
                    else:
                        data["uiPermalinkFallbackError"] = "; ".join(
                            errors + ["menu_opened_but_no_permalink"]
                        )
            except Exception as e:
                data["uiPermalinkFallbackError"] = "; ".join(errors + [f"menu_extract_failed:{e}"])
            finally:
                try:
                    await self.page.keyboard.press("Escape")
                except Exception:
                    pass
        return posts_data

    @staticmethod
    def _looks_like_linkedin_post_url(url: str) -> bool:
        u = url.strip().lower()
        if "linkedin.com" not in u:
            return False
        if "/feed/update/" in u or "/posts/" in u:
            return True
        return False

    @staticmethod
    def _normalize_clipboard_post_url(url: str) -> str:
        u = url.strip().splitlines()[0].strip()
        if "/feed/update/" in u and not u.endswith("/"):
            u = f"{u}/"
        return u

    async def _try_read_permalink_via_copy_link_menu(self) -> Optional[str]:
        """Overflow déjà ouvert : clique « Copier le lien vers le post » et lit le presse-papiers."""
        try:
            for origin in ("https://www.linkedin.com", "https://linkedin.com"):
                try:
                    await self.page.context.grant_permissions(
                        ["clipboard-read", "clipboard-write"],
                        origin=origin,
                    )
                except Exception:
                    pass
        except Exception:
            pass

        try:
            items = (
                self.page.locator('[role="menu"]:visible')
                .last.locator('[role="menuitem"]')
                .filter(
                    has_text=re.compile(
                        r"Copier le lien vers le post|Copier le lien|Copy link to post",
                        re.I,
                    )
                )
            )
            if await items.count() == 0:
                items = self.page.locator('[role="menuitem"]').filter(
                    has_text=re.compile(
                        r"Copier le lien vers le post|Copier le lien|Copy link to post",
                        re.I,
                    )
                )
            if await items.count() == 0:
                return None
            await items.last.click(timeout=5000)
        except Exception as e:
            logger.debug("copy_link menuitem click failed: %s", e)
            return None

        await self.page.wait_for_timeout(450)

        try:
            text = await self.page.evaluate(
                """async () => {
                    try {
                        return await navigator.clipboard.readText();
                    } catch (e) {
                        return "";
                    }
                }"""
            )
        except Exception as e:
            logger.debug("clipboard readText failed: %s", e)
            return None

        if not text or not isinstance(text, str):
            return None

        url = text.strip().splitlines()[0].strip()
        if not FeedScraper._looks_like_linkedin_post_url(url):
            return None
        if FeedScraper._is_company_posts_feed_listing(url):
            return None
        return FeedScraper._normalize_clipboard_post_url(url)

    @staticmethod
    def _is_company_posts_feed_listing(url: str) -> bool:
        """True for /company/X/posts (fil d'entreprise), not a permalink de post."""
        try:
            path = urlparse(url).path.rstrip("/")
            return bool(re.match(r"^/company/[^/]+/posts$", path))
        except Exception:
            return False

    @staticmethod
    def _finalize_linkedin_url(
        permalink: Optional[str],
        urn: str,
        permalink_candidates: List[str],
    ) -> Optional[str]:
        """Prefer URL from DOM; else build from activity URN; normalize /feed/update/ trailing slash."""
        options = []
        raw = (permalink or "").strip()
        if raw and not FeedScraper._is_company_posts_feed_listing(raw):
            options.append(raw)
        for candidate in permalink_candidates:
            if (
                candidate
                and candidate not in options
                and not FeedScraper._is_company_posts_feed_listing(candidate)
            ):
                options.append(candidate)

        def score(candidate_url: str) -> int:
            s = 0
            if "/feed/update/" in candidate_url:
                s += 100
            if "/posts/" in candidate_url:
                s += 70
            if "urn:li:activity:" in candidate_url:
                s += 50
            if "/company/" in candidate_url and "/posts/" in candidate_url:
                s -= 80
            if urn.startswith("urn:li:activity:") and urn in candidate_url:
                s += 40
            return s

        url = None
        if options:
            url = sorted(options, key=score, reverse=True)[0]
        if not url and urn.startswith("urn:li:activity:"):
            url = f"https://www.linkedin.com/feed/update/{urn}/"
        if url and "/feed/update/" in url and not url.endswith("/"):
            url = f"{url}/"
        return url

    async def _resolve_url(self, url: str) -> str:
        """Follow redirects (e.g. lnkd.in shortlinks) and return the final destination URL."""
        try:
            response = await self.page.request.get(
                url,
                max_redirects=10,
                timeout=8000,
            )
            final_url = response.url
            await response.dispose()
            return final_url or url
        except Exception as e:
            logger.debug(f"Could not resolve URL {url}: {e}")
            return url

    def _clean_date(self, text: str) -> Optional[str]:
        if not text:
            return None
        return text.split("•")[0].strip() or None

    def _parse_count(self, text: str) -> Optional[int]:
        if not text:
            return None
        try:
            cleaned = re.sub(r"\s", "", text)
            cleaned = re.sub(r"[^\d.,k]", "", cleaned, flags=re.IGNORECASE)
            if "k" in cleaned.lower():
                return int(float(cleaned.lower().replace("k", "").replace(",", ".")) * 1000)
            numbers = re.findall(r"\d+", cleaned)
            if numbers:
                return int("".join(numbers))
        except Exception:
            pass
        return None

    async def _scroll_for_more_posts(self) -> None:
        try:
            # Move mouse to page center, then scroll with wheel (triggers LinkedIn's listeners)
            vp = self.page.viewport_size or {"width": 1280, "height": 720}
            cx = vp["width"] // 2
            cy = vp["height"] // 2
            await self.page.mouse.move(cx, cy)
            await self.page.mouse.wheel(0, 800)
            await self.page.wait_for_timeout(1000)
            await self.page.mouse.wheel(0, 800)
            await self.page.wait_for_timeout(1500)
        except Exception as e:
            logger.debug(f"Error scrolling feed: {e}")
