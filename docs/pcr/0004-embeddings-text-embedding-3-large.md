# PCR-0004: Embeddings use text-embedding-3-large at 3072 dimensions

**Decision:** Every embedding, for ingestion and for queries, MUST use `text-embedding-3-large` at 3072 dimensions.

**Reason:** TODO(owner): name the alternative that was weighed and why it lost.

**Consequence:** Query and chunk vectors stay comparable, and the `vector(3072)` columns and match functions stay valid. Changing the model means re-embedding every chunk and migrating both chunk tables in one change.

**Date:** 2026-10-01
