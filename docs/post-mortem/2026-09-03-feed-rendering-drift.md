# Post-mortem : cinq champs de `scrape_feed` cassés par une refonte du rendu du feed

**Date** : 2026-09-03 (correctifs), 2026-09-04 (déploiement)
**Statut** : Résolu — `linkedin_scraper` 4.4.0 (PyPI), déployé via `linkedin-mcp` en prod
**Impact réel observé** : dégradation silencieuse des données d'une tâche planifiée, sans erreur ni alerte
**Repos concernés** : `linkedin_scraper` (ce repo) et `linkedin-mcp` (consommateur)

---

## Ce qui s'est passé

La tâche planifiée `linkedin-feed-11h` (scrape de 5 posts du feed → injection Notion → like + repost du meilleur post) a abouti, mais uniquement grâce à des contournements manuels de l'agent qui l'exécutait. Un pipeline strict, qui aurait utilisé les valeurs retournées telles quelles, aurait échoué sur les étapes like et repost — et aurait silencieusement pollué la base Notion.

Le rapport de bug listait cinq symptômes :

| # | Symptôme | Fréquence observée |
|---|---|---|
| 1 | `urn` = `urn:li:compkey:…` au lieu de `urn:li:activity:…` | 4 posts / 5 |
| 3 | `author_name` = le re-posteur, `actor_name` = `null` | 1 post / 5 |
| 4 | `comments` = `[]` malgré `comments_count` de 9 à 52 | 5 / 5 |
| 5a | `reactions_count` = `null` | 2 / 5 |
| 5b | `reposts_count` = `null` | 5 / 5 |

(Le symptôme #2 — `like_post` / `repost_post` en échec sur un URN — relève de `linkedin-mcp` et fait l'objet d'un [post-mortem distinct](https://github.com/vinzlac/linkedin-mcp/blob/main/docs/post-mortem/2026-09-03-feed-report-urn-and-ui-actions.md).)

**Aucune erreur n'a été levée.** Les champs manquants valaient `null`, les champs faux ressemblaient à des champs justes. C'est le mode de défaillance le plus coûteux : la tâche se déclare en succès et la dégradation se propage en base.

## Investigation

L'analyse initiale, faite **par lecture de code**, a produit quatre causes racines dont trois se sont révélées fausses ou incomplètes. C'est l'enseignement principal de cet incident.

| Hypothèse issue du code | Réalité constatée en live |
|---|---|
| #1 : la branche de fallback copy-link ne rétro-alimente pas `urn` | ✅ **exacte** |
| #5b : le Python lit `repostsText`, que le JS ne produit jamais | ✅ **exacte** |
| #3 : sur une carte de repost, le scraper lit le bloc auteur du wrapper au lieu du bloc embarqué | ❌ **fausse** — il existe deux formulations d'acteur, et seule la forme suffixe était reconnue |
| #4 : `comments` ne retient que les commentaires porteurs d'un lien externe (choix de conception) | ⚠️ **incomplète** — vrai, mais les sélecteurs de commentaires ne matchaient de toute façon plus rien |
| #5a : le compteur n'est pas encore rendu sur les posts récents | ❌ **fausse** — c'est la preuve sociale, indépendante de la récence |

Le basculement s'est fait en ouvrant une session navigateur sur le feed réel et en y exécutant **le JS d'extraction du scraper lui-même**, carte par carte. Technique employée, réutilisable :

```bash
# 1. extraire la constante JS depuis le source Python
python3 -c "import ast, pathlib; \
  tree = ast.parse(pathlib.Path('linkedin_scraper/scrapers/feed.py').read_text()); \
  js = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) \
        and isinstance(n.value, str) and 'isRepostButton' in n.value][0]; \
  pathlib.Path('/tmp/feed_extract.js').write_text(js)"

# 2. l'exécuter tel quel sur le feed live, sans lancer de session Playwright séparée
#    (ego-browser : contexte isolé qui réutilise l'état de connexion de l'utilisateur)
ego-browser nodejs <<'EOF'
const { readFileSync } = await import('node:fs')
const posts = await js('(' + readFileSync('/tmp/feed_extract.js', 'utf8') + ')()')
posts.forEach((p, i) => cliLog(i + ' ' + JSON.stringify({
  urn: p.urn, author: p.authorName, actor: p.actorName,
  react: p.reactionsText, reposts: p.repostsText })))
EOF
```

Sortie exacte du scraper sur 17 cartes réelles, en une commande, sans instrumenter le code.

## Cause

Une seule : **LinkedIn a refondu le rendu du feed** (CSS atomisé, classes hashées), et toutes les ancres du scraper ont disparu simultanément.

- `data-urn` — absent (c'était l'ancre « stable » d'[ADR-004](../adr/004-data-urn-stable-anchor.md), désormais superseded)
- `<time>` — absent
- `.comments-comment-item`, `[data-id^="urn:li:comment"]` — absents
- `aria-label` portant les compteurs — absents de **tous** les boutons
- `[componentkey]` — seule ancre survivante

Plus trois changements de structure : une ligne de wrapper « Post du fil d'actualité » en tête de carte (qui décale toute lecture par index), une seconde formulation d'acteur en préfixe (« Suivi par X »), et le basculement des réactions en preuve sociale (« Réaction de X et 154 autres personnes »).

Le cas le plus grave n'était pas dans le rapport. Le scan des compteurs parcourait **toutes** les lignes de la carte, y compris celles des commentaires affichés en dessous de la barre d'action. Sur une carte à 272 réactions dont un commentaire affichait « 4 réactions », `reactions_count` remontait **4**. Pas `null` : *faux*.

## Correctif appliqué

Détail des décisions et de leurs trade-offs dans [ADR-020](../adr/020-feed-dom-anchors-after-2026-09-rendering.md).

| Bug | Correctif |
|---|---|
| #1 | `_canonical_activity_urn_from_url()` dérive `urn:li:activity:<id>` du permalien dans **toutes** les branches ; compkey déplacé dans `feed_compkey` |
| #3 | Détection d'acteur en préfixe et en suffixe, formes plurielles incluses, sur les 4 premières lignes au lieu d'un index fixe |
| #4 | Ancres `componentkey`, corps du commentaire délimité à partir de l'horodatage, matcher d'ouverture des fils basé sur l'innerText ; nouveau champ `top_comment` (`comments` inchangé) |
| #5a | Motif de preuve sociale (`X + N autres` = `N + 1`) et bornage du scan à la barre d'action |
| #5b | Extraction de `repostsText` (aria-labels + motif groupé « X commentaires · Y republications ») |

Validation sur les mêmes 17 cartes live, après correction :

| Métrique | Avant | Après |
|---|---|---|
| `reactions_count` manquant ou faux | 2 `null` + 1 valeur fausse | **0** |
| `reposts_count` manquant | 17 | **1** (post d'1 h, sans repost) |
| acteurs détectés | 4 (forme suffixe seule) | **5** (les deux formes) |
| `top_comment` | — | propre, **3/3** des cartes chargées après réouverture des fils |

## Dettes trouvées en chemin

L'inspection live a révélé deux régressions silencieuses **non signalées** dans le rapport, corrigées dans la foulée :

1. **Le feed ne scrolle plus la fenêtre mais `<main>`** (`document.scrollHeight == clientHeight`). `_scroll_for_more_posts` utilise `mouse.wheel` et n'était pas affecté ; en revanche les `window.scrollBy(...)` de `linkedin-mcp` étaient devenus des no-op (corrigé côté MCP).
2. **`_expand_visible_comments_for_url_scrape` ne trouvait plus rien** : le contrôle « N commentaires » est devenu un `div[role="button"]` **sans** `aria-label`, alors que la fonction ne cliquait que des `button[aria-label*="commentaire"]`. Corrigé par un matcher sur l'innerText, avec exclusion explicite du composeur et des menus d'options. Mesuré en live : 3 → 21 commentaires rendus. Le plafond de 8 clics est conservé ([ADR-016](../adr/016-rate-limit-avoidance.md)).

## Prévention

- **Ne plus conclure sur une régression DOM sans l'avoir observée en live.** Trois hypothèses sur cinq issues de la lecture de code étaient fausses, et toutes étaient plausibles. Le coût de la vérification live est de quelques minutes ; le coût d'un correctif basé sur une hypothèse fausse est un second incident.
- **Figer chaque constat live par une fixture DOM.** Les six tests DOM headless ajoutés exercent le vrai JS d'extraction sur des fixtures calquées sur le rendu réel. Piège rencontré en les écrivant : il faut **un bloc HTML par ligne d'`innerText`** — des `<span>` adjacents se collent en une seule ligne et rendent la fixture infidèle (elle passait à côté du bug qu'elle prétendait couvrir).
- **Se méfier des valeurs plausibles autant que des valeurs absentes.** Un `null` finit par se voir ; un `4` au lieu de `272` se propage. Le bornage des scans à une frontière structurelle (ici la barre d'action) est ce qui distingue « je n'ai pas trouvé » de « j'ai trouvé autre chose ».
- **Traiter tout attribut LinkedIn comme un raccourci opportuniste**, jamais comme un contrat — c'est le principe posé par ADR-020, et la leçon de la disparition simultanée de `data-urn`, `<time>` et des `aria-label` de compteurs.

## Champs et outils concernés

- `Post.urn`, `Post.feed_compkey` (nouveau), `Post.author_name`, `Post.actor_name`, `Post.reactions_count`, `Post.reposts_count`, `Post.comments`, `Post.top_comment` (nouveau)
- `FeedScraper.scrape` / `scrape_post_by_url` → tools MCP `scrape_feed`, `scrape_post`

## Commits / versions

| Commit | Objet |
|---|---|
| `050e2c6` | urn canonique, `reposts_count`, `top_comment` |
| `cc3c906` | acteur en préfixe, preuve sociale, ancres de commentaires |
| `15e6352` | réouverture des fils de commentaires |
| `fd90234` | bump 4.4.0 |

PR [#3](https://github.com/vinzlac/linkedin_scraper/pull/3) · tag `v4.4.0` · publication PyPI par OIDC ([ADR-018](../adr/018-pypi-publication.md))
