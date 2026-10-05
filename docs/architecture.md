# Architecture

FakerForge 0.1 is a wrapper and a set of extension points. It imports Faker and does not vendor or patch it.

```text
FakerForge
    └── faker.Faker          attribute delegation, seed_instance, add_provider
            ├── FinanceProvider, a faker.providers.BaseProvider
            └── caller providers, also BaseProvider subclasses

DistributionEngine       seeded uniform, normal, log-normal, categorical
    └── FakerForge.number / FakerForge.categorical

DatasetSchema / DatabaseSchema
    └── DependencyGraph      stable topological order and parallel groups
    └── FakerForge.generate  validates order, then fills rows
            ├── derived fields and date dependencies
            ├── foreign keys sampled from parent rows
            └── DatasetResult / DatabaseResult
                    ├── frame is a pandas.DataFrame when pandas is installed
                    └── validate() runs DatasetCheck subclasses

FakerForge.load / plan   project document, no row draws
FakerForge.iter_batches  same row function, fixed-size chunks

Schema (Field...)
    └── Generator            calls provider methods on a FakerForge

Constraint subclasses
    └── Validator            checks a finished record against constraints
```

`DistributionEngine` keeps its own random stream so schema generation can sample numbers without consuming Faker provider draws. NumPy is optional. Each backend is deterministic, and the two backends do not emit the same series.

`FakerForge.load` reads a project document (`project.name`, optional `project.seed`, and `tables`). `FakerForge.plan` checks providers and dependencies and returns generation order, row counts, and parallel groups. It does not draw rows. `estimated_bytes_per_row` is a placeholder of 64 bytes per column.

`FakerForge.iter_batches` yields fixed-size chunks through the same row function as `generate`. `generate` still materializes every row. `DependencyGraph` is the topological sort used by declarative schemas.

Finance is the first built-in domain provider. Many-to-many relationships are still later work. The roadmap is in `ARCHITECTURE_AUDIT.md`.
