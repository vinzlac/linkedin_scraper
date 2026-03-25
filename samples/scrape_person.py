#!/usr/bin/env python3
"""
Example: Scrape a single LinkedIn profile

This example shows how to use the PersonScraper to scrape a LinkedIn profile.
"""
import asyncio
import sys
from linkedin_scraper.scrapers.person import PersonScraper
from linkedin_scraper.core.browser import BrowserManager


def _parse_url(arg: str) -> str:
    """Accept either a full URL or just the profile slug (e.g. 'williamhgates')."""
    if arg.startswith("http"):
        return arg.rstrip("/") + "/"
    return f"https://www.linkedin.com/in/{arg.strip('/')}/"


async def main():
    """Scrape a single person profile"""
    if len(sys.argv) < 2:
        print("Usage: uv run python samples/scrape_person.py <url-or-slug>")
        print("  e.g: uv run python samples/scrape_person.py williamhgates")
        print("  e.g: uv run python samples/scrape_person.py https://www.linkedin.com/in/williamhgates/")
        sys.exit(1)

    profile_url = _parse_url(sys.argv[1])

    # Initialize and start browser using context manager
    async with BrowserManager(headless=False) as browser:
        # Load existing session (must be created first - see README for setup)
        await browser.load_session("linkedin_session.json")
        print("✓ Session loaded")
        
        # Initialize scraper with the browser page
        scraper = PersonScraper(browser.page)
        
        # Scrape the profile
        print(f"🚀 Scraping: {profile_url}")
        person = await scraper.scrape(profile_url)
        
        # Display results
        print("\n" + "="*60)
        print(f"Name: {person.name}")
        print(f"Location: {person.location}")
        print(f"About: {person.about[:100]}..." if person.about else "About: N/A")
        print(f"Experiences: {len(person.experiences)}")
        print(f"Education: {len(person.educations)}")
        print("="*60)
    
    print("\n✓ Done!")


if __name__ == "__main__":
    asyncio.run(main())
