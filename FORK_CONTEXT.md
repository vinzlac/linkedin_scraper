# Contexte du fork — linkedin_scraper

## Origin

Fork de [joeyism/linkedin_scraper](https://github.com/joeyism/linkedin_scraper).

## Pourquoi ce fork

### Problème de départ

Ce projet est né d'un constat simple : **l'API officielle LinkedIn ne permet pas de lire les posts**.

Un premier projet (`linkedin-mcp`, fork de FilippTrigub) expose des outils MCP pour interagir avec LinkedIn via l'API officielle. Il fonctionne pour :
- S'authentifier via OAuth2
- Créer des posts (`POST /v2/ugcPosts`)

Mais la **lecture des posts est bloquée** par LinkedIn :

| Scope | Usage | Disponibilité |
|-------|-------|---------------|
| `w_member_social` | Créer des posts | Apps standard ✅ |
| `r_member_social` | Lire des posts | Marketing Developer Platform uniquement ❌ |

Le scope `r_member_social` est réservé aux partenaires LinkedIn (Marketing Developer Platform). Il est inaccessible aux développeurs individuels. Même avec un code correct, l'API renvoie **403 Forbidden** sur tous les endpoints de lecture (`/v2/ugcPosts`, `/v2/shares`).

### Solution retenue : scraping web avec Playwright

L'API officielle étant une impasse, la seule approche réaliste est d'automatiser un navigateur authentifié. Ce repo utilise déjà Playwright et expose exactement la structure nécessaire.

## Objectif de ce fork

**Ajouter un `FeedScraper`** capable de récupérer les N premiers posts du feed LinkedIn de l'utilisateur authentifié.

Le feed LinkedIn correspond à la page `linkedin.com/feed/` — ce que l'utilisateur voit quand il se connecte : posts de ses connexions, articles partagés, etc.

### Ce qui existe déjà dans le repo

- `CompanyPostsScraper` — scrape les posts d'une page entreprise
- `BrowserManager` — gestion de session Playwright réutilisable
- Modèle `Post` — structure de données pour un post

### Ce qu'il faut ajouter

Un `FeedScraper` calqué sur `CompanyPostsScraper` qui :
1. Navigue sur `https://www.linkedin.com/feed/`
2. Scrolle N fois pour charger les posts
3. Parse le DOM pour extraire : auteur, texte, date, reactions, comments
4. Filtre le bruit : publicités, suggestions "Vous connaissez peut-être...", posts sponsorisés
5. Retourne une liste de `Post`

## Complexité anticipée

### Identique à CompanyPostsScraper
- Session Playwright réutilisée
- Infinite scroll avec `page.evaluate("window.scrollBy(...)")`

### Spécifique au feed
- **Bruit dans le DOM** : le feed mélange posts réels, pubs, suggestions → filtrage nécessaire
- **Sélecteurs CSS instables** : LinkedIn obfusque ses class names, ils peuvent changer
- **Anti-bot** : LinkedIn est légèrement plus vigilant sur le feed que sur les pages publiques

## Prochaines étapes

1. Lire le code de `CompanyPostsScraper` pour comprendre le pattern exact
2. Inspecter le DOM du feed LinkedIn pour identifier les sélecteurs stables
3. Implémenter `FeedScraper` sur le même modèle
4. Tester avec différents comptes et volumes de posts

## Liens

- Repo original : https://github.com/joeyism/linkedin_scraper
- Ce fork : https://github.com/vinzlac/linkedin_scraper
- Projet MCP LinkedIn associé : https://github.com/vinzlac/linkedin-mcp (contexte origine)
