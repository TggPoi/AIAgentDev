---
name: graphrag-cypher-generation
description: Use this skill when the user asks to generate, review, explain, debug, or secure Neo4j Cypher queries or GraphRAG workflows, especially natural-language-to-Cypher tasks.
---

## Purpose

Generate and review safe, correct Cypher queries for GraphRAG-style knowledge graph retrieval.

## Core rule

Cypher is not SQL. It describes the graph pattern to match:

```cypher
(knownNode)-[:RELATION]->(targetNode)
```

For every user question, translate natural language into a graph path.

## Standard reasoning workflow

1. Identify the known entity.
2. Identify the known entity's label.
3. Identify the target entity.
4. Identify the target entity's label.
5. Determine the relationship path.
6. Check relationship direction.
7. Generate a read-only Cypher query.
8. Return clear aliases with `AS`.

## Tutorial milk-tea schema

Use this schema when the user is working with the Chapter 28 tutorial:

Labels:
- `Product`: milk tea product
- `Ingredient`: ingredient
- `Type`: milk tea type
- `Method`: preparation method
- `People`: suitable people group

Relationships and directions:
- `(Product)-[:属于]->(Type)`
- `(Product)-[:包含]->(Ingredient)`
- `(Product)-[:适合]->(People)`
- `(Ingredient)-[:使用]->(Method)`

Never reverse these relationship meanings.

## Common query templates

### Product ingredients

```cypher
MATCH (p:Product {name:$productName})-[:包含]->(i:Ingredient)
RETURN p.name AS product, collect(i.name) AS ingredients
```

### Product suitable people

```cypher
MATCH (p:Product {name:$productName})-[:适合]->(people:People)
RETURN p.name AS product, collect(people.name) AS suitablePeople
```

### Products under a type

```cypher
MATCH (t:Type {name:$typeName})<-[:属于]-(p:Product)
RETURN t.name AS type, collect(p.name) AS products
```

### Ingredients of products under a type

```cypher
MATCH (t:Type {name:$typeName})<-[:属于]-(p:Product)-[:包含]->(i:Ingredient)
RETURN t.name AS type, p.name AS product, collect(i.name) AS ingredients
```

### Methods used by ingredients in a product

```cypher
MATCH (p:Product {name:$productName})-[:包含]->(i:Ingredient)-[:使用]->(m:Method)
RETURN p.name AS product, i.name AS ingredient, m.name AS method
```

## Safety rules

For GraphRAG question answering, generate only read-only Cypher.

Do not generate:
- `CREATE`
- `MERGE`
- `SET`
- `DELETE`
- `DETACH DELETE`
- `DROP`
- `REMOVE`

If the user explicitly asks for data modification, warn that this is not a read-only GraphRAG query and ask for confirmation before generating write Cypher.

## Review checklist

When reviewing a Cypher query, check:

1. Are labels correct?
2. Are relationship types correct?
3. Is the relationship direction correct?
4. Is the known entity matched with the correct label?
5. Does `RETURN` match the user's target?
6. Should results use `DISTINCT` or `collect()`?
7. Is the query read-only?
8. Are parameters used instead of string interpolation?
