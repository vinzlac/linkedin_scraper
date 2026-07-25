# Post-mortem : hang like/repost, mauvaise URL de post, puis rate limit LinkedIn

**Date** : 2026-07-22
**Statut** : Résolu
**Impact** : `like_post`/`repost_post` (MCP `linkedin-mcp`) restaient bloqués indéfiniment ; puis, une fois corrigés, les deux échouaient silencieusement sur une URL reconstruite invalide ; le debug intensif a ensuite déclenché un rate limit LinkedIn
**Repos concernés** : `linkedin_scraper` (ce repo) et `linkedin-mcp`

---

## Chronologie

### 1. Hang perçu sur `like_post` après ajout d'un `scrape_post` préalable

**Symptôme** : un `scrape_post` inséré avant `like_post` (pour naviguer sur la page individuelle du post avant de liker) faisait paraître `like_post` bloqué indéfiniment plutôt que d'échouer proprement.

**Cause réelle** : `LikeUI`/`RepostUI` (côté `linkedin-mcp`) retombaient, quand le bouton n'était pas trouvé sur la page post, sur un fallback « carte feed » qui re-naviguait vers `/feed/`, scrollait 5 fois et attendait jusqu'à 40s à chaque étape — jusqu'à ~2 minutes cumulées. Ce délai dépassait le timeout du client MCP, qui abandonnait pendant que l'appel continuait de tourner côté serveur : perçu comme un hang, alors que c'était une latence non bornée.

**Correctif (`linkedin-mcp`)** :
- Suppression du fallback « carte feed » automatique quand une `activity_id` est disponible (le fallback n'aide de toute façon presque jamais dans ce cas — c'est un problème de sélecteur, pas de position dans le feed).
- 3 tentatives bornées directement sur la page post au lieu d'un aller-retour complet vers le feed.
- Skip de la navigation si la page est déjà sur l'URL cible (évite un `goto` redondant après un `scrape_post` précédent).
- `asyncio.wait_for(..., timeout=100s)` autour de `like_post`/`repost_post` côté serveur MCP : plus jamais de blocage réellement indéfini, même en cas de régression future.

### 2. Une fois le hang réglé : échec « bouton introuvable » — mauvaise reconstruction d'URL

**Symptôme** : `like_post`/`repost_post` échouaient avec « bouton introuvable », alors que le post scrapé existait bien.

**Cause racine** : `_post_url()`/`normalize_post_url()` reconstruisaient systématiquement une URL `https://www.linkedin.com/feed/update/urn:li:activity:{id}/` à partir de l'ID numérique extrait d'un permalien `/posts/{slug}-share-{id}-{suffix}/`. Or cet ID est un ID de **share/ugcPost**, pas garanti être un `urn:li:activity:` valide. Résultat : la page reconstruite affichait « Post introuvable — Ce post a été supprimé ou retiré », alors que le permalien **original** chargeait le post correctement (vérifié en navigant directement dessus : boutons « État du bouton de réaction » et « Republier » bien présents).

**Correctif (`linkedin-mcp`)** : `canonical_post_url()` (dans `repost.py`) navigue désormais vers l'URL **originale** telle que scrapée quand c'est déjà un permalien complet (`/posts/...` ou `/feed/update/...`), et ne reconstruit une URL `feed/update/urn:li:activity:` que si on ne dispose que d'un URN nu ou d'un ID numérique isolé.

### 3. Bug secondaire découvert en testant le repost réel : libellé de menu changé

**Symptôme** : le clic sur « Republier » fonctionnait, mais l'option de repost instantané restait introuvable.

**Cause** : LinkedIn a renommé l'option **« Republier instantanément »** (le code attendait « Diffusez instantanément » / « Instantly repost »).

**Correctif (`linkedin-mcp`)** : matching sur le mot-clé `instantan`/`instantly` plutôt qu'une phrase exacte, plus robuste aux changements de wording futurs.

### 4. Rate limit LinkedIn déclenché pendant le debug intensif

**Symptôme** : `RateLimitError: Rate limit message detected on page.` après une série de tests répétés en quelques dizaines de minutes.

**Causes identifiées** (voir [ADR-016](../adr/016-rate-limit-avoidance.md) pour la décision complète) :

1. **`headless=True` en pratique côté `linkedin-mcp`**, alors qu'[ADR-002](../adr/002-headless-false-required.md) impose `headless=False` pour ce projet précisément à cause de la détection anti-bot LinkedIn. Le paramètre par défaut avait divergé de la décision documentée.
2. **Volume et rythme d'interactions DOM excessifs** : `_fill_missing_permalinks_from_ui` rouvre le menu « ⋯ » de *toutes* les cartes visibles à chaque scrape, sans cache — et le fix retry ajouté au point 1 (3 tentatives × plusieurs stratégies de clic) a triplé ce volume. Combiné à des relances rapprochées du même scrape pendant le debug (dry-run, diagnostics ad hoc, `--execute` répété), cela a produit des dizaines de clics automatisés en quelques minutes — un pattern comportemental que les heuristiques anti-abus de LinkedIn détectent, indépendamment du volume brut de requêtes réseau.
3. Aucune action n'était prise sur le `suggested_wait_time` déjà renvoyé par `RateLimitError` — rien n'empêchait de relancer immédiatement après une détection.

**Correctifs** :
- `LINKEDIN_HEADLESS` remis à `False` par défaut dans `linkedin-mcp/config/settings.py`, conformément à ADR-002.
- Cache disque `urn -> permalink` (`core/permalink_cache.py`) : un post résolu une fois n'est plus jamais re-cliqué.
- Plafond dur (`_MAX_UI_FALLBACK_PER_CALL = 4`) sur le nombre de cartes traitées par le fallback UI en un seul appel.
- Cooldown persistant inter-process (`core/rate_limit_guard.py`) : `detect_rate_limit` persiste le `suggested_wait_time` sur disque ; `navigate_and_wait`/`like`/`repost` refusent de démarrer une action tant que ce cooldown n'est pas écoulé, même dans un nouveau process.
- Espacement aléatoire (20s + jitter jusqu'à 15s) entre deux actions d'écriture (like/repost) via `enforce_write_action_pacing`.

## Bilan des actions réelles effectuées pendant le debug

Pour référence (aucune conséquence négative constatée) :
- 1 like réellement publié (post d'un contact du feed) — jamais retiré depuis.
- 0 repost réellement publié (les tentatives ont échoué avant confirmation, à chaque fois de façon sûre — aucun contenu partagé par erreur).

## Prévention

- Toujours vérifier `LINKEDIN_HEADLESS` après tout changement de config — il doit rester `False` (ADR-002). Envisager un test qui échoue si ce n'est pas le cas.
- Ne jamais reconstruire une URL de post à partir d'un ID extrait d'un permalien sans vérifier la nature de cet ID (share/ugcPost ≠ activity).
- Espacer les runs de test manuels d'au moins 1-2 minutes ; le cooldown et le pacing automatiques limitent maintenant le risque mais ne remplacent pas la prudence pendant le debug actif.
- En cas de rate limit : ne pas relancer immédiatement. Le cooldown persistant (`~/.cache/linkedin_scraper/cooldown.json`) bloque désormais les tentatives prématurées, y compris depuis un nouveau process.

## Liens

- ADR : [016-rate-limit-avoidance](../adr/016-rate-limit-avoidance.md), [002-headless-false-required](../adr/002-headless-false-required.md)
- Consommateur : [linkedin-mcp](https://github.com/vinzlac/linkedin-mcp) — tools `like_post`, `repost_post`, `repost_post_scrape`, `scrape_post`
- Script de validation ajouté : `linkedin-mcp/test_scrape_like_repost_feed.py`
