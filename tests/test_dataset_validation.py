"""Tests for validating generated datasets against their schema."""

from datetime import date, datetime
from decimal import Decimal

from fakerforge import FakerForge
from fakerforge.schema import (
    DatabaseResult,
    DatabaseSchema,
    DatasetResult,
    DatasetSchema,
)
from fakerforge.validation import DatasetCheck, ValidationContext, Violation

CUSTOMERS = {
    "customer_id": {"type": "uuid", "unique": True},
    "name": {"provider": "person.name"},
    "age": {"type": "integer", "min": 18, "max": 80},
    "email": {"provider": "internet.email", "unique": True},
}

RELATIONAL = {
    "orders": {
        "rows": 10,
        "fields": {
            "order_id": {"type": "integer", "min": 1, "max": 10, "unique": True},
            "customer_id": {"references": "customers.customer_id"},
        },
    },
    "customers": {
        "rows": 4,
        "fields": {
            "customer_id": {"type": "integer", "min": 1, "max": 4, "unique": True},
            "name": {"provider": "person.name"},
        },
    },
}


class FlagValue(DatasetCheck):
    """Flag one exact value so tests can add a future-style check."""

    name = "flag"

    def __init__(self, value: object) -> None:
        self.value = value

    def run(self, context: ValidationContext) -> list[Violation]:
        found: list[Violation] = []
        for table in context.focus:
            for index, row in enumerate(context.tables[table]):
                for key, cell in row.items():
                    if cell != self.value:
                        continue
                    field = key if table == "" else f"{table}.{key}"
                    found.append(
                        Violation(
                            field=field,
                            check=self.name,
                            row=index,
                            message=f"row {index}: field {field!r}: flagged {cell!r}",
                        )
                    )
        return found


def _linked(document: dict) -> tuple[DatabaseSchema, dict[str, DatasetSchema]]:
    database = DatabaseSchema.from_dict(document)
    return database, {table.name: table.dataset for table in database.tables}


def _result(
    schema: dict,
    rows: list[dict],
    *,
    expected_rows: int | None = None,
) -> DatasetResult:
    return DatasetResult(
        rows,
        DatasetSchema.from_dict(schema),
        expected_rows=len(rows) if expected_rows is None else expected_rows,
    )


def test_generated_dataset_passes() -> None:
    result = FakerForge(seed=42).generate(schema=CUSTOMERS, rows=100)
    report = result.validate()
    assert report.status == "passed"
    assert report.rows == 100
    assert report.violation_count == 0
    assert report.by_field == {}
    assert str(report) == "passed: 100 rows, 0 violations"


def test_generated_relational_dataset_passes() -> None:
    result = FakerForge(seed=11).generate(schema=RELATIONAL)
    report = result.validate()
    assert report.status == "passed"
    assert report.rows == 14
    assert report.table_rows == {"orders": 10, "customers": 4}
    assert result["orders"].validate().status == "passed"
    assert result["customers"].validate().status == "passed"


def test_generated_provider_output_passes() -> None:
    schema = {
        "score": {"provider": "base.credit_score"},
        "amount": {"provider": "base.transaction_amount"},
        "account": {"provider": "base.account_number"},
        "born": {"provider": "date.date_of_birth"},
        "active": {"provider": "python.pybool"},
    }
    report = FakerForge(seed=3).generate(schema=schema, rows=20).validate()
    assert report.status == "passed"
    assert report.violation_count == 0


def test_type_violations_name_the_field_and_row() -> None:
    schema = {
        "label": {"type": "string"},
        "age": {"type": "integer"},
        "score": {"type": "float"},
        "active": {"type": "boolean"},
        "public_id": {"type": "uuid"},
        "born": {"type": "date"},
    }
    result = _result(
        schema,
        [
            {
                "label": 1,
                "age": True,
                "score": float("nan"),
                "active": 1,
                "public_id": "not-a-uuid",
                "born": datetime(2020, 1, 1),
            }
        ],
    )
    report = result.validate()
    assert report.status == "failed"
    assert report.rows == 1
    messages = {item.field: item.message for item in report.violations}
    assert "expected string, got int" in messages["label"]
    assert "expected integer, got bool" in messages["age"]
    assert "expected a finite float, got nan" in messages["score"]
    assert "expected boolean, got int" in messages["active"]
    assert "expected uuid, got str" in messages["public_id"]
    assert "expected date, got datetime" in messages["born"]
    assert all(item.row == 0 and item.check == "type" for item in report.violations)
    assert "row 0: field 'age'" in str(report)


def test_bounds_are_inclusive_for_integers_and_half_open_for_floats() -> None:
    integers = _result(
        {"age": {"type": "integer", "min": 18, "max": 80}},
        [{"age": 18}, {"age": 80}, {"age": 17}, {"age": 81}],
    )
    integer_rows = [item.row for item in integers.validate().by_field["age"]]
    assert integer_rows == [2, 3]
    assert "outside 18..80" in integers.validate().by_field["age"][0].message

    floats = _result(
        {"score": {"type": "float", "min": 0, "max": 1}},
        [{"score": 0.0}, {"score": 1.0}],
    )
    float_report = floats.validate()
    assert float_report.violation_count == 1
    assert "not below 1" in float_report.by_field["score"][0].message

    point = _result(
        {"score": {"type": "float", "min": 2, "max": 2}},
        [{"score": 2.0}],
    )
    assert point.validate().status == "passed"


def test_wrong_type_skips_the_bounds_check() -> None:
    report = _result(
        {"age": {"type": "integer", "min": 18, "max": 80}},
        [{"age": "no"}],
    ).validate()
    assert [item.check for item in report.violations] == ["type"]


def test_nullable_rejects_nulls_and_missing_keys() -> None:
    report = _result(
        {"age": {"type": "integer"}, "note": {"type": "string", "nullable": True}},
        [{"note": None}, {"age": None, "note": "ok"}],
    ).validate()
    assert report.by_field["age"][0].message.endswith("value is missing")
    assert report.by_field["age"][1].message.endswith("null is not allowed")
    assert "note" not in report.by_field


def test_unique_values_may_repeat_only_when_null() -> None:
    report = _result(
        {"email": {"provider": "internet.email", "unique": True, "nullable": True}},
        [
            {"email": None},
            {"email": "a@example.com"},
            {"email": None},
            {"email": "a@example.com"},
        ],
    ).validate()
    assert report.violation_count == 1
    assert report.by_field["email"][0].row == 3
    assert "duplicate value 'a@example.com'" in report.by_field["email"][0].message
    assert "first seen at row 1" in report.by_field["email"][0].message


def test_known_provider_output_is_checked() -> None:
    schema = {
        "email": {"provider": "internet.email"},
        "name": {"provider": "person.name"},
        "born": {"provider": "date.date_of_birth"},
        "score": {"provider": "base.credit_score"},
        "amount": {"provider": "base.transaction_amount"},
        "account": {"provider": "base.account_number"},
        "token": {"provider": "same.token"},
    }
    report = _result(
        schema,
        [
            {
                "email": "not-an-email",
                "name": "",
                "born": datetime(2020, 1, 1),
                "score": True,
                "amount": 1.5,
                "account": "12a",
                "token": 1,
            }
        ],
    ).validate()
    assert "token" not in report.by_field
    assert "email" in report.by_field["email"][0].message
    assert report.by_field["name"][0].check == "provider"
    assert "expected a date" in report.by_field["born"][0].message
    assert "credit score" in report.by_field["score"][0].message
    assert "Decimal" in report.by_field["amount"][0].message
    assert "account number" in report.by_field["account"][0].message

    valid = _result(
        schema,
        [
            {
                "email": "a@example.com",
                "name": "Ada",
                "born": date(2020, 1, 1),
                "score": 700,
                "amount": Decimal("1.50"),
                "account": "0012",
                "token": 1,
            }
        ],
    )
    assert valid.validate().status == "passed"


def test_foreign_keys_must_exist_in_the_parent() -> None:
    _, tables = _linked(
        {
            "customers": {
                "rows": 1,
                "fields": {
                    "customer_id": {
                        "type": "integer",
                        "min": 1,
                        "max": 1,
                        "unique": True,
                    },
                },
            },
            "orders": {
                "rows": 2,
                "fields": {
                    "customer_id": {"references": "customers.customer_id"},
                },
            },
        }
    )
    customers = DatasetResult(
        [{"customer_id": 1}],
        tables["customers"],
        expected_rows=1,
        table_name="customers",
    )
    orders = DatasetResult(
        [{"customer_id": 9}, {"customer_id": 1}],
        tables["orders"],
        expected_rows=2,
        table_name="orders",
        siblings={"customers": customers},
    )
    report = orders.validate()
    assert report.violation_count == 1
    assert report.by_field["orders.customer_id"][0].row == 0
    assert "is not in customers.customer_id" in report.violations[0].message


def test_database_report_groups_foreign_keys_and_row_counts() -> None:
    parsed, tables = _linked(RELATIONAL)
    customers = DatasetResult(
        [{"customer_id": 1}],
        tables["customers"],
        expected_rows=2,
        table_name="customers",
    )
    orders = DatasetResult(
        [{"order_id": 1, "customer_id": 9}],
        tables["orders"],
        expected_rows=3,
        table_name="orders",
        siblings={"customers": customers},
    )
    customers.siblings = {"orders": orders}
    database = DatabaseResult(
        {"orders": orders, "customers": customers},
        parsed,
    )
    report = database.validate()
    assert report.status == "failed"
    assert report.rows == 2
    assert report.table_rows == {"orders": 1, "customers": 1}
    assert "orders.customer_id" in report.by_field
    assert "orders.rows" in report.by_field
    assert "customers.rows" in report.by_field
    assert "expected 3 rows, found 1" in report.by_field["orders.rows"][0].message
    text = str(report)
    assert text.startswith("failed: ")
    assert "violations across 2 rows" in text


def test_missing_parent_is_a_foreign_key_violation() -> None:
    _, tables = _linked(
        {
            "customers": {
                "rows": 1,
                "fields": {
                    "customer_id": {
                        "type": "integer",
                        "min": 1,
                        "max": 1,
                        "unique": True,
                    },
                },
            },
            "orders": {
                "rows": 1,
                "fields": {
                    "customer_id": {"references": "customers.customer_id"},
                },
            },
        }
    )
    report = DatasetResult(
        [{"customer_id": 1}],
        tables["orders"],
        expected_rows=1,
        table_name="orders",
    ).validate()
    assert report.by_field["orders.customer_id"][0].check == "foreign_key"
    message = report.violations[0].message
    assert "parent table 'customers' is not available" in message


def test_child_validation_does_not_check_unfocused_parent_rows() -> None:
    _, tables = _linked(
        {
            "customers": {
                "rows": 1,
                "fields": {
                    "customer_id": {
                        "type": "integer",
                        "min": 1,
                        "max": 1,
                        "unique": True,
                    },
                },
            },
            "orders": {
                "rows": 1,
                "fields": {
                    "customer_id": {"references": "customers.customer_id"},
                },
            },
        }
    )
    customers = DatasetResult(
        [{"customer_id": "bad"}],
        tables["customers"],
        expected_rows=5,
        table_name="customers",
    )
    orders = DatasetResult(
        [{"customer_id": "bad"}],
        tables["orders"],
        expected_rows=1,
        table_name="orders",
        siblings={"customers": customers},
    )
    report = orders.validate()
    assert report.status == "passed"
    parent = customers.validate()
    assert parent.by_field["customers.customer_id"][0].check == "type"
    assert "customers.rows" in parent.by_field


def test_nullable_foreign_key_may_be_null() -> None:
    _, tables = _linked(
        {
            "customers": {
                "rows": 1,
                "fields": {
                    "customer_id": {
                        "type": "integer",
                        "min": 1,
                        "max": 1,
                        "unique": True,
                    },
                },
            },
            "orders": {
                "rows": 1,
                "fields": {
                    "customer_id": {
                        "references": "customers.customer_id",
                        "nullable": True,
                    },
                },
            },
        }
    )
    customers = DatasetResult(
        [{"customer_id": 1}],
        tables["customers"],
        expected_rows=1,
        table_name="customers",
    )
    orders = DatasetResult(
        [{"customer_id": None}],
        tables["orders"],
        expected_rows=1,
        table_name="orders",
        siblings={"customers": customers},
    )
    assert orders.validate().status == "passed"


def test_row_count_is_reported_for_one_table() -> None:
    report = _result(
        {"age": {"type": "integer", "min": 18, "max": 80}},
        [{"age": 18}],
        expected_rows=4,
    ).validate()
    assert report.by_field["rows"][0].check == "row_count"
    assert report.by_field["rows"][0].message == (
        "field 'rows': expected 4 rows, found 1"
    )
    assert report.table_rows == {}


def test_extra_checks_run_after_the_built_in_checks() -> None:
    result = _result(
        {"age": {"type": "integer", "min": 18, "max": 80}},
        [{"age": 18}, {"age": "no"}],
    )
    report = result.validate(extra=(FlagValue(18),))
    assert [item.check for item in report.violations] == ["type", "flag"]
    assert report.by_field["age"][1].message.endswith("flagged 18")
    assert report.violation_count == 2


def test_zero_rows_pass() -> None:
    result = FakerForge(seed=1).generate(schema=CUSTOMERS, rows=0)
    report = result.validate()
    assert report.status == "passed"
    assert report.rows == 0
    assert len(result) == 0
