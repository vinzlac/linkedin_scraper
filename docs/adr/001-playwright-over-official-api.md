# ADR-001 : Playwright plutôt que l'API officielle LinkedIn

## Status

Accepted

## Context

Le projet `linkedin-mcp` (fork de FilippTrigub) utilise l'API officielle LinkedIn via OAuth2. Cette API fonctionne pour créer des posts (`POST /v2/ugcPosts`, scope `w_member_social`), mais la **lecture des posts est bloquée** :

| Scope | Usage | Disponibilité |
|-------|-------|---------------|
| `w_member_social` | Créer des posts | Apps standard ✅ |
| `r_member_social` | Lire des posts | Marketing Developer Platform uniquement ❌ |

Le scope `r_member_social` est réservé aux partenaires LinkedIn (Marketing Developer Platform). Même avec un code correct, l'API renvoie **403 Forbidden** sur tous les endpoints de lecture (`/v2/ugcPosts`, `/v2/shares`). Cette restriction est documentée dans les LinkedIn Developer Docs et non contournable pour les développeurs individuels.

L'objectif du projet étant de lire le feed et les posts, l'API officielle est une impasse.

## Decision

Utiliser **Playwright** pour automatiser un navigateur authentifié et extraire les données directement du DOM, en réutilisant la structure existante du repo `joeyism/linkedin_scraper` qui utilise déjà cette approche pour les profils et les posts d'entreprise.

## Consequences

**Avantages :**
- Accès à toutes les données visibles par un utilisateur connecté
- Pas de restriction de scope API
- Réutilisation de l'infrastructure Playwright existante

**Inconvénients :**
- Fragile face aux changements de DOM LinkedIn (class names obfusqués, structure changeante)
- Nécessite un navigateur réel (plus lourd qu'une requête HTTP)
- Risque de violation des CGU LinkedIn
- Nécessite une session utilisateur (pas de service account)
- LinkedIn peut détecter et bloquer le scraping automatisé
