# ADR-003 : page.evaluate() plutôt que les locators Playwright

## Status

Accepted

## Context

Playwright offre deux approches pour interagir avec le DOM :

1. **Locators** (`page.locator(".class-name")`) — sélecteurs CSS ou XPath, idiomatiques en Playwright
2. **page.evaluate()** — exécution de JavaScript arbitraire dans le contexte du navigateur

LinkedIn obfusque systématiquement ses class names CSS. Par exemple, un élément peut avoir une classe `feed-shared-update-v2__description-wrapper` un jour et `ember-1234-abc` le suivant. Ces classes changent à chaque déploiement LinkedIn, rendant les locators basés sur les classes extrêmement fragiles.

Même les sélecteurs "stables" de LinkedIn (data attributes, roles ARIA) sont insuffisants pour extraire des données structurées complexes comme un post de feed qui mélange auteur, date, texte, métriques, et médias.

## Decision

Utiliser `page.evaluate()` avec du JavaScript inline pour toute extraction de données complexe. Le JavaScript s'exécute dans le contexte du navigateur et peut traverser le DOM de manière arbitraire, en s'appuyant sur des ancres stables (voir ADR-004) plutôt que sur des class names.

```python
posts_data = await self.page.evaluate("""() => {
    // Extraction JS directe du DOM
    var repostBtns = Array.from(document.querySelectorAll("button"))
        .filter(b => (b.innerText || "").trim() === "Republier" || ...);
    // ...
}""")
```

## Consequences

**Avantages :**
- Résistant aux changements de class names LinkedIn
- Peut extraire des données complexes en une seule passe DOM (plus efficace)
- Logique d'extraction concentrée et testable indépendamment

**Inconvénients :**
- JavaScript inline dans du Python : moins lisible, pas de syntax highlighting
- Débogage plus difficile (erreurs JS remontées comme exceptions Python génériques)
- Nécessite une connaissance du DOM LinkedIn pour identifier les ancres stables
