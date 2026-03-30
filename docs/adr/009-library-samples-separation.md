# ADR-009 : Séparation lib / samples pour double usage

## Status

Accepted

## Context

Le projet sert deux usages distincts :

1. **Librairie Python** — importée par d'autres projets (notamment `linkedin-mcp`) via PyPI ou référence git
2. **Application de développement** — scripts exécutables localement pour tester et déboguer le scraper

Ces deux usages ont des besoins différents :
- La librairie doit être propre, sans dépendances vers des scripts d'exécution
- Les scripts de dev/test doivent rester simples et exécutables directement

Sans séparation, les scripts de dev se retrouveraient dans la wheel PyPI (inutile pour les consommateurs) ou la librairie contiendrait des dépendances de dev (problématique).

## Decision

Séparer en deux couches distinctes :

```
linkedin_scraper/     ← librairie (incluse dans la wheel PyPI)
  __init__.py         ← API publique exportée
  core/
  scrapers/
  models/
  callbacks.py

samples/              ← scripts de dev/test (exclus de la distribution)
  scrape_feed.py      ← appelé par `just run-feed`
  scrape_person.py    ← appelé par `just run-person`
  create_session.py   ← appelé par `just session`
  ...

Justfile              ← orchestre les scripts samples/ (dev local uniquement)
tests/                ← tests (dev uniquement)
```

La configuration hatchling dans `pyproject.toml` garantit que seul `linkedin_scraper/` est distribué :

```toml
[tool.hatch.build.targets.wheel]
packages = ["linkedin_scraper"]
```

## Consequences

**Avantages :**
- Distribution PyPI propre (wheel contient uniquement la lib)
- `just run-feed` continue de fonctionner en développement
- Séparation claire des responsabilités
- Les consommateurs de la lib n'ont pas de scripts parasites dans leurs dépendances

**Inconvénients :**
- Les `samples/` ne sont pas disponibles après installation via PyPI (voulu)
- Nécessite de cloner le repo pour accéder aux scripts de dev
