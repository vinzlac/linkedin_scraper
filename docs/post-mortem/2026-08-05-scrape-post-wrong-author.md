# Post-mortem : `scrape_post` retournait le compte connecté comme auteur

**Date** : 2026-08-05
**Statut** : Résolu (`linkedin-playwright-scraper` 4.0.1)
**Impact** : `scrape_post` (MCP `linkedin-mcp`) retournait systématiquement `author_name`/`author_url` du compte LinkedIn connecté au lieu de l'auteur réel, sur les URLs `/posts/...` et `/feed/update/...` ; `scrape_feed` n'était pas affecté
**Repos concernés** : `linkedin_scraper` (ce repo) et `linkedin-mcp`

---

## Chronologie

### Symptôme rapporté

3 appels `scrape_post` sur 3 posts d'auteurs différents (Maxime Brunet, un post via `feed/update/urn:li:activity:...`, Pierre Evrard) ont tous les trois renvoyé `author_name: "Vincent Lacoste"` (le compte connecté utilisé par la session Playwright), avec `author_url` pointant vers son propre profil. Le reste du post (`text`, `reactions_count`, `urn`...) était correct — seuls `author_name`/`author_url` étaient faux.

Un correctif similaire avait déjà été appliqué le 23/06/2026 (`_correct_author_on_detail_page`, voir commit `8726a8f`) pour exactement ce type de confusion (auteur du post vs navbar du compte connecté). Le bug semblait donc être une régression, ou un correctif jamais réellement efficace pour `scrape_post` spécifiquement.

### Investigation

Les logs du pod `linkedin-mcp` en prod (k3s) montraient les 3 appels `scrape_post` du rapport, avec navigation réussie, mais **aucun** log `"Author corrected on detail page"` ni `"Could not extract author on detail page"` — alors que `_correct_author_on_detail_page` est censé logguer dans un des deux cas dès qu'elle s'exécute sur une URL de détail. Cette absence de log était le premier indice que la fonction retournait tôt sans rien trouver à corriger, plutôt que d'échouer bruyamment.

Inspection en direct de la page LinkedIn réelle (`https://www.linkedin.com/posts/maxime-brunet-shunpo_...`) via navigateur, avec le même JS que celui exécuté par `_extract_author_from_post_card()` :

```json
{ "postRootsCount": 0, "pageActorsCount": 0, "hits": [], "pageActorHits": [] }
```

**Cause racine n°1** : LinkedIn a migré la page de détail d'un post (`/posts/...`) vers des classes CSS **atomisées et hashées** (`_74151fd5 _3adf7052 _29e627b8 ...`) — plus aucune des classes attendues n'existe sur cette page : `.feed-shared-actor`, `.update-components-actor`, `#global-nav`, `header.global-nav`, et aucun attribut `data-view-name`. Toute la logique de sélection CSS du correctif de juin (et de l'extraction principale `_extract_posts_from_feed`) matchait donc **zéro élément**, silencieusement.

En cherchant tous les liens `a[href*='/in/']` sur la page (sans filtre de classe), le vrai lien vers l'auteur (`/in/maxime-brunet-shunpo/`, texte `"Maxime Brunet • Suivi"`) était bien présent — mais un lien de bannière promotionnelle (« Essayez Premium All-in-One pour 0 € ») réutilisait par coïncidence le même slug d'URL en préfixe (`/posts/maxime-brunet-shunpo_...`), et le propre profil du compte connecté (« Vincent Lacoste ») apparaissait tôt dans le DOM via un encart de suggestion/nudge de profil — c'est ce dernier que l'ancienne logique heuristique (« premier lien `/in/` trouvé ») capturait en pratique en amont, avant même que le correctif de juin n'entre en jeu.

**Cause racine n°2** (découverte en testant le fix) : même une fois le bon conteneur/lien localisé, le code faisait confiance à `a.querySelector("span[aria-hidden='true']")` pour le nom affiché, en le préférant systématiquement au texte visible de l'ancre :

```js
var name = nameSpan
    ? (nameSpan.innerText || "").trim()
    : (a.innerText || "").trim();
```

Sur la page redessinée, ce `span[aria-hidden='true']` existe (c'est une icône décorative) mais est **vide**. Le nom réel (`"Pierre Evrard • 1er"`) est dans le texte visible de l'ancre elle-même, jamais atteint car `nameSpan` était non-null (juste vide) — le candidat retenu se retrouvait donc réduit à `""`, en dessous du seuil minimal de longueur, et rejeté silencieusement. Ce bug affectait 4 endroits du fichier partageant le même motif.

## Correctifs (`linkedin_scraper` 4.0.1, commit `2858e8f`)

1. **Repli class-agnostic** dans `_extract_author_from_post_card()` : après l'échec des sélecteurs CSS classiques, recherche de tous les liens `/in/` ou `/company/` (hors chrome global) dont le texte visible contient un **suffixe de degré de connexion LinkedIn** — `"Nom • Suivi"`, `"Nom • Following"`, `"Nom • 1er"`, `"Nom • 1st"`, `"Nom • 3e et +"`. Ce motif est un artefact fonctionnel de LinkedIn (badge de degré de relation), stable indépendamment du système de classes CSS utilisé, contrairement aux classes elles-mêmes.
2. **Fix du `nameSpan` vide** à 4 endroits (`_get_session_user_profile`, `profileFromAnchor`, la nouvelle recherche par suffixe de degré, `profileLinkFromAnchor`) : le texte du `nameSpan` n'est utilisé que s'il est réellement non-vide après `trim()`, sinon repli sur le texte visible de l'ancre.
3. Test de non-régression Playwright (`TestExtractAuthorFromPostCardDom`, `tests/test_feed_scraper.py`) : lance un vrai navigateur headless sur une page HTML statique reproduisant le DOM cassé exact (classes hashées, lien "Vincent Lacoste" en leurre sans suffixe de degré, `nameSpan` vide sur le vrai lien auteur) — vérifie que `_extract_author_from_post_card()` retourne bien le bon auteur.

Vérifié en direct sur 2 des 3 URLs du rapport (`maxime-brunet-shunpo`, `pierre-evrard-dashboard`) : auteur correctement résolu après fix, alors qu'avant fix les deux retournaient le compte connecté.

## Point non-bug découvert en creusant : cas `feed/update/urn:li:activity:...`

Le 3e cas du rapport (`https://www.linkedin.com/feed/update/urn:li:activity:7490383761457541120/`) attendait `"Charlie Hills 🦩"` (d'après `scrape_feed`), mais la page de détail affiche `"Eric Melillo"` en tant qu'acteur principal. Ce n'est probablement **pas un bug d'extraction** : l'URL de détail pointe vers l'activité elle-même, et si ce post est un repost (Charlie Hills reprend/partage un post d'Eric Melillo), `scrape_feed` affiche le **resharer** (tel qu'affiché sur la carte du fil) tandis que `scrape_post` sur l'URL de détail affiche l'**auteur original** intégré dans l'activité. Les deux valeurs sont "correctes" selon la définition retenue, mais incohérentes entre les deux outils — à traiter séparément si une sémantique unifiée est nécessaire (ex. exposer les deux champs `original_author` et `resharer` sur les reposts).

## Prévention

- Ne plus tenir pour acquis qu'un `span[aria-hidden='true']` présent contient du texte utile : toujours vérifier qu'il est non-vide avant de l'utiliser en priorité sur le texte visible du parent.
- Pour l'extraction d'acteur sur les pages LinkedIn, préférer quand c'est possible un signal fonctionnel stable (motif de texte, comportement) à un sélecteur de classe CSS — LinkedIn migre régulièrement vers du CSS généré/atomisé sans préavis, ce qui casse silencieusement (zéro élément matché, pas d'erreur) tout sélecteur basé sur des noms de classes.
- Quand une fonction de correction peut légitimement ne rien avoir à corriger, s'assurer qu'elle distingue *observablement* (log, champ de résultat) « rien trouvé à corriger » de « recherche non tentée / a échoué silencieusement » — l'absence de tout log dans les 3 cas du rapport a été le signal clé qui a permis de localiser rapidement la cause.

## Liens

- Commit fix : `2858e8f` (`fix(feed): resolve real author on posts using hashed atomic-CSS markup`)
- Version publiée : `linkedin-playwright-scraper==4.0.1` (tag `v4.0.1`)
- Post-mortem lié (bug similaire, cause différente) : [2026-06-25-feed-repost-aria-label](2026-06-25-feed-repost-aria-label.md)
- Consommateur : [linkedin-mcp](https://github.com/vinzlac/linkedin-mcp) — tool `scrape_post`
