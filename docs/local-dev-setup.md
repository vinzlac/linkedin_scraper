# Développement local — linkedin_scraper + linkedin-mcp

Ce guide décrit comment travailler sur les deux projets en parallèle sur la même machine, sans passer par PyPI ni GitHub.

## Prérequis

- [uv](https://docs.astral.sh/uv/) installé
- [just](https://just.systems/) installé
- Les deux repos clonés côte à côte :

```
workspace/
  linkedin_scraper/    ← ce projet (la lib)
  linkedin-mcp/        ← le consommateur MCP
```

```bash
cd workspace
git clone https://github.com/vinzlac/linkedin_scraper
git clone https://github.com/vinzlac/linkedin-mcp
```

## Installer linkedin_scraper en mode editable dans linkedin-mcp

```bash
cd linkedin-mcp
uv add --editable ../linkedin_scraper
```

`uv` ajoute automatiquement la référence dans `pyproject.toml` de `linkedin-mcp` :

```toml
dependencies = [
    "linkedin_scraper @ file:///chemin/absolu/vers/linkedin_scraper",
    ...
]
```

En mode editable, toute modification dans `linkedin_scraper/` est **immédiatement visible** dans `linkedin-mcp` sans réinstaller.

## Vérifier l'installation

```bash
cd linkedin-mcp
uv run python -c "import linkedin_scraper; print(linkedin_scraper.__version__)"
# → dev  (ou la version si le package est installé)
```

## Workflow quotidien

```
linkedin_scraper/              linkedin-mcp/
─────────────────              ─────────────
just run-feed 5                ← tester la lib seule
just test                      ← tests unitaires lib

# Modifier feed.py...
# → linkedin-mcp voit le changement instantanément

                               uv run linkedin-mcp  ← tester l'intégration MCP
```

## Tester la lib seule (sans linkedin-mcp)

Depuis `linkedin_scraper/` :

```bash
just install          # installe les dépendances + Playwright
just session          # crée linkedin_session.json (login manuel)
just run-feed 10      # scrape 10 posts du feed
just run-person <slug> # scrape un profil
just test             # lance les tests unitaires
just check            # lint + types + tests
```

## Passer à PyPI plus tard

Quand la lib est prête à être distribuée :

```bash
cd linkedin_scraper

# 1. Bumper la version dans pyproject.toml
#    version = "4.0.0"  →  version = "4.1.0"

# 2. Builder
just build
# → crée dist/linkedin_scraper-4.1.0.tar.gz
# → crée dist/linkedin_scraper-4.1.0-py3-none-any.whl

# 3. Publier (nécessite un compte PyPI et un token)
just publish
```

Dans `linkedin-mcp`, remplacer la référence locale par la version PyPI :

```toml
# Avant (dev local)
"linkedin_scraper @ file:///..."

# Après (PyPI)
"linkedin_scraper>=4.1.0"
```

## Architecture de la session LinkedIn

La session est créée une fois dans `linkedin_scraper/` et peut être partagée avec `linkedin-mcp` via une variable d'environnement :

```bash
# .env dans linkedin-mcp
LINKEDIN_SESSION_PATH=/chemin/vers/linkedin_scraper/linkedin_session.json
```

Ou en copiant le fichier :

```bash
cp linkedin_scraper/linkedin_session.json linkedin-mcp/
```
