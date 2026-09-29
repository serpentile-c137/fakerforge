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
    └── FakerForge.generate  validates order, then fills rows
            ├── derived fields and date dependencies
            ├── foreign keys sampled from parent rows
            └── DatasetResult / DatabaseResult
                    ├── frame is a pandas.DataFrame when pandas is installed
                    └── validate() runs DatasetCheck subclasses

Schema (Field...)
    └── Generator            calls provider methods on a FakerForge

Constraint subclasses
    └── Validator            checks a finished record against constraints
```

`DistributionEngine` keeps its own random stream so schema generation can sample numbers without consuming Faker provider draws. NumPy is optional.

Finance is the first built-in domain provider. Many-to-many relationships are still later work.
