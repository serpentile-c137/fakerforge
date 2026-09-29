# FakerForge

FakerForge is a Python framework for synthetic data, built on top of [Faker](https://faker.readthedocs.io/). It does not fork Faker. Custom providers are normal Faker providers, and every other Faker method stays available.

Requires Python 3.10 or newer.

## Install

```bash
pip install fakerforge
```

NumPy and pandas are optional:

```bash
pip install "fakerforge[numpy]"
pip install "fakerforge[pandas]"
```

## Quick start

```python
from fakerforge import FakerForge

fake = FakerForge(seed=42)

fake.name()
fake.email()
fake.address()
```

`FakerForge` forwards unknown attributes to its `faker.Faker` instance. `seed` calls `seed_instance`, so the seed applies only to that object. Built-in providers are registered with Faker's `add_provider` and read the same random generator.

## Finance

`FinanceProvider` is registered on every `FakerForge` instance.

```python
from fakerforge import FakerForge

fake = FakerForge(seed=42)

fake.credit_score()          # int, 300 through 850
fake.transaction_amount()    # Decimal quantized to cents, 1.00 through 10000.00
fake.account_number()        # 12-digit string

fake.credit_score(min_score=700, max_score=750)
fake.transaction_amount(min_amount=10, max_amount=25)
fake.account_number(length=8)
```

The same seed reproduces the same sequence. `min_score` and `max_score` are inclusive. Amount bounds are inclusive after rounding to cents.

## Distributions

`number` and `categorical` sample from a `DistributionEngine` created with the same seed as the `FakerForge` instance. That stream is separate from Faker provider calls, so a later schema generator can replay distribution draws without depending on how many names or emails were produced. `seed_instance` reseeds both streams.

NumPy is used when it is installed (`pip install fakerforge[numpy]`). Without NumPy, sampling uses the standard library. Each backend is deterministic for a given seed. They do not emit the same series.

```python
from fakerforge import FakerForge

fake = FakerForge(seed=42)

fake.number(distribution="uniform", min=0, max=1)
fake.number(distribution="normal", mean=50, std=10, min=18, max=80)
fake.number(distribution="lognormal", mean=0, std=0.25, min=0.5, max=3)
fake.categorical(values=["A", "B", "C"])
fake.categorical(values=["A", "B", "C"], weights=[0.6, 0.3, 0.1])
```

`min` and `max` on normal and log-normal draws are inclusive. A sample outside that interval is discarded and another sample is drawn. Values are not clipped to the boundary. If 1000 draws in a row miss the interval, `number` raises `DistributionError`.

Log-normal `mean` and `std` describe the underlying normal distribution, matching NumPy's `Generator.lognormal`. Samples are greater than zero. Uniform draws use the half-open interval `[min, max)`, except when `min == max`, which returns that value. Weights do not need to sum to 1.

## Schemas

`generate` validates a declarative schema, then builds rows. The return value is a dataset result. `rows` is the list of records. `frame` is a pandas DataFrame when pandas is installed (`pip install fakerforge[pandas]`). `validate()` checks the rows against the schema.

```python
from fakerforge import FakerForge

fake = FakerForge(seed=42)

schema = {
    "customer_id": {"type": "uuid", "unique": True},
    "name": {"provider": "person.name"},
    "age": {"type": "integer", "min": 18, "max": 80},
    "email": {"provider": "internet.email", "unique": True},
}

result = fake.generate(schema=schema, rows=1000)
report = result.validate()
```

Primitive types are `string`, `integer`, `float`, `boolean`, `uuid`, and `date`. Provider references use Faker's `provider.method` form, such as `person.name`. Integer bounds are inclusive. Float bounds use the half-open interval `[min, max)`. Omitted numeric bounds default to `0..100` for integers and `0.0..1.0` for floats.

`nullable` fields are `None` with probability `null_probability`, which defaults to `0.1`. Unique columns do not repeat non-null values. Nulls may repeat. If a unique value cannot be found, generation raises `GenerationError` instead of inserting a duplicate. Dates are drawn from 1990-01-01 through 2030-12-31 so a seed stays stable.

Invalid schemas raise `SchemaError` before any row is produced. `errors` lists every problem found in that pass.

### Derived and dependent fields

`derived_from` computes a field from an earlier one. A date source produces completed years as of 2030-12-31, so the result does not change with the calendar day. `depends_on` generates the named fields first. A date that depends on a date is drawn on or after that date. Cycles are rejected.

```python
schema = {
    "date_of_birth": {"provider": "date.date_of_birth"},
    "age": {"derived_from": "date_of_birth"},
    "start_date": {"type": "date"},
    "end_date": {"type": "date", "depends_on": "start_date"},
}
```

### Foreign keys

A relational schema maps each table to `fields` and `rows`. `references` copies a value from a unique parent column. Child rows are generated after the parent, so a foreign key is never invented. A unique foreign key uses each parent value at most once. Many-to-many relationships are not supported.

```python
schema = {
    "customers": {
        "rows": 10,
        "fields": {
            "customer_id": {"type": "uuid", "unique": True},
            "name": {"provider": "person.name"},
        },
    },
    "orders": {
        "rows": 40,
        "fields": {
            "order_id": {"type": "uuid", "unique": True},
            "customer_id": {"references": "customers.customer_id"},
        },
    },
}

tables = fake.generate(schema=schema)
report = tables.validate()
```

### Validation

`validate()` checks the generated rows against the schema that produced them. The report has a `passed` or `failed` status, the row count, the violation count, and violations grouped by field. Each violation has a human-readable message. A failed report is returned; it is not raised.

Built-in checks cover type, min/max, nullable, uniqueness, known provider output, foreign keys, and row count. Subclass `DatasetCheck` and pass instances as `extra` to add further data-quality checks:

```python
from fakerforge.validation import DatasetCheck, ValidationContext, Violation

class RejectPlaceholder(DatasetCheck):
    name = "placeholder"

    def run(self, context: ValidationContext) -> list[Violation]:
        return []

report = result.validate(extra=(RejectPlaceholder(),))
```

## Custom providers

Subclass `faker.providers.BaseProvider` and pass the class to `FakerForge` or `add_provider`. `ForgeProvider` is a thin subclass of that base, re-exported for convenience. Provider methods use Faker helpers such as `random_int` and `numerify`, which read the instance generator.

```python
from faker.providers import BaseProvider

from fakerforge import FakerForge
from fakerforge.generator import Generator
from fakerforge.schema import Field, Schema

class StatusProvider(BaseProvider):
    def status_code(self) -> str:
        return self.random_element(("new", "open", "closed"))

fake = FakerForge(seed=42, providers=[StatusProvider])
fake.status_code()

schema = Schema(
    fields=(
        Field("name", "name"),
        Field("email", "email"),
        Field("status", "status_code"),
    )
)
rows = Generator(fake).generate(schema, count=3)
```

The source distribution includes `examples/quickstart.py` and `docs/architecture.md`.

## This release

| Piece | What 0.1 provides |
| --- | --- |
| Providers | Built-in `FinanceProvider`, plus `add_provider` for custom `BaseProvider` subclasses |
| Constraints | `Constraint` base and `Validator` |
| Distributions | Uniform, normal, log-normal, and weighted categorical sampling |
| Schema | Declarative datasets via `FakerForge.generate` |
| Generation | Seeded rows, with a DataFrame when pandas is installed |
| Validation | Dataset checks on generated rows, plus per-field `Validator` |
| Reproducibility | Instance seeding |

Later releases can add more domain providers and many-to-many relationships.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check src tests examples
ruff format --check src tests examples
mypy
```
