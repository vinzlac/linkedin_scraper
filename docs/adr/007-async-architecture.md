# ADR-007 : Architecture full async/await

## Status

Accepted

## Context

Le scraping LinkedIn implique de nombreuses opérations I/O : navigation de pages, attente de chargement DOM, scroll, requêtes réseau. Deux paradigmes possibles :

1. **Synchrone** — Simple, utilisé par le repo original (joeyism) avec Selenium
2. **Async/await** — Non-bloquant, permet la concurrence sans threads, natif dans Playwright async

La migration vers Playwright (v3.0.0) a introduit le choix entre `playwright.sync_api` et `playwright.async_api`. Le scraping web implique typiquement des délais d'attente significatifs (chargement page, scroll, lazy-loading) — un bon cas d'usage pour l'async.

## Decision

Utiliser exclusivement **`playwright.async_api`** et `asyncio` pour toute l'architecture.

```python
async with BrowserManager(headless=False) as browser:
    await browser.load_session("linkedin_session.json")
    scraper = FeedScraper(browser.page)
    posts = await scraper.scrape(limit=20)
```

## Consequences

**Avantages :**
- Naturel pour l'intégration MCP (le SDK `mcp` Python est async)
- Permet de scraper plusieurs scrapers en parallèle (`asyncio.gather`)
- Meilleure utilisation des temps d'attente (scroll delays, page loads)
- Playwright async est l'API recommandée par Microsoft

**Inconvénients :**
- `asyncio.run()` obligatoire pour les scripts standalone
- Courbe d'apprentissage pour les développeurs non familiers avec l'async Python
- Quelques subtilités (ex: `pytest-asyncio` requis pour les tests)
