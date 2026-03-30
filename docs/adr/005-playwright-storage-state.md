# ADR-005 : Playwright storage state pour la gestion de session

## Status

Accepted

## Context

LinkedIn nécessite une authentification. Plusieurs approches existent pour persister une session :

1. **Cookie `li_at` uniquement** — Le cookie de session principal de LinkedIn. Simple mais incomplet : certaines pages nécessitent aussi des cookies secondaires et le localStorage.
2. **Playwright storage state** — Snapshot complet de l'état du navigateur : tous les cookies + tout le localStorage. Sauvegardé en JSON via `context.storage_state()`.
3. **Credentials en clair** — Email/mot de passe dans un `.env`. Permet un login programmatique mais déclenche des CAPTCHAs fréquents et est bloqué si LinkedIn suspecte un bot.

## Decision

Utiliser le **Playwright storage state** (`linkedin_session.json`) comme mécanisme de persistance de session.

```python
# Sauvegarde
storage_state = await context.storage_state()
with open("linkedin_session.json", "w") as f:
    json.dump(storage_state, f)

# Chargement
context = await browser.new_context(storage_state="linkedin_session.json")
```

La création initiale de la session se fait via login manuel (`just session`) : le navigateur s'ouvre, l'utilisateur se connecte normalement (avec 2FA si activé), et la session est sauvegardée.

## Consequences

**Avantages :**
- Session complète (cookies + localStorage) — plus fiable que le cookie seul
- Durée de vie longue (plusieurs semaines à mois selon l'activité LinkedIn)
- Compatible avec 2FA (login manuel une fois, session réutilisée ensuite)
- Pas de credentials stockés en clair dans le code

**Inconvénients :**
- Fichier sensible (équivalent d'un mot de passe) — ne jamais commiter
- Renouvellement manuel nécessaire à l'expiration
- Lié à un compte utilisateur spécifique (pas de service account)
- Sur serveur distant, nécessite un transfert sécurisé du fichier (`scp`)
