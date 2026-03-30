# ADR-013 : Architecture d'intégration MCP avec linkedin-mcp

## Status

Accepted

## Context

Le projet `linkedin-mcp` (https://github.com/vinzlac/linkedin-mcp) expose des outils MCP pour interagir avec LinkedIn via l'API officielle. Il peut créer des posts mais **ne peut pas lire** (scope `r_member_social` bloqué — ADR-001).

`linkedin_scraper` peut lire le feed, les profils, les posts d'entreprise, mais **ne peut pas écrire** (scraping uniquement).

Les deux projets sont complémentaires. L'objectif est d'intégrer `linkedin_scraper` comme librairie dans `linkedin-mcp` pour ajouter les capacités de lecture.

## Decision

Transformer `linkedin_scraper` en **librairie Python publiée sur PyPI** (ou référençable via git), importable par `linkedin-mcp` :

```toml
# pyproject.toml de linkedin-mcp
dependencies = [
    "linkedin_scraper>=4.0.0",
    # ou pendant le dev :
    # "linkedin_scraper @ git+https://github.com/vinzlac/linkedin_scraper.git@main"
]
```

**Architecture du serveur MCP résultant :**

```
Claude Desktop / Claude Code
        │ MCP protocol (stdio)
        ▼
linkedin-mcp (serveur MCP)
  ├── create_post()          ← API officielle LinkedIn (OAuth2)
  ├── authenticate()         ← OAuth2 flow
  ├── scrape_feed()          ← linkedin_scraper lib (Playwright)
  ├── scrape_person()        ← linkedin_scraper lib (Playwright)
  └── scrape_company_posts() ← linkedin_scraper lib (Playwright)
        │
        ▼
BrowserManager (Playwright, persistent)
        │
        ▼
LinkedIn (navigateur authentifié)
```

**Deux mécanismes d'auth coexistent :**
- OAuth2 (`LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`) pour l'écriture via API
- Session Playwright (`linkedin_session.json`) pour la lecture via scraping

## Consequences

**Avantages :**
- Séparation des responsabilités : chaque projet fait ce qu'il sait faire
- `linkedin-mcp` devient un serveur MCP complet (lecture + écriture)
- `linkedin_scraper` reste une librairie générique réutilisable

**Inconvénients :**
- Double mécanisme d'authentification à gérer (OAuth2 + session Playwright)
- Le navigateur Playwright dans un serveur MCP est un processus lourd persistant
- La session Playwright doit être accessible sur la machine qui héberge le serveur MCP
