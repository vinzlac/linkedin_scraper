# ADR-021 : Envoi de message via l'API Voyager `createMessage`

## Status

Accepted — 2026-10-10

## Context

Depuis le 2026-10-08, `send_message` échoue en production avec `Message compose editor not found` : le navigateur partagé (CDP, ADR-017) ne voit plus la zone de saisie du fil, alors que le même sélecteur la trouve dans un Chrome interactif. L'envoi dépendait de toute la chaîne d'affichage (chargement du fil, zone de saisie, Entrée, bulle sortante pour confirmer).

## Decision

`send_message` appelle directement l'action REST que la web app utilise elle-même :
`POST https://www.linkedin.com/voyager/api/voyagerMessagingDashMessengerMessages?action=createMessage`, via `fetch` exécuté dans la page connectée (cookies de session, `csrf-token` = cookie `JSESSIONID`, `x-restli-protocol-version: 2.0.0`). Corps capturé le 2026-10-09 :

    {"message": {"body": {"attributes": [], "text": "…"}, "renderContentUnions": [],
                 "conversationUrn": "urn:li:msg_conversation:(urn:li:fsd_profile:<moi>,<thread id>)",
                 "originToken": "<uuid4>"},
     "mailboxUrn": "urn:li:fsd_profile:<moi>", "trackingId": "<16 octets>",
     "dedupeByClientGeneratedToken": false}

L'id `<moi>` est lu par `GET /voyager/api/me` (même mécanique, sans DOM) ; repli sur la capture `messengerConversations` de `/messaging/` si cette lecture échoue.

Succès = HTTP 200 et `value.entityUrn` présent (avec notre `originToken` quand LinkedIn le renvoie). Le chemin DOM (saisie + Entrée + bulle) est supprimé, sans repli.

## Consequences

- Plus de dépendance au rendu du fil ni aux sélecteurs de la zone de saisie ; succès confirmé par le serveur.
- Un seul appel par invocation, pas de retry interne (risque de double envoi). Une erreur après un HTTP 200 dit « ne pas rejouer » ; une erreur de page pendant le POST dit « envoi incertain, ne pas rejouer sans vérifier le fil ».
- Endpoint interne non documenté : un changement de LinkedIn se verra comme une erreur HTTP explicite (`ScrapingError` avec le code).
- Même catégorie de risque CGU que le scraping existant.
