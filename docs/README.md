# Documentation

## Structure

```
docs/
  README.md          ← ce fichier
  adr/               ← Architecture Decision Records
    README.md        ← index des ADRs
    001-...md
    ...
```

## ADRs

Les [Architecture Decision Records](adr/README.md) documentent toutes les décisions techniques significatives du projet : pourquoi Playwright plutôt que l'API officielle, pourquoi headless=False, comment fonctionne la gestion de session, etc.

→ [Voir tous les ADRs](adr/README.md)

## Setup développement local

Le guide [local-dev-setup.md](local-dev-setup.md) explique comment travailler sur `linkedin_scraper` et `linkedin-mcp` en parallèle sur la même machine, sans passer par PyPI.

→ [Guide de setup local](local-dev-setup.md)

## Intégration dans linkedin-mcp

Le guide [integration-linkedin-mcp.md](integration-linkedin-mcp.md) est un guide d'implémentation pas-à-pas destiné à Claude Code pour ajouter le tool `scrape_feed` dans le serveur MCP `linkedin-mcp`.

→ [Guide d'intégration linkedin-mcp](integration-linkedin-mcp.md)

## Ressources

- [README principal](../README.md) — installation, quick start, API
- [CLAUDE.md](../CLAUDE.md) — guide pour Claude Code (architecture, conventions, commandes)
- [FORK_CONTEXT.md](../FORK_CONTEXT.md) — contexte et motivation du fork depuis joeyism/linkedin_scraper
- [CONTRIBUTING.md](../CONTRIBUTING.md) — guide de contribution
- [TESTING.md](../TESTING.md) — guide des tests
