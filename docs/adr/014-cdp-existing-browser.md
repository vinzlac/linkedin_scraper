# ADR-014 : Connexion CDP à un navigateur existant

## Status

Accepted

## Context

Dans le contexte d'un serveur MCP tournant sur un desktop (Claude Desktop sur macOS ou Windows), Playwright lance par défaut un **nouveau Chromium** à chaque démarrage du serveur. Sur desktop, cela crée une fenêtre Chromium supplémentaire visible.

Une alternative existe : **Chrome DevTools Protocol (CDP)**. Si l'utilisateur a déjà Chrome ouvert (avec son compte LinkedIn actif), Playwright peut s'y connecter directement via CDP plutôt que de lancer un nouveau navigateur.

```python
# Connexion à un Chrome existant
playwright.chromium.connect_over_cdp("http://localhost:9222")
```

Chrome doit être lancé avec le port de debug activé :
```bash
# macOS
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222

# Linux
google-chrome --remote-debugging-port=9222
```

## Decision

Documenter et supporter l'approche CDP comme **option alternative** pour les usages desktop, sans en faire le mode par défaut. Le mode Playwright avec `linkedin_session.json` reste le mode par défaut (plus portable, fonctionne sur serveur).

**Comparatif des deux modes :**

| | Playwright (défaut) | CDP (existant) |
|---|---|---|
| Setup | `linkedin_session.json` | Chrome lancé avec `--remote-debugging-port` |
| Fenêtre visible | Oui (desktop) / Non (Linux+Xvfb) | Chrome existant de l'utilisateur |
| Fingerprint | Bon | Parfait (vrai Chrome avec plugins réels) |
| Session expire | À renouveler via `just session` | Jamais (utilisateur déjà connecté) |
| Linux serveur | Oui (avec Xvfb) | Non (pas de Chrome ouvert) |
| Idéal pour | Serveur / CI | Desktop (Claude Desktop) |

## Consequences

**Avantages de CDP :**
- Fingerprint navigateur parfait (vrai Chrome de l'utilisateur, ses vraies fonts, ses vrais plugins)
- Pas de fichier de session à gérer
- Pas de fenêtre supplémentaire
- Utilisateur toujours connecté à LinkedIn dans son Chrome habituel

**Inconvénients de CDP :**
- Nécessite que l'utilisateur lance Chrome avec un flag spécifique
- Expose le port CDP localement (risque sécurité si non protégé)
- Ne fonctionne pas sur serveur distant (pas de Chrome ouvert)
- Si Chrome est fermé, le scraper perd la connexion
