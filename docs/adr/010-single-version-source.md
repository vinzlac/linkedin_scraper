# ADR-010 : Source unique de vérité pour la version

## Status

Accepted

## Context

La version du package était définie à deux endroits :
1. `pyproject.toml` — `version = "3.1.1"`
2. `linkedin_scraper/__init__.py` — `__version__ = "3.1.1"`

Cette duplication crée un risque de désynchronisation lors des bumps de version (oublier de mettre à jour l'un des deux). C'est un bug classique dans les projets Python.

## Decision

Utiliser `pyproject.toml` comme **seule source de vérité** pour la version. `__init__.py` lit la version depuis les métadonnées du package installé via `importlib.metadata` (standard library Python 3.8+) :

```python
from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("linkedin_scraper")
except PackageNotFoundError:
    # Exécution directe depuis les sources (non installé)
    __version__ = "dev"
```

Pour bumper une version, il suffit de modifier `pyproject.toml` uniquement :
```toml
[project]
version = "4.1.0"
```

## Consequences

**Avantages :**
- Un seul endroit à modifier lors d'un bump de version
- Pas de risque de désynchronisation
- `PackageNotFoundError` géré proprement pour l'exécution depuis les sources

**Inconvénients :**
- `__version__` retourne `"dev"` quand le package n'est pas installé via `uv sync` (cas rare en développement car `uv sync` installe le package en mode editable automatiquement)
