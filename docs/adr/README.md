# Architecture Decision Records

Ce répertoire contient les ADRs (Architecture Decision Records) du projet `linkedin_scraper`.

Un ADR documente une décision architecturale significative : le contexte qui l'a motivée, la décision prise, et ses conséquences.

## Format

Chaque ADR suit le format :
- **Status** : Proposed / Accepted / Deprecated / Superseded
- **Context** : Pourquoi cette décision était nécessaire
- **Decision** : Ce qui a été décidé
- **Consequences** : Trade-offs, avantages, inconvénients

## Index

| # | Titre | Status |
|---|-------|--------|
| [001](001-playwright-over-official-api.md) | Playwright plutôt que l'API officielle LinkedIn | Accepted |
| [002](002-headless-false-required.md) | headless=False obligatoire contre la détection anti-bot | Accepted |
| [003](003-js-evaluation-over-locators.md) | page.evaluate() plutôt que les locators Playwright | Accepted |
| [004](004-data-urn-stable-anchor.md) | data-urn comme ancre stable pour l'identification des posts | Accepted |
| [005](005-playwright-storage-state.md) | Playwright storage state pour la gestion de session | Accepted |
| [006](006-pydantic-models.md) | Pydantic pour les modèles de données | Accepted |
| [007](007-async-architecture.md) | Architecture full async/await | Accepted |
| [008](008-uv-just-toolchain.md) | Migration toolchain vers uv + just | Accepted |
| [009](009-library-samples-separation.md) | Séparation lib / samples pour double usage | Accepted |
| [010](010-single-version-source.md) | Source unique de vérité pour la version | Accepted |
| [011](011-xvfb-linux-deployment.md) | Xvfb pour le déploiement Linux sans interface graphique | Accepted |
| [012](012-lnkd-url-resolution.md) | Résolution des URLs courtes lnkd.in via page.request | Accepted |
| [013](013-mcp-integration-architecture.md) | Architecture d'intégration MCP avec linkedin-mcp | Accepted |
| [014](014-cdp-existing-browser.md) | Connexion CDP à un navigateur existant | Accepted |
| [015](015-local-editable-install.md) | Installation editable locale plutôt que publication PyPI | Accepted |
