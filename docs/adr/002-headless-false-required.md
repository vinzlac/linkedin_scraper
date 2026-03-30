# ADR-002 : headless=False obligatoire contre la détection anti-bot

## Status

Accepted

## Context

Playwright peut lancer Chromium en mode headless (sans fenêtre visible), ce qui est l'usage habituel pour les scripts d'automatisation. Cependant, LinkedIn implémente une détection multi-couches des navigateurs automatisés.

Signaux détectés par LinkedIn en mode headless classique (`headless=True`) :
- `navigator.webdriver = true`
- Absence de plugins audio/vidéo (`navigator.plugins.length === 0`)
- User-agent contenant "HeadlessChrome"
- Canvas fingerprint dégradé (pas de GPU)
- `window.chrome` absent ou incomplet
- Comportements WebGL anormaux

En pratique, les sessions en mode headless classique sont bloquées rapidement (CAPTCHA, checkpoint de sécurité, ou ban silencieux).

## Decision

Forcer `headless=False` dans tous les usages de production. Le navigateur est visible mais peut être rendu invisible via d'autres mécanismes selon l'environnement :

- **macOS/Windows desktop** : fenêtre Chromium en arrière-plan (acceptable)
- **Linux serveur sans GUI** : Xvfb (virtual framebuffer) — voir ADR-011
- **Docker** : image officielle Playwright avec Xvfb préconfiguré

Le mode `headless="new"` (Chromium 112+, même binaire qu'en mode normal sans fenêtre OS) est une alternative prometteuse mais son efficacité contre la détection LinkedIn n'est pas garantie à long terme.

## Consequences

**Avantages :**
- Pas de détection anti-bot sur les sessions testées
- Fingerprint navigateur identique à un vrai utilisateur

**Inconvénients :**
- Nécessite un display (réel ou virtuel)
- Plus lourd en ressources qu'un mode headless pur
- Complexité de déploiement sur serveurs Linux (Xvfb requis)
