# Post-mortem : feed vide — boutons Republier en icônes (aria-label)

**Date** : 2026-06-25  
**Statut** : Résolu  
**Impact** : `scrape_feed` / `FeedScraper.scrape()` retournaient `[]` — MCP Claude Desktop inutilisable pour le fil  
**Commit correctif** : (voir `git log` sur `master` après merge)

---

## Symptôme

- `uv run python test_scrape_feeds.py 5` → `⚠️ Aucun post trouvé dans le feed`
- Log : `Feed posts not loaded after 40s. url=https://www.linkedin.com/feed/ title=Fil d'actualité | LinkedIn`
- Boutons visibles dans le diagnostic : `Accueil`, `Vous`, `Nouveaux posts` — **pas** de `Republier` dans `innerText`
- MCP `scrape_feed` dans Claude Desktop : même échec silencieux (liste vide)

## Cause racine

LinkedIn a déployé une UI où l’action **Republier / Repost** est rendue comme **bouton icône** :

- `button.innerText` → vide ou compteur (`715`, `68`, …)
- `button.getAttribute('aria-label')` → `"Republier"` (FR)

Le scraper s’appuyait exclusivement sur :

```javascript
(b.innerText || "").trim() === "Republier" || ... === "Repost"
```

pour (1) attendre le chargement du feed (`_WAIT_FOR_FEED_JS`) et (2) ancrer chaque carte post (`repostBtns` dans `_extract_posts_from_feed`).

Résultat : timeout 40s → retour anticipé `[]` sans exception.

## Diagnostic

Script ad hoc (session Playwright valide, page feed chargée) :

| Signal | Avant correctif |
|--------|-----------------|
| `aria-label` contenant `Republier` | 7 boutons |
| `innerText === "Republier"` | 0 |
| `feed-shared-actor` / `data-urn` | 0 (layout différent, non bloquant une fois les boutons trouvés) |

La session n’était **pas** expirée (titre `Fil d'actualité`, profil visible).

## Correctif

Fichier : `linkedin_scraper/scrapers/feed.py`

1. **`_WAIT_FOR_FEED_JS`** : accepter `aria-label` matching `/^Republier\b/i` ou `/^Repost\b/i`
2. **`_extract_posts_from_feed`** : helper JS `isRepostButton(b)` (texte **ou** aria-label), utilisé pour `repostBtns` et le comptage parent

## Validation

```bash
cd ~/workspace/linkedin-mcp
uv run python test_scrape_feeds.py 5 --dir output
# → 5 posts, ex. output/20260625-145621/feed.json
```

## Prévention

- Ne jamais ancrer le feed uniquement sur `innerText` des boutons d’action LinkedIn
- En cas de feed vide : logger les 10 premiers `aria-label` des boutons + vérifier session
- Test d’intégration `scrape(limit=5)` à lancer après toute mise à jour majeure de Playwright ou changement DOM signalé

## Liens

- Consommateur MCP : [linkedin-mcp](https://github.com/vinzlac/linkedin-mcp) — tool `scrape_feed`
- ADR connexe : [003-js-evaluation-over-locators](../adr/003-js-evaluation-over-locators.md)
