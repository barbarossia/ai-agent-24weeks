---
title: Vector field notes
tags: [postgres, retrieval]
---
# PostgreSQL
## Cosine retrieval
PostgreSQL pgvector stores vectors alongside source metadata. Cosine distance orders matching chunks.

## Updates
An explicit note update atomically replaces its old chunks and metadata in one transaction.
