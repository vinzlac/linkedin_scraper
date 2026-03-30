# ADR-004 : data-urn comme ancre stable pour l'identification des posts

## Status

Accepted

## Context

Le feed LinkedIn affiche une liste de posts, mais le DOM ne fournit pas de structure claire et stable pour délimiter un post. Les class names sont obfusqués (ADR-003). Il faut un moyen fiable de :
1. Identifier les limites de chaque post (quel élément DOM correspond à un post entier)
2. Extraire l'identifiant unique du post (pour la déduplication lors du scroll)

Deux approches ont été évaluées :

**Approche A — Bouton "Republier/Repost"** : chaque post a exactement un bouton Repost dans sa barre d'action. En remontant l'arbre DOM depuis ce bouton jusqu'au container parent qui n'en contient qu'un seul, on isole le post.

**Approche B — Attribut `data-urn`** : LinkedIn expose un attribut `data-urn="urn:li:activity:XXXXXX"` sur les éléments de post. C'est l'identifiant canonique LinkedIn d'un post (URN = Uniform Resource Name).

L'approche A a été implémentée en premier pour délimiter le container. L'approche B a été ajoutée ultérieurement comme source primaire d'extraction de l'URN, après avoir constaté que certains posts avaient `URL: None` car leur URN n'était pas extrait par les stratégies secondaires.

## Decision

Utiliser `data-urn` comme **stratégie 0 (prioritaire)** pour l'extraction de l'URN, avant toutes les autres stratégies (`componentkey`, `/posts/` links, `/feed/update/` links). L'approche bouton Repost reste utilisée pour délimiter le container du post.

```javascript
// Stratégie 0 : data-urn — ancre stable LinkedIn
var urnEls = el.querySelectorAll("[data-urn]");
for (var i = 0; i < urnEls.length && !urn; i++) {
    var m = (urnEls[i].getAttribute("data-urn") || "").match(/urn:li:activity:(\d+)/);
    if (m) urn = m[0];
}
```

Une fois l'URN `urn:li:activity:XXXXXX` extrait, le permalien est construit : `https://www.linkedin.com/feed/update/{urn}/`.

## Consequences

**Avantages :**
- `data-urn` est documenté dans CLAUDE.md comme "stable anchor" — LinkedIn le maintient car c'est leur système d'adressage interne
- Fournit à la fois l'identifiant unique ET la base du permalien
- Résout le problème de `URL: None` sur les posts sans lien `/posts/` ou `/feed/update/` dans le DOM

**Inconvénients :**
- `data-urn` peut ne pas être présent sur tous les types de posts (ex: posts sponsorisés, suggestions)
- Fallback nécessaire vers les autres stratégies pour les cas limites
