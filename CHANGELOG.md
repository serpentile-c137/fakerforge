# Changelog

## 0.2.0 - 2026-10-05

- Add a dependency graph and use it for declarative schema order. Parallel groups are reported and execution stays single-threaded.
- Add `FakerForge.load` and `FakerForge.plan` for JSON projects, and for YAML when PyYAML is installed. Planning validates providers and dependencies and does not generate rows.
- Add `FakerForge.iter_batches`. Concatenating chunks matches `generate` for the same seed. `generate` still returns the full in-memory result.

## 0.1.0 - 2026-09-29

First public release. Requires Python 3.10 or newer.

- Add `FakerForge`, a seeded wrapper that delegates unknown attributes to `faker.Faker`.
- Add `ForgeProvider` as a subclass of Faker's `BaseProvider`.
- Add abstract `Constraint` and `Distribution` bases.
- Add `Field`, `Schema`, and a schema `Generator` that calls Faker provider methods.
- Add `Validator` for per-field constraint checks.
- Register `FinanceProvider` on every `FakerForge` instance through Faker's `BaseProvider` mechanism.
- Add a seeded `DistributionEngine` with uniform, normal, log-normal, and weighted categorical sampling.
- Add declarative schema generation with primitive types, Faker provider references, bounds, nulls, uniqueness, and optional pandas output.
- Add derived fields, dependent fields, and foreign keys that preserve referential integrity.
- Add dataset validation for types, bounds, nulls, uniqueness, provider output, foreign keys, and row counts.
