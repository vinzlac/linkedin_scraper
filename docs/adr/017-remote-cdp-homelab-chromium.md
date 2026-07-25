# ADR-017 : Connexion CDP au Chromium partagé du homelab (k3s-homelab / OpenClaw Phase 10)

## Status

Accepted

## Context

ADR-002 impose `headless=False` pour éviter la détection anti-bot LinkedIn, mais cela ouvre une fenêtre Chromium visible sur le poste desktop (macOS) à chaque scrape/like/repost — gênant pour un usage quotidien.

ADR-014 documentait déjà l'idée de se connecter en CDP à un Chrome *local* déjà ouvert par l'utilisateur, mais ne résout pas le problème : il faut toujours qu'une fenêtre Chrome existe quelque part sur la machine locale.

Le repo `k3s-homelab` héberge déjà, indépendamment de ce projet, un Chromium **headless mais anti-détection** (`--use-gl=egl`, `--disable-blink-features=AutomationControlled`, profil persistant) exposé en **CDP sur le port 9222**, construit pour OpenClaw (Phase 10 du master plan) mais explicitement documenté comme « réutilisable par d'autres services du cluster (ex. MCP scraping) ». Deux variantes coexistent :

- **10A — hôte** (`geekom-as6`, systemd `chromium-cdp.service`) : `http://192.168.1.153:9222` (LAN) / `ws://chromium-cdp-host.openclaw.svc:9222` (in-cluster)
- **10B — pod** (`Deployment` k3s) : `ws://chromium-cdp-pod.openclaw.svc:9222` (in-cluster uniquement)

Testé en direct (2026-07-22) : la variante 10A répond depuis le Mac sur le LAN, une session LinkedIn s'y charge et navigue normalement.

**Point trouvé en testant** : malgré `--headless=new` et `--disable-blink-features=AutomationControlled`, le user-agent par défaut de Chromium contient encore littéralement `HeadlessChrome` — un signal trivialement détectable, resté non corrigé jusqu'ici car sans doute inoffensif pour l'usage OpenClaw/Telegram d'origine.

## Decision

1. **`BrowserManager` supporte un mode CDP** (`cdp_url` optionnel) : quand fourni, `start()` appelle `chromium.connect_over_cdp(cdp_url)` au lieu de `chromium.launch(...)`. Un contexte Playwright isolé est ensuite créé par-dessus (comme en mode local), donc `linkedin_session.json` reste le mécanisme de session unique quel que soit le mode — pas de dépendance au profil partagé du Chromium distant, pas de risque de collision avec la navigation d'OpenClaw dans ce même Chromium.
2. **`close()` ne tue jamais le Chromium distant** : `Browser.close()` sur une connexion CDP déconnecte le client Playwright, il ne termine pas le process serveur (documenté côté Playwright) — vérifié en pratique : le pod `chromium-cdp-pod` restait `Running` après fermeture de notre session.
3. **Le `--user-agent` du Chromium distant est corrigé** pour retirer le token `HeadlessChrome` (remplacé par `Chrome`, version dérivée dynamiquement du binaire pour la variante hôte). Correctif côté `k3s-homelab` (`ansible/templates/chromium-cdp-wrap.sh.j2` et `kubernetes/openclaw/chromium-cdp-pod.yaml`), pas dans ce repo.
4. **`headless` local reste le défaut** (ADR-002) : `cdp_url` est une option explicite (`LINKEDIN_CDP_URL` côté `linkedin-mcp`), pas un remplacement automatique. Un utilisateur sans accès au homelab garde le mode local `headless=False` qui fonctionne déjà.

## Consequences

**Avantages :**
- Plus aucune fenêtre Chromium visible sur le Mac quand `LINKEDIN_CDP_URL` est configuré — le navigateur tourne entièrement sur `geekom-as6`.
- Réutilise une infrastructure déjà opérationnelle et maintenue (Ansible + GitOps ArgoCD), pas de nouveau service à faire vivre.
- Fingerprint anti-détection déjà travaillé pour cet usage précis (`--use-gl=egl`, `AutomationControlled` désactivé, maintenant aussi UA corrigé).

**Inconvénients :**
- Couplage à la disponibilité du homelab : si `geekom-as6` est éteint ou le service `chromium-cdp` arrêté, `LINKEDIN_CDP_URL` doit être vidée pour retomber en local (pas de fallback automatique implémenté — jugé plus simple et plus prévisible qu'un fallback silencieux).
- Chromium distant **partagé** avec OpenClaw : deux clients CDP simultanés (LinkedIn + OpenClaw) sur le même process navigateur. Chacun a son propre contexte Playwright isolé (pas de fuite de cookies), mais consomment les mêmes ressources CPU/RAM du host — à surveiller si les deux usages deviennent concurrents et fréquents.
- Nécessite d'être sur le même réseau que le homelab (LAN direct pour 10A, ou tunnel/VPN si accès distant) — pas utilisable depuis n'importe où sans exposition réseau supplémentaire.

**Hors scope de cet ADR** : exposition du serveur MCP `linkedin-mcp` lui-même sur une URL publique pour un déclenchement hors LAN (question distincte, voir échanges ultérieurs — nécessiterait son propre ADR côté authentification/exposition si mis en œuvre).
