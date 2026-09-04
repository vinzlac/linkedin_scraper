# ADR-020 : Ancres DOM et identité de post après la refonte du rendu du feed (septembre 2026)

**Status** : Accepted (supersede [ADR-004](004-data-urn-stable-anchor.md))

## Context

Le 2026-09-03, une tâche planifiée consommant `scrape_feed` via `linkedin-mcp` a remonté cinq anomalies simultanées : `urn` valant un `urn:li:compkey:` au lieu d'un `urn:li:activity:`, `author_name` portant le contact réseau au lieu de l'auteur du contenu, `comments` systématiquement vide malgré `comments_count > 0`, `reactions_count` à `null`, et `reposts_count` à `null` sur 5 posts sur 5.

L'inspection du feed **live** (17 cartes réelles, session connectée) a montré qu'il ne s'agissait pas de cinq bugs indépendants mais d'une seule cause : LinkedIn a refondu le rendu du feed (CSS atomisé, classes hashées) et **toutes les ancres sur lesquelles le scraper reposait ont disparu en même temps** :

| Ancre historique | État constaté le 2026-09-03 |
|---|---|
| `data-urn="urn:li:activity:…"` (ADR-004) | **absent** de toutes les cartes inspectées |
| `<time>` | **absent** |
| `.comments-comment-item`, `[data-id^="urn:li:comment"]` | **absents** |
| `aria-label` portant les compteurs (« 42 réactions ») | **absents** — plus aucun bouton n'en porte |
| `[componentkey]` | **seule ancre survivante** (56 par carte) |

Trois conséquences structurelles se sont ajoutées, invisibles depuis le code seul :

1. Chaque carte s'ouvre désormais par une ligne « Post du fil d'actualité », ce qui décale d'un cran toute lecture par index de ligne (le scraper lisait `allLines[1]` pour la ligne d'acteur).
2. L'acteur d'une carte d'activité est annoncé sous **deux** formes : suffixe (« Y a republié ce contenu ») et **préfixe** (« Suivi par Y », « Recommandé par Y »). Seule la première était reconnue.
3. Les réactions basculent en **preuve sociale** (« Réaction de X et 154 autres personnes ») dès qu'une relation a réagi : aucune ligne ne commence alors par un chiffre.

ADR-004 postulait que `data-urn` était « documenté comme stable anchor — LinkedIn le maintient car c'est leur système d'adressage interne ». Ce postulat ne tient plus.

## Decision

### 1. L'identité d'un post se dérive du permalien, jamais d'un compkey

`urn` n'expose plus jamais un `urn:li:compkey:` dès qu'un permalien a pu être résolu, quelle que soit la branche de résolution (DOM, menu overflow, copy-link). `_canonical_activity_urn_from_url()` en extrait `urn:li:activity:<id>` — depuis un slug `-share-` / `-ugcPost-` / `-activity-` ou depuis une URN embarquée. Le compkey est conservé dans un champ dédié `feed_compkey`, pour le debug uniquement.

Motivation : le compkey est une **clé de carte de feed**, éphémère et dépendante de la session. L'exposer comme identifiant de post crée un doublon en base à chaque scrape du même post, et il n'est exploitable par aucune action en aval.

### 2. `linkedin_url` n'est pas normalisé vers `/feed/update/`

Le permalien `/posts/…` renvoyé par le DOM est conservé tel quel. On ne reconstruit **pas** `https://www.linkedin.com/feed/update/urn:li:activity:<id>/` à partir du id du slug : celui-ci est un id de share ou de ugcPost, et cette URL peut tomber sur une page sans barre d'action alors que le permalien d'origine se charge très bien (cf. [ADR-003 de linkedin-mcp](https://github.com/vinzlac/linkedin-mcp/blob/main/docs/adr/003-post-action-url-cascade.md)).

Conséquence assumée : `urn` et `linkedin_url` ne sont pas redondants. `urn` est la **clé de déduplication**, `linkedin_url` l'**adresse navigable**. Les consommateurs qui déclenchent une action doivent passer `linkedin_url`.

### 3. `componentkey` remplace les classes CSS comme ancre de commentaire

Les commentaires sont ancrés sur `[componentkey^="replaceableComment_"]` (et la section sur `[componentkey^="commentsSectionContainer"]`), les anciennes classes étant conservées en repli pour les surfaces non encore migrées. Le componentkey d'un commentaire embarque au passage l'URN d'activité du post parent : `replaceableComment_urn:li:comment:(urn:li:activity:<id>,…)`.

Le corps du commentaire n'ayant plus de conteneur dédié, il est délimité **comme le post lui-même** : à partir de l'horodatage (l'en-tête — nom, badge, degré, accroche — le précède), en s'arrêtant à la première ligne d'action, de compteur, ou de chiffre nu.

### 4. Les compteurs se lisent dans le texte, bornés à la barre d'action

La branche `aria-label` est conservée (sans coût, et LinkedIn peut la réintroduire) mais n'est plus le chemin nominal. Deux règles s'ajoutent :

- **preuve sociale** : « X et N autres personnes » vaut `N + 1` réactions ;
- **bornage** : le scan des compteurs s'arrête à la barre d'action (J'aime / Commenter / Republier / Envoyer), frontière entre le post et ses commentaires affichés. Sans cette borne, le scan ramassait le « N réactions » d'un commentaire : une carte à 272 réactions en remontait **4**, silencieusement.

La barre d'action est détectée séparément de la fin de contenu (`endIdx`), qui peut tomber bien avant sur « … plus » ou « Afficher la traduction », et reconnaît l'apostrophe typographique (`J’aime`) en plus de l'apostrophe droite.

### 5. L'acteur se détecte par motif, jamais par index de ligne

Les deux formes (suffixe et préfixe) sont reconnues, les formes plurielles incluses (« ont aimé », « aiment »), en balayant les **quatre premières lignes** de la carte plutôt qu'un index fixe. Une ligne de wrapper insérée en tête par LinkedIn ne casse plus l'attribution d'auteur.

### 6. Principe général : préférer les motifs textuels et structurels aux attributs

Là où ADR-004 pariait sur la stabilité d'un attribut propriétaire, la règle devient : **s'ancrer en priorité sur ce que l'utilisateur voit** (libellés FR/EN, forme des lignes, position relative à la barre d'action) et sur la **structure invariante** (un bouton Republier par carte, l'horodatage précède le contenu), en traitant tout attribut LinkedIn comme un raccourci opportuniste et non comme un contrat.

Corollaire opérationnel : toute correction de sélecteur doit être **validée sur le feed live** avant d'être considérée comme faite, et figée par une fixture DOM calquée sur le rendu réel (cf. `TestFeedCardActorAndCountsDom`, `TestFeedCardCountsAndCommentsDom`, `TestExpandVisibleCommentsDom`).

## Consequences

**Positif**

- `urn` redevient une clé de déduplication fiable : plus de doublons en base à chaque exécution d'une tâche planifiée.
- Les cinq anomalies sont couvertes par des tests DOM headless qui exercent le vrai JS d'extraction, pas des mocks : une prochaine dérive du rendu casse un test au lieu de produire des données fausses.
- Le mode d'échec le plus dangereux — un compteur **faux** plutôt qu'absent — est éliminé par le bornage.

**Coûts et limites**

- Les motifs textuels sont dépendants de la langue. FR et EN sont couverts ; une session dans une troisième langue dégraderait la détection d'acteur et de compteurs (échec silencieux : valeurs `null`, pas d'exception).
- Le corps d'un commentaire reste une heuristique de délimitation : un commentaire dont la dernière ligne est un nombre nu sera tronqué à cette ligne. Trade-off accepté contre le risque inverse (polluer `top_comment` avec des puces de compteur).
- `feed_compkey` ajoute un champ au modèle public `Post`. Il est explicitement documenté comme champ de debug, à ne jamais utiliser comme identifiant.
- La dépendance à `componentkey` reproduit, en plus faible, le pari d'ADR-004 : c'est aujourd'hui la seule ancre structurelle disponible. La différence est qu'elle n'est plus le chemin unique — les motifs textuels prennent le relais si elle disparaît.

## Liens

- Post-mortem associé : [2026-09-03-feed-rendering-drift](../post-mortem/2026-09-03-feed-rendering-drift.md)
- ADR superseded : [ADR-004 — data-urn comme ancre stable](004-data-urn-stable-anchor.md)
- ADR liée (le pourquoi du `page.evaluate` inline) : [ADR-003](003-js-evaluation-over-locators.md)
- ADR liée (plafond de clics UI et rate limit) : [ADR-016](016-rate-limit-avoidance.md)
- Commits : `050e2c6`, `cc3c906`, `15e6352` — version `4.4.0`
- Consommateur : [linkedin-mcp](https://github.com/vinzlac/linkedin-mcp) — tools `scrape_feed`, `scrape_post`, `like_post`, `repost_post`
