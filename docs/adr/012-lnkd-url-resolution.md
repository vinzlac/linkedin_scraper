# ADR-012 : Résolution des URLs courtes lnkd.in via page.request

## Status

Accepted

## Context

Les posts LinkedIn contiennent souvent des liens externes raccourcis via le service de tracking LinkedIn (`lnkd.in`). Par exemple :
- `https://lnkd.in/eCT_4TGS` → `https://github.com/louislva/claude-peers-mcp`

Ces URLs sont des redirects HTTP (301/302). Sans résolution, le champ `article_url` du modèle `Post` contient l'URL courte LinkedIn, inutilisable pour comprendre la destination sans suivre le redirect.

Plusieurs approches de résolution ont été évaluées :

1. **`requests.get()` / `httpx`** — Requête HTTP synchrone ou async, simple mais ajoute une dépendance ou nécessite une session
2. **`page.evaluate()` avec `fetch()`** — Impossible (CORS bloque les requêtes cross-origin depuis le contexte page)
3. **`page.request.get()`** — API Playwright pour faire des requêtes HTTP dans le contexte du navigateur (avec les cookies de session), suit les redirects automatiquement

## Decision

Utiliser **`page.request.get()`** de Playwright pour résoudre les URLs courtes. Cette API réutilise le contexte de session existant (cookies LinkedIn inclus) et suit les redirects jusqu'à l'URL finale.

```python
async def _resolve_url(self, url: str) -> str:
    try:
        response = await self.page.request.get(url, max_redirects=10, timeout=8000)
        final_url = response.url
        await response.dispose()
        return final_url or url
    except Exception as e:
        logger.debug(f"Could not resolve URL {url}: {e}")
        return url  # Retourne l'URL brute en cas d'échec
```

## Consequences

**Avantages :**
- Réutilise le contexte Playwright existant (pas de dépendance HTTP supplémentaire)
- Gère les redirects chaînés (max 10)
- Timeout court (8s) pour ne pas bloquer le scraping
- Fallback gracieux : retourne l'URL brute si la résolution échoue

**Inconvénients :**
- Ajoute une requête réseau par post contenant un lien externe (latence)
- Ne résout que le premier lien externe trouvé dans le post
- `lnkd.in` peut parfois rediriger vers une page d'interstitiel LinkedIn pour les liens non-LinkedIn
