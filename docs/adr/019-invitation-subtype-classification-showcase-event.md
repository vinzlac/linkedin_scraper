# ADR-019 : Classification par pattern d'URL pour les sous-types d'invitation (Showcase, Event)

**Status** : Accepted

## Context

`InvitationScraper` classe chaque carte de `/mynetwork/invitation-manager/received/` en un `invitation_kind` (`connection`, `follow_person`, `follow_company`, `follow_newsletter`, `unknown`) depuis 2026-08-14 (commit `e19a1b3`). La classification repose sur deux signaux combinés dans `classify_invitation()` :

1. Les **liens d'entité** présents dans la carte (`/in/`, `/company/`, `/newsletters/`), extraits par `_extract_entity_links()` via un sélecteur CSS `a[href*="..."]` par type.
2. Le **texte de la carte** (regex FR/EN : "vous a invité à suivre", "invited you to follow"...) pour désambiguïser quand plusieurs entités sont présentes (ex. une personne qui invite à suivre une page).

Une revue croisée avec le repo `linkedin-auto-responder` (2026-09-01) a signalé que ce schéma ne couvrait pas tous les types de cartes que LinkedIn peut afficher sur cette page précise. Une recherche externe (aide LinkedIn officielle + filtres UI confirmés "Pages"/"Events" sur l'Invitation Manager) a confirmé deux gaps réels :

- **Pages Showcase** (`/showcase/{slug}/`) — URL top-level distincte de `/company/{slug}/`, même mécanique "invited you to follow" que les Pages entreprise.
- **Événements LinkedIn** (`/events/{id_numérique}/`) — invitations à un événement, filtrables via un chip "Events" propre à cette page.

Sans lien capturé pour ces deux types, la carte n'a aucune entité (`persons=[]`, `companies=[]`, `newsletters=[]`) : `classify_invitation()` retombe sur `unknown` avec `target=None`, et si la carte n'a pas d'attribut `data-invitation-id`, elle est **silencieusement exclue** des résultats (`_parse_card` retourne `None` faute d'`invitation_id`, cf. ligne "Skipping card without invitation_id").

Une autre piste (invitations "réseau d'école/alumni") a été investiguée et **écartée** : ce sont des demandes de connexion `/in/{slug}` standard, seulement regroupées par un filtre UI "Your School" — pas un sous-type de carte distinct, donc déjà couvert par `connection`.

## Decision

Étendre le même schéma (liens d'entité par pattern d'URL + priorité de classification), sans changer l'architecture de `classify_invitation()` :

- Ajout de `_SHOWCASE_RE` (`/showcase/{slug}/`) et `_EVENT_RE` (`/events/{id_numérique}/`), au même niveau que `_PROFILE_RE`/`_COMPANY_RE`/`_NEWSLETTER_RE`.
- `_extract_entity_links()` retourne désormais 5 listes (`persons, companies, newsletters, showcases, events`) au lieu de 3.
- Deux nouveaux `InvitationKind` : `follow_showcase_page`, `event_invitation`.
- Ordre de priorité dans `classify_invitation()` : `newsletter` → **`event`** → **`showcase`** → `company` → `follow_person`/`follow_company` (via texte) → `connection` → `unknown`. Les nouveaux types passent **avant** `company`/`connection` : une carte d'événement ou de Showcase peut aussi contenir un lien `/in/` (l'organisateur, l'admin qui invite) qui ne doit pas la faire classer à tort en `connection` ou `follow_person`.
- `_find_card_by_id` (utilisé par `accept`/`ignore`) reconnaît aussi les slugs Showcase et l'id numérique d'Event, pour que ces invitations restent actionnables.

## Consequences

- **Positif** : plus de cartes silencieusement perdues pour ces deux types ; les consommateurs (ex. `linkedin-mcp` / `list_pending_invitations`) reçoivent un `invitation_kind` exploitable au lieu de `unknown`/absence.
- **Limite assumée** : le format exact du texte affiché par LinkedIn sur une carte Event/Showcase réelle n'a pas pu être observé en usage réel au moment du fix (aucune invitation de ce type disponible sur le compte de test) — la classification s'appuie donc uniquement sur le **pattern d'URL**, qui est un signal stable et suffisant indépendamment du texte, contrairement à ce dernier qui varie selon la langue/formulation UI. Si LinkedIn introduit un jour un format de carte Event/Showcase sans lien direct vers l'entité cible, ce mécanisme ne suffira plus.
- Le nombre de branches dans `classify_invitation()` continue de croître de façon linéaire avec chaque nouveau type d'entité LinkedIn — acceptable tant que le nombre de types reste faible (7 aujourd'hui), à réévaluer (dispatch par type au lieu d'un if/elif long) si de nouveaux types apparaissent encore.

## Liens

- Post-mortem associé : [2026-09-01-invitation-kind-showcase-event-gap](../post-mortem/2026-09-01-invitation-kind-showcase-event-gap.md)
- Commit : `512a13e` (`feat(invitations): classify showcase-page and event invitation cards`)
- ADR liée (introduction initiale de la classification) : commit `e19a1b3` (pas d'ADR écrit à l'époque)
- Consommateur : [linkedin-mcp](https://github.com/vinzlac/linkedin-mcp) — tool `list_pending_invitations`
