# ADR-016 : Stratégie multi-couches contre la détection et le rate limit LinkedIn

## Status

Accepted

## Context

Le 2026-07-22, une session de debug (voir [post-mortem associé](../post-mortem/2026-07-22-rate-limit-hang.md)) a déclenché un rate limit LinkedIn (`RateLimitError`, message « Too many requests / slow down ») après une succession rapprochée de scrapes de feed, likes et reposts.

Deux causes distinctes ont été identifiées :

1. **`headless=True` utilisé en pratique alors qu'ADR-002 impose `headless=False`.** Le service `linkedin-mcp` avait `LINKEDIN_HEADLESS: bool = True` par défaut, ce qui contredit directement la décision d'ADR-002 (fingerprint anti-bot classique : `navigator.webdriver`, UA `HeadlessChrome`, canvas/WebGL dégradés).
2. **Volume et rythme d'interactions DOM excessifs.** `_fill_missing_permalinks_from_ui` (feed.py) rouvre le menu « ⋯ » de **toutes les cartes visibles** à chaque scrape, y compris celles déjà résolues lors d'un run précédent — sans aucun cache. Combiné à des relances rapprochées du même scrape pendant le debug (et à un correctif retry qui triplait les tentatives de clic par carte), cela a produit des dizaines de clics automatisés concentrés sur quelques minutes.

Un troisième facteur aggravant, non corrigé ici mais documenté : aucune action n'était prise sur le `suggested_wait_time` déjà renvoyé par `RateLimitError` — rien n'empêchait de relancer immédiatement après une détection.

## Decision

Adopter une défense en profondeur, classée par impact attendu (le detail de chaque analyse est dans le post-mortem) :

1. **`headless=False` par défaut partout** (déjà la règle d'ADR-002 ; corrigé dans `linkedin-mcp` où la valeur avait divergé). Le point le plus impactant : ne pas dépendre de la mémoire humaine pour respecter cette règle.

2. **Cache de permalien persistant** (`core/permalink_cache.py`) : `urn -> permalinkUrl` sur disque (`~/.cache/linkedin_scraper/permalink_cache.json`). Un post déjà résolu une fois n'est plus jamais re-cliqué lors des scrapes suivants, même dans un nouveau process.

3. **Plafond dur sur le fallback UI par appel** (`_MAX_UI_FALLBACK_PER_CALL = 4` dans `feed.py`) : même avec un cache froid, un seul appel ne peut pas ouvrir plus de N menus overflow. Les cartes au-delà du plafond restent non résolues pour cet appel (dégradation propre, pas d'échec) et se résolvent progressivement au fil des runs suivants une fois le cache chaud.

4. **Cooldown persistant inter-process** (`core/rate_limit_guard.py`) : quand `detect_rate_limit` lève `RateLimitError`, le `suggested_wait_time` est maintenant persisté sur disque (`~/.cache/linkedin_scraper/cooldown.json`). `BaseScraper.navigate_and_wait` (et `LikeUI.like` / `RepostUI.repost` côté `linkedin-mcp`) vérifient ce cooldown **avant** de démarrer une navigation, y compris dans un nouveau process — impossible de contourner le cooldown juste en relançant le script.

5. **Espacement aléatoire entre actions d'écriture** (`enforce_write_action_pacing`) : like et repost partagent une clé de pacing commune (`write_action`) avec un délai minimum + jitter aléatoire (20s + jusqu'à 15s), persisté sur disque. Deux actions d'écriture rapprochées (ex. like puis repost du même post en quelques secondes) sont désormais espacées automatiquement.

## Consequences

**Avantages :**
- Chaque mécanisme est indépendant et fail-safe : une erreur dans le cache ou le cooldown ne bloque jamais le scraping (best-effort, dégradation propre).
- Le cooldown et le cache survivent aux redémarrages de process — un utilisateur qui relance le script après un rate limit ne peut pas accidentellement le contourner.
- Le coût du fallback UI décroît avec le temps (cache qui se remplit), au lieu de rester constant à chaque run.

**Inconvénients :**
- Fichiers de cache/cooldown partagés dans `~/.cache/linkedin_scraper/` : pas de séparation multi-compte si plusieurs sessions LinkedIn différentes tournent sur la même machine (non géré pour l'instant — un seul compte par machine est l'usage actuel).
- Le plafond de 4 cartes/appel peut laisser des permaliens non résolus sur un premier scrape à froid d'un feed jamais vu (`linkedin_url: None`) ; les runs suivants les résolvent progressivement.
- Le pacing des actions d'écriture ajoute jusqu'à ~35s de latence perçue entre deux appels `like_post`/`repost_post` rapprochés — attendu et voulu, mais à documenter côté MCP pour ne pas surprendre l'appelant.

**Non traité par cet ADR (hors scope, moins prioritaire d'après le post-mortem) :**
- Jitter sur les montants/vitesses de scroll (actuellement des paliers fixes).
- Quota horaire/journalier configurable par compte.
- Patchs anti-fingerprint CDP supplémentaires (jugés non prioritaires : le rate limit du 2026-07-22 est un signal comportemental, pas un signal de fingerprint, puisque la session était déjà authentifiée avec cookies valides).
