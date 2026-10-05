# Phase 2 architecture review

Review of the Phase 1 generation path against a target of 60–70 tables, millions to tens of millions of rows, and a later path toward 100M rows, Parquet, and parallel DAG execution. This document does not change the implementation. Phase 2 (medallion layers) should not start until the generation currency below is accepted, because a medallion runner that only calls today's `iter_batches` will copy the same memory shape into Bronze, Silver, and Gold.

Figures below are engineering estimates from object layout, not measurements. The benchmark plan is how to replace them with numbers.

## A. Current scalability characteristics

`FakerForge.generate` cannot scale to 10M rows. It builds one Python dictionary per row, keeps every table, then copies every dictionary into `DatasetResult`.

`iter_batches` is the only path that can drop row data. It still calls `_row` once per row, and each call allocates two dictionaries (generation order, then output order). A caller that writes a batch and discards it bounds row retention to `batch_size`. That is necessary and not sufficient.

What remains live for the whole job:

- Every unique parent value, as a Python object, in a `KeyPool` list. Pools are not released after the last child finishes.
- A uniqueness `set` for every unique column, holding every non-null value seen in that table.
- For a unique integer column whose span is at most 1,000,000, `list(range(...))` before any row is drawn.
- For a unique foreign key, a second Python list copied from the parent pool for the whole child table.

A narrow 10-column table of 10M rows, fully materialized, is multiple gigabytes of dicts before Faker strings are counted. Streaming batches removes that table-sized copy. It does not remove per-cell Python calls or parent-key retention.

CPU is the other limit. Each cell is a scalar Faker call or a scalar `DistributionEngine.number` call. Ten million rows and ten columns is on the order of 100 million Python calls, plus a float allocation per numeric draw. That can finish, and it will not be a practical way to regenerate a 70-table enterprise model.

100M rows is not realistic on this row engine. Integer foreign-key indexes fit in memory as arrays. 100M dictionaries do not. 100M Faker `uuid4()` strings retained as a key pool do not.

What does scale today:

- The dependency graph. Seventy tables is a small graph. Topological order, cycle detection, and parallel levels are metadata.
- Schema objects. `Column` and `DatasetSchema` are tiny next to the rows.
- Plan mode. `FakerForge.plan` does not draw rows.

`generate` and `iter_batches` share `_row`, so a faster engine has to be a new batch producer. Changing `_row` in place would change seeded sequences.

## B. Bottlenecks

### Memory: Python objects that grow with row count

| Site | What is retained |
| --- | --- |
| `schema/generate.py` `_generate_table` | `list` of every row dict for the table |
| `schema/generate.py` `_generate_database` | every table, plus a Python list of every unique value |
| `schema/result.py` `DatasetResult.__init__` | a second dict per row (`dict(row)`) |
| `schema/result.py` `DatasetResult.frame` | a pandas copy when the property is read |
| `schema/result.py` `DatabaseResult` | every `DatasetResult`, and each result's `siblings` points at all of them |
| `generation/batch.py` `_iter_table_batches` | one `list[dict]` of `batch_size`; the previous list is droppable only if the caller drops the `Batch` |
| `generation/batch.py` `_record_keys` | every non-null unique value for every table, for the rest of the database run |
| `generation/keys.py` `KeyPool._values` | `list[Any]`. `as_list` returns that same list |
| `schema/generate.py` `_pools` | up to 1,000,000 Python ints for one unique integer column |
| `schema/generate.py` `seen` | a `set` of every unique value drawn, including UUIDs and strings |
| `schema/generate.py` `fk_pools` | `list(parent_keys[...])`, a full copy of each unique foreign-key parent for the child table |
| `schema/generate.py` `_row` | two dicts per row; the first is discarded after the row is reordered |
| `validation/dataset.py` `UniquenessCheck` | another dict of every unique value |
| `validation/dataset.py` `ForeignKeyCheck` | a `set` of every parent key, built from full parent row dicts |
| `validation/dataset.py` `TypeCheck`, `BoundsCheck`, `NullableCheck` | no extra dataset, but they require every row to still exist |

`KeyPool.sample` and `KeyPool.take` are not on the generation path. `_foreign_key` indexes the raw list and, for unique children, swap-pops the copied list.

Unique columns that are not foreign-key targets are still stored. A surrogate key that no child references costs a full Python list.

Parent pools outlive the last child. Nothing in the graph records the last consumer.

### CPU: per-row and per-cell Python

- `_generate_table` and `_iter_table_batches` loop `for _ in range(rows)`.
- `_row` loops columns and calls `_value`.
- `_dependency_date` rebuilds `{name: column}` on every dependent date cell.
- `_uniform_index` calls `DistributionEngine.number`, which returns one Python `float`, then truncates it to an index. One call per foreign key and per numeric cell.
- Null decisions call `forge.random.random()` once per nullable cell.
- Provider cells call Faker once per cell. Text, email, and `uuid4()` cannot be a tight numeric loop.
- Unique provider columns retry up to 100 draws and probe a `set`. At high occupancy this both slows down and fails.
- `DatasetResult` copies every row even when `iter_batches` already built the dict.
- Validation walks every cell in Python after the table exists. It cannot run as a streaming check unless the caller keeps the rows.

`_uniform_index` is exact for pool sizes up to 2^53 because every integer in that range is a Python float. Million-row pools are inside that range. The cost is the call, not the rounding.

### Repeated work before any row

`Project.generation_plan` parses the document twice: `validate_dependency_graph` calls `schema()`, then `generation_plan` calls `schema()` again. `DependencyGraph.from_database` sorts the same table edges the schema already sorted. That cost is irrelevant at 70 tables and should not be repeated once per batch. A generation run should parse and resolve providers once, then reuse the `DatabaseSchema` and the graph.

`iter_batches` on a mapping calls `DatabaseSchema.from_dict` once per call. That is acceptable. Calling `plan` and then `iter_batches(project.tables)` parses again. The streaming API should accept the already parsed schema.

## C. Proposed generation architecture

Keep three producers. They must not share one random stream.

1. **Compatibility producer.** `FakerForge.generate` and today's `iter_batches` keep calling `_row`. Seed sequences stay what 0.1 and Phase 1 tests lock. This producer is for tests, examples, and datasets that fit in memory.

2. **Columnar batch producer.** New method, not an overload that silently changes `generate`. It fills one batch of one table as named arrays, in column generation order. Independent numeric columns are vectorized. Faker-backed columns are filled with one provider call per value into a preallocated array. Derived columns read the source array. Foreign keys are integer indexes into a parent key store, resolved to key values only for the columns that the batch will emit.

3. **Sink.** A consumer takes one batch and drops it. Parquet is the first sink. `generate()` is the sink that collects batches into `DatasetResult`, and it remains documented as the in-memory API.

A table is either **sampled** (providers, distributions, keys) or **derived** (a transform of an upstream table or of its own batch stream). Bronze rows are sampled. Silver and Gold tables that only clean or aggregate must be derived producers. If every table is sampled, medallion layers cannot preserve lineage and will not fit in memory three times.

Column generation order is the unit of work inside a table, not the row. A date column that depends on another date in the same row is produced after that column, for the whole batch. That matches today's topological column order and removes the per-cell rebuild of the column map.

## D. Proposed memory model

Bound memory by what must outlive a batch, not by table cardinality.

Retained for the job:

- Parsed schema, graph, and execution plan. Small.
- One open writer per table currently being produced.
- Parent key stores that later tables still reference. Drop a store when the execution plan's last consumer has finished.
- For a unique foreign key, a mutable index of remaining parent positions. The key values stay in the parent store. Do not copy them into a second list of objects.

Retained for one batch:

- One columnar batch. After the sink writes it, only the key column of that batch is appended to the parent store, and only if some later table references it.
- Uniqueness state that cannot be expressed as a dense integer range. Prefer a bitset or a roaring structure for integer domains. For UUIDs generated as sequential or random 128-bit values, uniqueness can be structural (a counter, or a batch of distinct random values with a collision check) instead of a `set` of every string allocated so far.

Not retained:

- Row dictionaries.
- Full parent tables.
- Sibling tables inside a result object.
- A pandas frame unless the caller asks for one on a batch that already fits in memory.
- Unique columns that are not referenced and are not required for a streaming uniqueness check. Sequential integer primary keys need a counter, not a list of the integers.

`DatasetResult` stays the small-data container. It is not the large-data container. A large run returns a manifest: paths, row counts, schema, and key-store summaries.

## E. Proposed batch model

Today's `Batch` is `table: str` and `rows: list[dict]`. Keep that class for `iter_batches` so Phase 1 callers keep working.

Add a columnar batch as the streaming currency:

- `table`
- `start_row` (offset in the table, so a batch is addressable without holding earlier batches)
- columns as Arrow arrays, or as NumPy arrays when Arrow is not installed
- a null mask per column
- the parent-key indexes for foreign keys, separate from the resolved key values, so a sink can write keys without the generator building dicts

Default batch size should be large enough for Arrow and Parquet row groups (on the order of 65,536 or 100,000 rows), not 1,000. The Phase 1 default of 1,000 stays on `iter_batches` so existing callers do not change chunking. The columnar API takes an explicit `batch_size`.

The producer yields one batch and does not append it to a list. The database loop is unchanged in order: finish every batch of a parent before the first batch of a child, because the child's key store must be complete for uniform sampling. That is a real barrier. Streaming does not mean interleaving a child with an unfinished parent.

Zero-row tables yield nothing and still publish an empty key store so children fail with the current "refusing to invent a foreign key" rule.

## F. Proposed key-management model

`KeyPool` as `list[Any]` is the correct Phase 1 isolation point and the wrong store for millions of keys.

Split keys by representation:

- **Dense integer surrogate.** Store `offset` and `count`, or a NumPy `int64` range. Sampling draws an index. The key value is `offset + index`. Memory is O(1) until a non-dense subset remains.
- **Arbitrary parent values that must be reproduced** (UUID strings, business keys). Store them once in a fixed-width array: 16 bytes for UUID, dictionary-encoded Arrow for low-cardinality strings. Sample by index. Resolve a batch of indexes with one array take.
- **Unique child.** Swap-pop an index array, not a copy of the values. When the parent is a dense range, shuffle or draw indexes without building `list(range(n))` as Python ints. The existing cap of 1,000,000 materialized ints should not grow with row count.
- **Non-unique child.** Read-only view of the parent store. Many children share it. No per-child copy.

Only columns that appear as `references` targets are appended to a store. The graph already has those edges. The execution plan lists them so `_record_keys` stops keeping every unique column.

Release rule: a store lives until every table that references it has been generated. The plan computes that from reference edges. After release, the process no longer holds the parent keys. Parquet already has the column.

Empty store behavior stays a hard error. Sampling must not invent a key.

`as_list()` exposes the live Python list. A later store should not pretend to be that list. Keep `KeyPool` for the compatibility producer. The columnar producer uses a new store type with `take_indices(count) -> ndarray` and `resolve(indices) -> array`.

## G. Proposed Arrow, NumPy, and Polars integration

NumPy is already an optional distribution backend, and it does not match the standard-library series. Leave that split alone on `FakerForge.number` and on `generate`.

Use NumPy inside the columnar producer only:

- uniform, normal, and log-normal fills for a whole column
- integer primary keys
- foreign-key index draws
- null masks as boolean arrays

Those draws use a generator seeded for that column and batch, not the compatibility engine's scalar stream. Document the split. Do not route `generate` through it.

PyArrow is the batch and file format, behind an optional extra. The producer can build a `RecordBatch` from NumPy buffers with minimal copy. Parquet writes that batch. Arrow is not required to import FakerForge. If it is missing, the columnar API raises an install error. `generate` and `iter_batches` keep working.

Polars is a reasonable optional reader for users who want to scan output Parquet. It should not be the internal representation. Pandas stays the optional view on `DatasetResult.frame` for small results. Neither library should be the place where foreign keys are resolved.

Faker stays a per-value provider for text and domain methods. A Faker column in a columnar batch is still a Python loop, writing into an Arrow array or an object buffer that is sealed at the end of the batch. That loop is isolated to columns that are actually Faker-backed. Numeric and key columns skip it.

## H. Proposed streaming model

One generation run:

1. Parse the project once into `DatabaseSchema`.
2. Build one `DependencyGraph` and one execution plan. Resolve providers once per table.
3. For each table in `graph.order` (the stable order, not a flattening of levels that would change schedule):
   - open the sink
   - for each batch, generate columns, yield one batch, let the sink write, append referenced key columns to the store, drop the batch
   - close the sink
   - drop key stores that have no remaining consumers
4. Return a manifest.

`iter_batches` remains the dict-batch iterator. The streaming method is separate, for example `iter_arrow_batches`, and a `write_parquet` helper owns the writer so callers do not have to.

Parquet integration, when that phase arrives:

- one dataset per table, writer created at the first batch and closed at the last
- `write_batch` per yielded batch, so row-group size follows `batch_size`
- compression and schema declared up front from the column types
- partition columns are fields already in the batch, written by the dataset writer, not by regrouping a full table in memory
- no row-wise `INSERT`
- foreign keys are values in the batch, already resolved from indexes; the key store is not re-read from Parquet during the child pass unless a resume/checkpoint design explicitly reloads them

Validation of a large run is a pass over the sink, or checks computed while the batch is alive (null count, batch uniqueness, key-index in range). `DatasetResult.validate` stays for the in-memory API. It should not be the 10M-row checker, because it requires the dicts it is checking.

Checkpointing later stores the manifest, the next table name, and the key stores still needed. It should not require regenerating finished Parquet files. That is why key stores must be reloadable from the written key column or from a compact sidecar. Do not design the store as an unreproducible Python list with no on-disk form.

## I. Proposed future parallel execution model

`DependencyGraph.levels` is a valid barrier schedule: every table in a level depends only on earlier levels. It is not yet an execution plan. Running a level on threads against one `Faker` instance and one `DistributionEngine` is not deterministic. Those generators are a single sequential stream. Thread interleaving changes draw order. Process forks copy the generator and then diverge without a defined seed.

Parallelism has to break the global stream on purpose.

- Derive a subseed from the project seed, the table id, and the batch index, with a documented hash. A batch does not consume a parent's generator.
- Workers generate batches of tables in the same level only. The next level starts after the level's key stores are published.
- Merge in declaration order within the level, which is the order already stored in each level tuple. Completion order must not become file order.
- Key-store publication is the synchronization point. A child never samples a partial parent unless the relationship is defined as a stream (it is not, for uniform foreign keys over the full parent).
- Document that parallel runs match each other when subseeds and merge order match, and that they do not match `generate()`'s single stream. Do not change `generate()` to subseeds in a minor release.

Within a table, column-wise generation is ordinary sequential code over arrays. That is the first speedup. Cross-table parallelism waits until key stores are arrays that can be handed to another process without copying a `list` of strings, and until tests show single-process columnar output is stable.

The graph does not yet say which columns a worker must return. A worker that returns a full table of dicts will erase the memory bound. The contract is: return key columns and write the rest to the sink inside the worker, or return only Arrow batches.

## J. Migration strategy

Do this before medallion execution, as the generation substrate Phase 2 will call.

1. Add an execution plan computed once from an existing `DatabaseSchema` and `DependencyGraph`. No behavior change. `plan()` can attach it without changing current fields.
2. Add the columnar batch type and producer behind a new method. `generate` and `iter_batches` stay on `_row`.
3. Add key stores for integer surrogates and for fixed-width values. `KeyPool` stays on the compatibility path.
4. Add a Parquet sink that writes columnar batches and drops them. Still not the default `generate` return type.
5. Teach the execution plan which key columns to retain and when to drop them.
6. Only then implement Bronze, Silver, and Gold as table producers on top of the same batch loop. Silver transforms read upstream batches or upstream Parquet. They do not call Faker a second time for columns that are copies or casts.

Phase 2 medallion metadata (layer names, layer edges) can be designed in parallel with step 1. It should not grow a second row loop.

Repeated parsing ends when `Project` caches `schema()` and the graph. `generation_plan` uses the cache. Invalidation is replacing `tables`.

## K. Backward compatibility strategy

Locked, including seeded sequences:

- `FakerForge.generate(schema, rows=...)` returns `DatasetResult` or `DatabaseResult` and still uses `_row`.
- `iter_batches` still yields `Batch` with `.table` and `.rows` as `list[dict]`, default `batch_size` 1000, and still matches `generate` for the same seed.
- `KeyPool` list behavior stays for callers that use it directly.
- `SchemaError` and `GenerationError` keep their current bases.
- NumPy remains optional on the scalar distribution engine, and installing it still selects that engine's existing series. The columnar producer does not become the default just because NumPy is installed.
- Root exports stay `FakerForge` and `__version__`.

Safe additions:

- New methods, new batch type, optional `arrow` extra, new plan fields that old callers can ignore.
- `Project.schema()` caching, if the parsed result is identical.
- Execution metadata on the graph that does not change `order` or `levels`.

Breaking if done in place, so do not:

- Making `iter_batches` yield Arrow batches.
- Switching `generate` to per-table subseeds or to column-wise draws. The draw count and order would change, so tests that lock sequences would fail and existing users would see new rows.
- Replacing `DatasetResult.rows` with a lazy object.
- Making `KeyPool.as_list` return a NumPy array.
- Running parallel levels inside `generate` or `iter_batches`.

The unreleased Phase 1 streaming API can grow a sibling. It should not be redefined. A major version is the point at which `generate` could default to the columnar engine. Until then, large-scale entry points are new methods.

`DatasetResult` does force full materialization. That remains the contract for `generate`. Streaming callers use the new producer and never construct a `DatasetResult` for the full table.

## L. Benchmark plan

No benchmark claims without this harness. Do not put 10M rows in the default pytest run.

Cases, same schema, seeds, and batch size, NumPy explicitly on and off:

- 1K, 10K, 100K, and 1M rows. 10M is a manual profile, not CI.
- Narrow numeric table, no Faker.
- Faker string columns only.
- Parent of 1M integer keys and a child of 10M foreign keys.
- Parent of UUID keys at 100K and 1M, to expose object-list cost.
- Full `generate` versus dict `iter_batches` versus columnar batches, caller discarding each batch.
- Columnar batches written to Parquet, generation time and write time reported separately.

Record rows per second, peak resident memory, and bytes written. Peak memory is the scalability result. Rows per second without memory is not.

Compare implementations inside FakerForge only: scalar `_row`, columnar numeric columns, and index-based foreign keys. Repeat each case. Publish the schema, seed, batch size, Python version, and whether NumPy and PyArrow were installed.

Acceptance for the streaming substrate, before medallion work depends on it:

- A 1M-row numeric table streamed in batches has peak memory on the order of one batch plus the key store, not on the order of the full dict table. Measure this. Do not treat the estimate in this document as that result.
- Foreign keys in the child batch all exist in the parent store. An empty parent still errors.
- `generate` sequences in the existing tests stay unchanged.
- A second process with the same seed and the same columnar settings reproduces the Parquet contents. Parallel workers are out of scope for that check until subseeds exist.

## Execution metadata the graph still needs

`DependencyGraph` has nodes, edges, table `order`, parallel `levels`, and `cycle`. `GenerationPlan` has row counts, those groups, and a placeholder of 64 bytes per column. Neither object can drive a bounded run.

Add a frozen execution plan, computed once, that does not replace `order` or `levels`:

- table order and level index per table
- column generation order per table
- row count and batch count per table
- columns whose values must be retained, the referencing tables, and the last consumer after which the store is dropped
- columns that are vectorizable (integer, float, boolean, sequential key, null mask) versus provider-scalar
- subseed inputs (project seed, table name, batch index), recorded even while the compatibility producer ignores them
- a flag that the table is sampled or derived from an upstream table, so a later Silver table is not forced through Faker

`levels` stays the parallel barrier. The new fields are the memory and seeding contract. `export()` can include them. Generation must follow `order` until a parallel runner exists, because flattening levels is a different schedule from the current tie break when independent tables are mixed with dependents.

## What would block Bronze, Silver, and Gold

These current facts do not block layers: one flat table list, no layer attribute yet, self-references rejected by the schema parser, age-only `derived_from`. Layers can be a prefix on table ids and extra edges. Self-references and SCD can be added when the schema allows the edge the graph can already represent.

These choices would block a large medallion:

- Implementing Silver by calling `generate` again on a cleaned schema. That doubles the draw, drops lineage, and materializes another full dict table.
- Requiring `DatabaseResult` to hold Bronze and Silver and Gold at once.
- Treating `list[dict]` as the only batch the next phase can consume.
- Keeping every unique column in a Python list so each layer retains the previous layer's keys.
- Using one global RNG so a Silver transform cannot be replayed without replaying every Bronze cell draw before it.
- Parsing and resolving the project again inside every layer pass.

Phase 2 can introduce layer metadata and layer edges on the graph. The row producer for those layers should be the streaming substrate above, not another wrapper around `_row`.
