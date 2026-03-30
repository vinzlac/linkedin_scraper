# Intégration linkedin_scraper dans linkedin-mcp

Ce document est un guide d'implémentation destiné à Claude Code pour ajouter la lecture du feed LinkedIn dans le serveur MCP `linkedin-mcp`, en utilisant la librairie `linkedin_scraper`.

## Contexte

Le serveur `linkedin-mcp` utilise `FastMCP` et expose des outils MCP via `@mcp.tool()` dans `linkedin_mcp/server.py`. Il peut créer des posts via l'API officielle LinkedIn mais **ne peut pas lire le feed** (scope `r_member_social` bloqué par LinkedIn pour les apps standard).

`linkedin_scraper` est une librairie Playwright qui lit le feed par scraping navigateur. L'objectif est d'ajouter un tool `scrape_feed(count)` dans `server.py`.

---

## Étape 1 — Ajouter la dépendance

Depuis la racine du projet `linkedin-mcp` :

```bash
uv add --editable ../linkedin_scraper
```

Vérifie que `pyproject.toml` contient bien la référence :

```toml
dependencies = [
    ...
    "linkedin_scraper @ file:///.../linkedin_scraper",
]
```

---

## Étape 2 — Ajouter la configuration de session

La librairie `linkedin_scraper` nécessite un fichier de session Playwright (`linkedin_session.json`) créé par login manuel.

Dans `linkedin_mcp/config/settings.py`, ajouter le champ :

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # ... champs existants ...

    LINKEDIN_SESSION_PATH: str = "linkedin_session.json"
    """Chemin vers le fichier de session Playwright pour linkedin_scraper."""
```

Dans `.env` (ou variables d'environnement) :

```env
LINKEDIN_SESSION_PATH=/chemin/absolu/vers/linkedin_session.json
```

Le fichier `linkedin_session.json` se génère avec la commande suivante depuis le projet `linkedin_scraper` :

```bash
cd ../linkedin_scraper
just session   # ouvre un navigateur pour login manuel
```

---

## Étape 3 — Gérer le cycle de vie du navigateur

Le navigateur Playwright doit être initialisé **une seule fois** au démarrage du serveur MCP et resté ouvert entre les appels d'outils (le serveur est un processus persistant).

Pattern à utiliser : initialisation lazy au premier appel, instance partagée ensuite.

Dans `linkedin_mcp/server.py`, ajouter **après les imports existants** :

```python
from linkedin_scraper import BrowserManager, FeedScraper
```

Ajouter **après les initialisations existantes** (`auth_client`, `post_manager`, etc.) :

```python
# Browser Playwright pour le scraping (initialisé au premier appel)
_browser_manager: BrowserManager | None = None
_browser_initialized: bool = False


async def _get_browser() -> BrowserManager:
    """Retourne l'instance BrowserManager, en l'initialisant si nécessaire."""
    global _browser_manager, _browser_initialized

    if _browser_initialized and _browser_manager is not None:
        return _browser_manager

    session_path = settings.LINKEDIN_SESSION_PATH
    if not session_path or not Path(session_path).exists():
        raise RuntimeError(
            f"Fichier de session LinkedIn introuvable : {session_path}. "
            "Génère-le avec `just session` depuis le projet linkedin_scraper."
        )

    _browser_manager = BrowserManager(headless=False)
    await _browser_manager.__aenter__()
    await _browser_manager.load_session(session_path)
    _browser_initialized = True
    logger.info(f"Navigateur Playwright initialisé avec la session {session_path}")
    return _browser_manager
```

Ajouter aussi l'import `Path` si absent :

```python
from pathlib import Path
```

---

## Étape 4 — Ajouter le tool scrape_feed

Dans `linkedin_mcp/server.py`, ajouter après les tools existants (`get_posts`, `get_posts_legacy`) :

```python
@mcp.tool()
async def scrape_feed(count: int = 10, ctx: Context = None) -> str:
    """Lit les N premiers posts du feed LinkedIn de l'utilisateur connecté.

    Utilise un navigateur Playwright authentifié (scraping) car l'API officielle
    LinkedIn bloque la lecture du feed pour les applications standard.

    Args:
        count: Nombre de posts à récupérer (défaut 10)

    Returns:
        Liste JSON des posts avec : url, auteur, texte, date, réactions,
        commentaires, images, vidéo, lien externe.
    """
    logger.info(f"Scraping {count} posts du feed LinkedIn...")
    try:
        if ctx:
            await ctx.info(f"Démarrage du scraping du feed ({count} posts)...")

        browser = await _get_browser()
        scraper = FeedScraper(browser.page)
        posts = await scraper.scrape(limit=count)

        if not posts:
            return "Aucun post trouvé dans le feed."

        if ctx:
            await ctx.info(f"{len(posts)} posts récupérés.")

        return json.dumps(
            [p.model_dump() for p in posts],
            ensure_ascii=False,
            indent=2,
            default=str,
        )

    except Exception as e:
        error_msg = f"Erreur lors du scraping du feed : {str(e)}"
        logger.exception("Erreur scrape_feed")
        if ctx:
            await ctx.error(error_msg)
        raise RuntimeError(error_msg)
```

---

## Résultat dans server.py

Après modification, les imports en haut de `server.py` ressemblent à :

```python
import json
import logging
import webbrowser
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP, Context
from pydantic import FilePath

from .linkedin.auth import LinkedInOAuth, AuthError
from .linkedin.post import PostManager, PostRequest, PostCreationError, MediaRequest, PostVisibility
from .linkedin.reader import PostReader
from .linkedin.reader_legacy import PostReaderLegacy
from .callback_server import LinkedInCallbackServer
from .utils.logging import configure_logging
from .config.settings import settings
from linkedin_scraper import BrowserManager, FeedScraper
```

Et les outils MCP disponibles sont :

| Tool | Source | Capacité |
|------|--------|----------|
| `authenticate` | API officielle (OAuth2) | Login LinkedIn |
| `create_post` | API officielle | Créer un post |
| `get_posts` | API officielle | Lire ses posts publiés (scope restreint) |
| `get_posts_legacy` | API officielle legacy | Lire ses posts (fallback) |
| `scrape_feed` | linkedin_scraper (Playwright) | **Lire le feed** |

---

## Étape 5 — Mettre à jour la liste des dépendances FastMCP

Dans la déclaration `FastMCP(...)`, ajouter `linkedin_scraper` à la liste des dépendances :

```python
mcp = FastMCP(
    "LinkedInServer",
    dependencies=[
        "httpx",
        "mcp[cli]",
        "pydantic",
        "pydantic-settings",
        "python-dotenv",
        "linkedin_scraper",   # ← ajouter
    ]
)
```

---

## Étape 6 — Tester

```bash
# Depuis linkedin-mcp
uv run linkedin-mcp
```

Puis dans Claude Desktop ou Claude Code, appeler :

```
scrape_feed(count=5)
```

Résultat attendu — JSON de la forme :

```json
[
  {
    "linkedin_url": "https://www.linkedin.com/feed/update/urn:li:activity:123/",
    "urn": "urn:li:activity:123",
    "author_name": "Julien Dubois",
    "author_url": "https://www.linkedin.com/in/juliendubois/",
    "text": "Today I code AT GitHub!...",
    "posted_date": "3 j",
    "reactions_count": 97,
    "comments_count": 4,
    "reposts_count": null,
    "image_urls": ["https://media.licdn.com/..."],
    "video_url": null,
    "article_url": "https://github.com/louislva/claude-peers-mcp"
  }
]
```

---

## Notes importantes

### Headless et display

Sur **macOS/Windows desktop** : une fenêtre Chromium s'ouvre en arrière-plan au premier appel de `scrape_feed`. C'est normal et attendu (LinkedIn bloque les navigateurs headless).

Sur **Linux serveur sans GUI** : lancer le serveur MCP avec Xvfb :

```bash
xvfb-run --server-args="-screen 0 1280x720x24" uv run linkedin-mcp
```

Ou utiliser l'image Docker officielle Playwright.

### Session expirée

Si la session `linkedin_session.json` est expirée, `scrape_feed` lèvera une `RuntimeError`. Regénérer la session :

```bash
cd ../linkedin_scraper
just session
```

### Deux authentifications coexistent

| Mécanisme | Variables | Usage |
|-----------|-----------|-------|
| OAuth2 | `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET` | `create_post`, `authenticate` |
| Session Playwright | `LINKEDIN_SESSION_PATH` | `scrape_feed` |

Les deux sont indépendants et peuvent coexister dans le même `.env`.
