# ADR-018 : Publication PyPI sous `linkedin-playwright-scraper`

## Status

Accepted — supersede [ADR-015](015-local-editable-install.md)

## Context

ADR-015 avait reporté la publication PyPI de `linkedin_scraper` au profit d'une installation `editable` locale (`uv add --editable ../linkedin_scraper`), avec une clause de sortie explicite : revisiter PyPI « quand `linkedin-mcp` est déployé sur un serveur distant sans accès au dossier source ».

Cette condition s'est concrétisée : `linkedin-mcp` est désormais déployé comme pod k3s (voir `linkedin-mcp/docs/plan/deploy-k3s-argocd.md`), construit via une image Docker buildée sur BuildKit distant (in-cluster). Le build Docker n'a pas accès à `../linkedin_scraper` (hors contexte de build) — deux options ont été considérées :

1. **Vendoring** — copier une copie de `linkedin_scraper` dans `linkedin-mcp/vendor/` au moment du build (script de sync manuel ou submodule git).
2. **Publication PyPI** — dépendance standard, résolue par `uv`/`pip` sans mécanisme ad hoc.

## Decision

Publier `linkedin_scraper` sur PyPI public, sous le nom de distribution **`linkedin-playwright-scraper`** (le nom `linkedin-scraper` était déjà pris par un projet Selenium non lié, de Joey Sham). Le nom du module Python reste inchangé (`import linkedin_scraper`) — seul le nom du paquet PyPI change. Le nom du dépôt GitHub (`vinzlac/linkedin_scraper`) reste également inchangé ; nom de repo et nom de distribution PyPI n'ont pas besoin de correspondre.

Publication automatisée via `.github/workflows/publish.yml` : build avec `uv build`, publication via `pypa/gh-action-pypi-publish` sur push d'un tag `v*`, authentification par **OIDC trusted publishing** (pas de token PyPI stocké en secret).

Versioning manuel, sans semantic-release : bump `version` dans `pyproject.toml`, `git tag vX.Y.Z && git push --tags` déclenche la publication. Choix délibérément simple — projet mono-développeur avec un seul consommateur connu (`linkedin-mcp`), l'outillage de release automatisé serait disproportionné.

`linkedin-mcp` référence désormais `linkedin-playwright-scraper>=4.0.0` comme dépendance PyPI standard dans son `pyproject.toml`, sans override `tool.uv.sources` — le mode dev-local en `editable` (ADR-015) est abandonné au profit d'un mode unique (PyPI partout), plus simple à maintenir qu'une coexistence dev/CI.

## Consequences

**Avantages :**
- Le build Docker de `linkedin-mcp` résout `linkedin_scraper` comme n'importe quelle dépendance PyPI, sans mécanisme de sync ni chemin relatif hors contexte.
- OIDC trusted publishing : aucun token PyPI longue durée à gérer/roter.
- Repo GitHub déjà public, donc aucune préoccupation de confidentialité à publier le code sur un registre public.

**Inconvénients :**
- Perte du cycle de dev immédiat d'ADR-015 (modifier `linkedin_scraper` → visible instantanément dans `linkedin-mcp`). Une modification locale à `linkedin_scraper` ne se propage plus à `linkedin-mcp` tant qu'une nouvelle version n'est pas publiée sur PyPI (`git tag vX.Y.Z && git push --tags`) et que `uv lock` n'est pas relancé côté `linkedin-mcp`.
- Un oubli de bump de version bloque la prise en compte d'un changement par `linkedin-mcp` sans erreur explicite (juste l'ancienne version qui continue d'être résolue).

**Alternative écartée :** le vendoring aurait évité la publication publique mais aurait introduit un mécanisme de sync supplémentaire (script ou submodule git) à maintenir, pour un gain de confidentialité nul (le repo est déjà public).
