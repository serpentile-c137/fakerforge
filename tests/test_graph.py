"""Dependency graph order, cycles, and parallel levels."""

from fakerforge.graph import DependencyGraph
from fakerforge.schema import DatabaseSchema


def test_customer_orders_match_schema_generation_order() -> None:
    database = DatabaseSchema.from_dict(
        {
            "customers": {
                "rows": 2,
                "fields": {"customer_id": {"type": "uuid", "unique": True}},
            },
            "orders": {
                "rows": 4,
                "fields": {
                    "order_id": {"type": "uuid", "unique": True},
                    "customer_id": {"references": "customers.customer_id"},
                },
            },
        }
    )
    graph = DependencyGraph.from_database(database)
    assert graph.order == database.generation_order
    assert graph.order == ("customers", "orders")
    assert graph.cycle == ()
    assert graph.levels == (("customers",), ("orders",))
    references = [
        edge
        for edge in graph.edges
        if edge.kind == "references" and edge.target == "orders"
    ]
    assert references[0].source == "customers"
    exported = graph.export()
    assert exported["order"] == ["customers", "orders"]
    assert any(node["id"] == "orders.customer_id" for node in exported["nodes"])


def test_independent_tables_share_a_parallel_level() -> None:
    graph = DependencyGraph.from_dependencies(
        ["customers", "products", "orders"],
        {"orders": ["customers", "products"]},
    )
    assert graph.order == ("customers", "products", "orders")
    assert graph.levels == (("customers", "products"), ("orders",))
    assert graph.cycle == ()


def test_cycles_are_left_unordered() -> None:
    graph = DependencyGraph.from_dependencies(
        ["orders", "customers"],
        {"orders": ["customers"], "customers": ["orders"]},
    )
    assert graph.order == ()
    assert graph.levels == ()
    assert graph.cycle == ("orders", "customers")


def test_column_edges_record_derived_and_dependent_fields() -> None:
    database = DatabaseSchema.from_dict(
        {
            "people": {
                "rows": 1,
                "fields": {
                    "date_of_birth": {"type": "date"},
                    "age": {"derived_from": "date_of_birth"},
                    "start_date": {"type": "date"},
                    "end_date": {"type": "date", "depends_on": "start_date"},
                },
            }
        }
    )
    graph = DependencyGraph.from_database(database)
    edges = {(edge.source, edge.target, edge.kind) for edge in graph.edges}
    assert ("people.date_of_birth", "people.age", "derived_from") in edges
    assert ("people.start_date", "people.end_date", "depends_on") in edges
