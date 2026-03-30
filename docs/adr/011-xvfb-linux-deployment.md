# ADR-011 : Xvfb pour le déploiement Linux sans interface graphique

## Status

Accepted

## Context

Le mode `headless=False` est obligatoire (ADR-002), mais les serveurs Linux de production n'ont généralement pas d'interface graphique (pas de serveur X11, pas de display). Lancer Chromium avec `headless=False` sans display provoque une erreur :

```
Error: Failed to launch chromium
...
[0324/...] Missing X server or $DISPLAY
```

Plusieurs solutions ont été évaluées :

1. **`headless=True`** — Bloqué par la détection anti-bot LinkedIn (ADR-002)
2. **`headless="new"`** — Chromium 112+ sans fenêtre OS, même binaire que headed. Potentiellement détectable à terme
3. **Xvfb (X Virtual Framebuffer)** — Crée un display virtuel. Chromium pense avoir un vrai écran
4. **Docker + image Playwright officielle** — Inclut Xvfb préconfiguré et toutes les dépendances système

## Decision

Recommander **Xvfb** comme solution de déploiement Linux, avec une recette `just` dédiée. L'image Docker officielle Playwright (`mcr.microsoft.com/playwright/python`) est l'alternative recommandée pour les déploiements containerisés.

```bash
# Installation
sudo apt install xvfb

# Usage direct
xvfb-run --server-args="-screen 0 1280x720x24" uv run python samples/scrape_feed.py 10

# Via just
just run-feed-xvfb 10
```

```just
# Justfile
run-feed-xvfb N="10":
    xvfb-run --server-args="-screen 0 1280x720x24" uv run python samples/scrape_feed.py {{ N }}
```

## Consequences

**Avantages :**
- Transparent pour LinkedIn : le navigateur rend vraiment le contenu (pas de mode headless détectable)
- Disponible sur toutes les distributions Linux (`apt install xvfb`)
- Standard dans les environnements CI/CD (GitHub Actions, CircleCI)
- Aucun changement de code nécessaire

**Inconvénients :**
- Dépendance système supplémentaire à installer
- Légèrement plus lourd qu'un vrai mode headless
- Sur Docker, préférer l'image officielle Playwright qui inclut Xvfb avec les bonnes fonts et codecs (fingerprint plus réaliste qu'un serveur minimal)
