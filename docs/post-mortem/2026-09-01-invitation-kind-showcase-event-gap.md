# Post-mortem : sous-types d'invitation Showcase/Event non classifiés (jamais captés)

**Date** : 2026-09-01
**Statut** : Résolu (`linkedin_scraper` commit `512a13e`)
**Impact réel observé** : aucun — pas un incident de production. Gap structurel trouvé via revue de code, avant tout impact utilisateur rapporté.
**Repos concernés** : `linkedin_scraper` (ce repo) et `linkedin-mcp` (consommateur de `list_pending_invitations`)

---

## Origine

Ce n'est pas un post-mortem d'incident classique : aucun bug n'a été rapporté en prod. Le point de départ est une **dette technique remontée par une revue croisée** du repo `linkedin-auto-responder` (2026-09-01), formulée ainsi :

> Dette upstream MCP — sous-type d'événements incomplet. `invitation_kind` couvre `connection/follow_person/follow_company/follow_newsletter/unknown`. Pas de sous-type pour d'autres types d'items LinkedIn (ex. invitations à un groupe/événement) si LinkedIn en présente. Pas de ticket concret tant que ça n'a pas été observé en usage réel.

La recommandation initiale était donc d'attendre une observation réelle avant d'agir. L'investigation qui a suivi a changé cette conclusion.

## Investigation

1. **Lecture du code de classification** (`classify_invitation()` + `_extract_entity_links()` dans `invitations.py`) : le sélecteur de liens ne cherchait que `a[href*="/in/"], a[href*="/company/"], a[href*="/newsletters/"]`. Toute carte dont l'entité cible utilise un autre pattern d'URL n'a **aucun lien capturé** → `classify_invitation()` retombe sur la branche `else: kind = "unknown"` avec `target=None` → si la carte n'a pas d'attribut `data-invitation-id`, elle est renvoyée `None` par `_parse_card` et **disparaît silencieusement** des résultats de `list_pending_invitations` (aucune erreur, aucun log d'anomalie).
2. **Vérification en direct** : appel de l'outil `list_pending_invitations` sur le compte de production réel — une seule invitation en attente au moment du test, de type `connection` standard, déjà correctement classée. Impossible de confirmer empiriquement d'autres types depuis cette session (pas assez de volume d'invitations en attente).
3. **Recherche externe** (WebSearch + confirmation Perplexity, sources : LinkedIn Help Center, aide officielle Pages/Newsletters, capture d'écran documentée d'une carte "invited you to follow") pour déterminer les vrais types de cartes affichés sur cette page précise (`/mynetwork/invitation-manager/received/`), plutôt que de deviner :
   - **Confirmé, gap réel** : Pages **Showcase** (`/showcase/{slug}/`, distinct de `/company/{slug}/`) et **Événements** (`/events/{id_numérique}/`, filtre UI "Events" natif sur cette page).
   - **Piste écartée** : invitations "réseau d'école/alumni" — ce sont des demandes de connexion `/in/{slug}` standard, seulement regroupées par un filtre "Your School" ; pas un sous-type de carte distinct, déjà couvert par `connection`.
   - **Piste écartée** : groupes LinkedIn et invitations à un événement de groupe — ont leurs propres flux d'invitation séparés, n'apparaissent pas sur cette page précise.

## Cause racine

Le sélecteur de liens `_extract_entity_links()` a été conçu au moment de l'ajout initial de `invitation_kind` (commit `e19a1b3`, 2026-08-14) en couvrant les trois types d'entité observés à l'époque (personne, entreprise, newsletter), sans anticiper les autres URLs top-level que LinkedIn utilise pour ses Pages (Showcase) et ses Événements. Le mécanisme de repli (`unknown` + skip silencieux si pas de `data-invitation-id`) masque le problème au lieu de le signaler : aucune erreur, aucun warning, la carte disparaît juste des résultats.

## Correctif (`linkedin_scraper` commit `512a13e`)

Voir [ADR-019](../adr/019-invitation-subtype-classification-showcase-event.md) pour le détail de la décision. En résumé :

1. Ajout de `_SHOWCASE_RE` et `_EVENT_RE`, extension de `_extract_entity_links()` pour capturer ces deux types de liens en plus des trois existants.
2. Deux nouveaux `InvitationKind` : `follow_showcase_page`, `event_invitation`, priorisés avant `follow_company`/`connection` dans `classify_invitation()`.
3. `_find_card_by_id` étendu pour que `accept_invitation`/`ignore_invitation` reconnaissent aussi ces slugs.
4. 3 nouveaux tests unitaires (fixture HTML étendue avec une carte Showcase et une carte Event) — 13/13 sur `test_invitation_scraper.py`, 52/52 sur la suite complète.

## Limite assumée

Le format exact de carte Event/Showcase (texte affiché, structure DOM) n'a pas pu être validé sur une vraie invitation de ce type — aucune disponible sur le compte de test au moment du fix. Le correctif s'appuie uniquement sur le **pattern d'URL de l'entité liée**, qui est le signal le plus stable indépendamment du texte/langue de la carte (cf. le post-mortem [2026-08-05-scrape-post-wrong-author](2026-08-05-scrape-post-wrong-author.md) sur la fragilité des sélecteurs CSS/texte face aux changements d'UI LinkedIn). À revalider si une vraie carte de ce type est un jour capturée (`raw_card_text` disponible sur chaque `Invitation` pour du debug a posteriori).

## Prévention

- Quand un nouveau type d'entité LinkedIn (Page, Showcase, Event, School...) est identifié, vérifier systématiquement s'il utilise un **pattern d'URL top-level propre** avant de supposer qu'il est couvert par un type existant.
- Le mode d'échec silencieux de `_parse_card` (carte sans `invitation_id` → `None`, aucun log) est un facteur aggravant récurrent : une future itération pourrait logger un `warning` avec `raw_card_text` tronqué quand une carte a des boutons Accept/Ignore mais aucune entité extraite, pour rendre ce genre de gap visible en prod sans attendre une revue de code externe.
- Ne pas attendre une observation en usage réel quand le gap est **structurellement démontrable** par simple lecture du code (ici : sélecteur de liens incomplet) — la recommandation initiale ("pas de ticket tant que non observé") aurait laissé ce gap ouvert indéfiniment alors que la cause était vérifiable sans attendre.

## Liens

- ADR : [019-invitation-subtype-classification-showcase-event](../adr/019-invitation-subtype-classification-showcase-event.md)
- Commit fix : `512a13e` (`feat(invitations): classify showcase-page and event invitation cards`)
- PR : [vinzlac/linkedin_scraper#1](https://github.com/vinzlac/linkedin_scraper/pull/1)
- Origine du signalement : revue croisée `linkedin-auto-responder` (2026-09-01)
- Consommateur : [linkedin-mcp](https://github.com/vinzlac/linkedin-mcp) — tool `list_pending_invitations`
