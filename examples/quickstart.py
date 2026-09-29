"""Generate a few seeded records with FakerForge."""

from fakerforge import FakerForge
from fakerforge.generator import Generator
from fakerforge.schema import Field, Schema


def main() -> None:
    fake = FakerForge(seed=42)
    print(fake.name())
    print(fake.email())
    print(fake.address())
    print(fake.credit_score())
    print(fake.transaction_amount())
    print(fake.account_number())
    print(fake.number(distribution="normal", mean=50, std=10, min=18, max=80))
    print(fake.categorical(values=["A", "B", "C"], weights=[0.6, 0.3, 0.1]))
    generated = fake.generate(
        schema={
            "customer_id": {"type": "uuid", "unique": True},
            "name": {"provider": "person.name"},
            "age": {"type": "integer", "min": 18, "max": 80},
            "email": {"provider": "internet.email", "unique": True},
        },
        rows=2,
    )
    print(generated.validate())

    schema = Schema(
        fields=(
            Field("name", "name"),
            Field("email", "email"),
            Field("address", "address"),
        )
    )
    rows = Generator(FakerForge(seed=42)).generate(schema, count=2)
    for row in rows:
        print(row)


if __name__ == "__main__":
    main()
