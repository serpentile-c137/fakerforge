"""Project loading and dry-run plans."""

from pathlib import Path

import pytest

from fakerforge import FakerForge
from fakerforge.core import PlanError
from fakerforge.core.plan import ESTIMATED_BYTES_PER_COLUMN


def _project() -> dict[str, object]:
    return {
        "project": {"name": "demo", "seed": 42},
        "tables": {
            "customers": {
                "rows": 10,
                "fields": {
                    "customer_id": {"type": "uuid", "unique": True},
                    "name": {"provider": "person.name"},
                },
            },
            "products": {
                "rows": 5,
                "fields": {"product_id": {"type": "uuid", "unique": True}},
            },
            "orders": {
                "rows": 20,
                "fields": {
                    "order_id": {"type": "uuid", "unique": True},
                    "customer_id": {"references": "customers.customer_id"},
                    "product_id": {"references": "products.product_id"},
                },
            },
        },
    }


def test_plan_reports_order_and_does_not_generate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("generated")

    monkeypatch.setattr("fakerforge.schema.generate._row", fail)
    monkeypatch.setattr(
        "fakerforge.distributions.engine.DistributionEngine.number", fail
    )
    forge = FakerForge(seed=1)
    plan = forge.plan(forge.load(_project()))
    assert plan.project == "demo"
    assert plan.seed == 42
    assert plan.order == ("customers", "products", "orders")
    assert dict(plan.row_counts) == {"customers": 10, "products": 5, "orders": 20}
    assert plan.total_rows == 35
    assert plan.parallel_groups == (("customers", "products"), ("orders",))
    assert plan.estimated_bytes_per_row["customers"] == ESTIMATED_BYTES_PER_COLUMN * 2
    assert plan.estimated_bytes_per_row["orders"] == ESTIMATED_BYTES_PER_COLUMN * 3


def test_plan_does_not_consume_the_faker_stream() -> None:
    document = _project()
    first = FakerForge(seed=42)
    expected = first.name()
    forge = FakerForge(seed=42)
    forge.plan(forge.load(document))
    assert forge.name() == expected


def test_load_minimal_json_project() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "projects"
        / "minimal"
        / "project.json"
    )
    forge = FakerForge()
    project = forge.load(path)
    plan = forge.plan(project)
    assert project.name == "minimal"
    assert project.seed == 42
    assert plan.order == ("customers", "orders")
    assert plan.total_rows == 15


def test_table_cycle_names_the_project() -> None:
    document = {
        "project": {"name": "loop"},
        "tables": {
            "orders": {
                "rows": 1,
                "fields": {
                    "order_id": {"type": "uuid", "unique": True},
                    "customer_id": {"references": "customers.customer_id"},
                },
            },
            "customers": {
                "rows": 1,
                "fields": {
                    "customer_id": {"type": "uuid", "unique": True},
                    "order_id": {"references": "orders.order_id"},
                },
            },
        },
    }
    project = FakerForge().load(document)
    with pytest.raises(PlanError) as caught:
        project.validate_dependency_graph()
    assert caught.value.project == "loop"
    assert caught.value.dependency is not None
    assert "orders" in caught.value.dependency
    assert "customers" in caught.value.dependency


def test_unknown_project_keys_are_rejected() -> None:
    document = _project()
    document["scale"] = 1
    with pytest.raises(PlanError, match="unknown project keys"):
        FakerForge().load(document)


def test_missing_and_invalid_json_are_plan_errors(tmp_path: Path) -> None:
    forge = FakerForge()
    with pytest.raises(PlanError, match="does not exist"):
        forge.load(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(PlanError, match="invalid JSON"):
        forge.load(bad)


def test_yaml_requires_the_optional_extra(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "project.yaml"
    path.write_text("project: {name: demo}\ntables: {}\n", encoding="utf-8")

    def missing_yaml(_name: str) -> object:
        raise ImportError("no yaml")

    monkeypatch.setattr("fakerforge.core.project.import_module", missing_yaml)
    with pytest.raises(PlanError, match=r"fakerforge\[yaml\]"):
        FakerForge().load(path)
