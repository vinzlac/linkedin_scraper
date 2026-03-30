# ADR-006 : Pydantic pour les modèles de données

## Status

Accepted

## Context

Les données extraites du DOM LinkedIn sont non structurées (texte brut, HTML). Il faut les représenter sous forme d'objets Python typés. Deux approches principales :

1. **Dataclasses Python** — Standard library, pas de dépendance externe, validation basique
2. **Pydantic BaseModel** — Validation, sérialisation JSON native, support `Optional` élégant

La migration de Selenium vers Playwright (v3.0.0 du repo original) a inclus le passage aux modèles Pydantic.

## Decision

Utiliser **Pydantic v2** (`BaseModel`) pour tous les modèles de données scraped.

```python
class Post(BaseModel):
    linkedin_url: Optional[str] = None
    urn: Optional[str] = None
    author_name: Optional[str] = None
    text: Optional[str] = None
    reactions_count: Optional[int] = None
    image_urls: List[str] = Field(default_factory=list)
    video_url: Optional[str] = None
    article_url: Optional[str] = None
```

## Consequences

**Avantages :**
- Sérialisation JSON via `model.model_dump()` et `model.model_dump_json()` — indispensable pour l'intégration MCP
- Validation automatique des types (ex: `reactions_count` sera toujours `int` ou `None`, jamais une string)
- `Optional[X] = None` exprime clairement les champs non garantis
- Compatible avec les outils de type checking (mypy)
- `Field(default_factory=list)` évite les bugs de mutable defaults

**Inconvénients :**
- Dépendance externe (`pydantic>=2.0.0`)
- Pydantic v2 introduit des breaking changes par rapport à v1 (`model_dump()` vs `dict()`)
