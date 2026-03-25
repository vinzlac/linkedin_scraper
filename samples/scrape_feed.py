#!/usr/bin/env python3
import asyncio
from linkedin_scraper.scrapers.feed import FeedScraper
from linkedin_scraper.core.browser import BrowserManager


async def main():
    async with BrowserManager(headless=False) as browser:
        await browser.load_session("linkedin_session.json")
        print("Session loaded")

        scraper = FeedScraper(browser.page)

        print("Scraping feed...")
        posts = await scraper.scrape(limit=10)

        print(f"\nFound {len(posts)} posts\n")
        print("=" * 60)

        for i, post in enumerate(posts, 1):
            print(f"\nPost {i}:")
            print(f"  Author : {post.author_name}")
            print(f"  URL    : {post.linkedin_url}")
            print(f"  Posted : {post.posted_date}")
            print(f"  React  : {post.reactions_count}")
            print(f"  Comments: {post.comments_count}")
            if post.text:
                preview = post.text[:200] + "..." if len(post.text) > 200 else post.text
                print(f"  Text   : {preview}")
            print("-" * 40)

        print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
