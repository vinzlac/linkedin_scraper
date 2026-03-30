# ADR-008 : Migration toolchain vers uv + just

## Status

Accepted

## Context

Le repo original utilisait `pip` + `Makefile` (ou pas de task runner). Plusieurs alternatives ont été évaluées pour moderniser le toolchain :

**Gestionnaire de packages :**
- `pip` + `requirements.txt` — standard mais lent, pas de lockfile natif
- `poetry` — populaire mais lourd, résolution lente
- `uv` — écrit en Rust, 10-100x plus rapide que pip, gère virtualenv + lockfile, compatible `pyproject.toml`

**Task runner :**
- `Makefile` — universel mais syntaxe archaïque, pas de documentation intégrée
- `just` — syntaxe moderne, `just --list` documente automatiquement les recettes, multiplateforme

## Decision

Migrer vers **uv** comme gestionnaire de packages/virtualenv et **just** comme task runner.

```toml
# pyproject.toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

```just
# Justfile
run-feed N="10":
    uv run python samples/scrape_feed.py {{ N }}
```

## Consequences

**Avantages :**
- `uv sync` installe toutes les dépendances en ~1s (vs ~30s avec pip)
- `uv run` exécute dans le virtualenv sans activation manuelle
- `just --list` donne une documentation gratuite des commandes
- `uv.lock` garantit la reproductibilité exacte des dépendances
- `uv build` + `uv publish` remplacent `build` + `twine` pour la publication PyPI

**Inconvénients :**
- `just` est moins universel que `make` (installation requise)
- `uv` est relativement récent (2023) — moins mature que poetry pour certains cas edge
