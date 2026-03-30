# ADR-015 : Installation editable locale plutôt que publication PyPI

## Status

Accepted

## Context

Pour que `linkedin-mcp` utilise `linkedin_scraper` comme librairie, plusieurs options existent :

1. **Publication PyPI** — nécessite un compte PyPI, un token, et une release à chaque changement
2. **Référence GitHub** — nécessite de pusher chaque modification avant qu'elle soit visible
3. **Installation editable locale** — référence directement le dossier source local via `uv add --editable`

Les deux projets sont développés en parallèle sur la même machine. Publier sur PyPI ou pousser sur GitHub à chaque itération serait un frein majeur au développement.

## Decision

Utiliser **`uv add --editable`** pour référencer `linkedin_scraper` depuis `linkedin-mcp` en local. La publication PyPI est reportée à une phase ultérieure (distribution à d'autres utilisateurs).

```bash
# Depuis le dossier linkedin-mcp
uv add --editable ../linkedin_scraper
```

Cela ajoute dans `pyproject.toml` de `linkedin-mcp` :

```toml
dependencies = [
    "linkedin_scraper @ file:///chemin/absolu/vers/linkedin_scraper",
]
```

En mode editable, toute modification dans `linkedin_scraper/` est immédiatement visible dans `linkedin-mcp` sans réinstaller — le package pointe directement sur les sources.

## Consequences

**Avantages :**
- Cycle de développement immédiat : modifier `linkedin_scraper` → visible dans `linkedin-mcp` instantanément
- Pas de compte PyPI requis
- Pas de push GitHub requis entre chaque itération
- `uv.lock` capture le chemin exact pour reproductibilité sur la même machine

**Inconvénients :**
- Le chemin absolu dans `pyproject.toml` est spécifique à la machine locale
- Ne fonctionne pas pour distribuer à d'autres développeurs (ils n'ont pas le même chemin)
- `uv.lock` avec une dépendance locale ne peut pas être réutilisé tel quel sur une autre machine

**Quand passer à PyPI :**
- Quand d'autres développeurs doivent utiliser la lib
- Quand `linkedin-mcp` est déployé sur un serveur distant sans accès au dossier source
