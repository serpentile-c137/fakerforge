"""Dependency graph and a stable topological sort.

The sort matches the declaration-index tie break used by dataset schemas.
Parallel levels are a separate view: nodes in one level do not depend on
each other. Generation order follows ``order``, not a flattening of levels.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class GraphNode:
    """One table or column in a dependency graph.

    Args:
        id: Stable node id. Tables use the table name. Columns use
            ``table.column``.
        kind: ``"table"`` or ``"column"``.
        table: Owning table for a column node. ``None`` for a table node.
    """

    id: str
    kind: str
    table: str | None = None


@dataclass(frozen=True, slots=True)
class GraphEdge:
    """A dependency from an earlier node to a later node.

    Args:
        source: Node that must be generated first.
        target: Node that depends on ``source``.
        kind: ``"depends_on"``, ``"derived_from"``, or ``"references"``.
    """

    source: str
    target: str
    kind: str


@dataclass(frozen=True, slots=True)
class DependencyGraph:
    """Tables, columns, and the edges that order them.

    ``order`` is the stable topological order of table nodes. ``levels``
    groups those tables into sets that do not depend on each other.
    ``cycle`` lists table names left unordered when the table edges contain
    a cycle. An empty ``cycle`` means every table is in ``order``.

    Args:
        nodes: Table and column nodes in declaration order.
        edges: Dependencies. ``source`` is generated before ``target``.
        order: Table names in generation order. Cycle members are omitted.
        levels: Parallel table groups. Each group is declaration order.
        cycle: Table names that participate in a cycle, in declaration order.
    """

    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    order: tuple[str, ...]
    levels: tuple[tuple[str, ...], ...]
    cycle: tuple[str, ...]

    def export(self) -> dict[str, Any]:
        """Return nodes and edges as plain dictionaries.

        The mapping is suitable for JSON. It does not include generated rows.
        """
        return {
            "nodes": [
                {"id": node.id, "kind": node.kind, "table": node.table}
                for node in self.nodes
            ],
            "edges": [
                {"source": edge.source, "target": edge.target, "kind": edge.kind}
                for edge in self.edges
            ],
            "order": list(self.order),
            "levels": [list(level) for level in self.levels],
            "cycle": list(self.cycle),
        }

    @classmethod
    def from_dependencies(
        cls,
        names: Sequence[str],
        dependencies: Mapping[str, Sequence[str]],
        *,
        kind: str = "table",
    ) -> "DependencyGraph":
        """Build a graph whose nodes are ``names``.

        ``dependencies[name]`` lists nodes that must precede ``name``.
        Unknown and self dependencies are ignored, matching schema sorting.

        Args:
            names: Node ids in declaration order.
            dependencies: Preceding node ids for each name.
            kind: Node kind stored on every node. Defaults to ``"table"``.

        Returns:
            A graph. ``cycle`` is empty when every name was ordered.
        """
        ordered = list(names)
        incoming = {name: tuple(dependencies.get(name, ())) for name in ordered}
        known = set(ordered)
        nodes = tuple(GraphNode(id=name, kind=kind, table=None) for name in ordered)
        edges = tuple(
            GraphEdge(source=dependency, target=name, kind="depends_on")
            for name, deps in incoming.items()
            for dependency in deps
            if dependency in known and dependency != name
        )
        order, cycle = topological_order(ordered, incoming)
        return cls(
            nodes=nodes,
            edges=edges,
            order=tuple(order),
            levels=parallel_levels(ordered, incoming),
            cycle=tuple(cycle),
        )

    @classmethod
    def from_database(cls, database: Any) -> "DependencyGraph":
        """Build table and column nodes from a relational schema.

        Table order uses the same parent-table edges as
        ``DatabaseSchema``. Column edges record ``depends_on``,
        ``derived_from``, and ``references``. The schema object is read
        structurally so this module does not import the schema package.

        Args:
            database: Object with ``tables`` in declaration order. Each table
                has ``name`` and ``dataset.columns``.

        Returns:
            A graph whose ``order`` matches ``database.generation_order``
            when that schema was sorted with :func:`topological_order`.
        """
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        names: list[str] = []
        dependencies: dict[str, tuple[str, ...]] = {}
        for table in database.tables:
            names.append(table.name)
            nodes.append(GraphNode(id=table.name, kind="table"))
            parents: set[str] = set()
            for column in table.dataset.columns:
                column_id = f"{table.name}.{column.name}"
                nodes.append(GraphNode(id=column_id, kind="column", table=table.name))
                if column.derived_from:
                    edges.append(
                        GraphEdge(
                            source=f"{table.name}.{column.derived_from}",
                            target=column_id,
                            kind="derived_from",
                        )
                    )
                for dependency in column.depends_on:
                    edges.append(
                        GraphEdge(
                            source=f"{table.name}.{dependency}",
                            target=column_id,
                            kind="depends_on",
                        )
                    )
                if column.references_table and column.references_column:
                    parents.add(column.references_table)
                    edges.append(
                        GraphEdge(
                            source=(
                                f"{column.references_table}.{column.references_column}"
                            ),
                            target=column_id,
                            kind="references",
                        )
                    )
            dependencies[table.name] = tuple(sorted(parents))
            for parent in parents:
                edges.append(
                    GraphEdge(source=parent, target=table.name, kind="references")
                )
        order, cycle = topological_order(names, dependencies)
        return cls(
            nodes=tuple(nodes),
            edges=tuple(edges),
            order=tuple(order),
            levels=parallel_levels(names, dependencies),
            cycle=tuple(cycle),
        )


def topological_order(
    names: Sequence[str],
    dependencies: Mapping[str, Sequence[str]],
) -> tuple[list[str], list[str]]:
    """Return a stable order and any names left in a cycle.

    Ready nodes are emitted in declaration order. A dependency that is not
    in ``names``, and a self-dependency, are ignored.

    Args:
        names: Node ids in declaration order.
        dependencies: Preceding ids for each name.

    Returns:
        The ordered prefix, then the names that remain because of a cycle.
        The second list is empty when the graph is acyclic.
    """
    ordered = list(names)
    index = {name: position for position, name in enumerate(ordered)}
    incoming = {
        name: {
            item
            for item in dependencies.get(name, ())
            if item in index and item != name
        }
        for name in ordered
    }
    dependents: dict[str, list[str]] = {name: [] for name in ordered}
    for name, deps in incoming.items():
        for dependency in deps:
            dependents[dependency].append(name)
    ready = sorted(
        [name for name, deps in incoming.items() if not deps],
        key=lambda name: index[name],
    )
    order: list[str] = []
    while ready:
        name = ready.pop(0)
        order.append(name)
        freed: list[str] = []
        for child in dependents[name]:
            incoming[child].discard(name)
            if not incoming[child]:
                freed.append(child)
        ready.extend(freed)
        ready.sort(key=lambda item: index[item])
    if len(order) == len(ordered):
        return order, []
    remaining = [name for name in ordered if name not in set(order)]
    return order, remaining


def parallel_levels(
    names: Sequence[str],
    dependencies: Mapping[str, Sequence[str]],
) -> tuple[tuple[str, ...], ...]:
    """Group ``names`` into levels that do not depend on each other.

    A node is placed when every in-graph dependency is already placed.
    Nodes in the same level are sorted by declaration order. Names left in
    a cycle are omitted.

    Args:
        names: Node ids in declaration order.
        dependencies: Preceding ids for each name.

    Returns:
        Levels from roots to leaves. Independent nodes share a level.
    """
    ordered = list(names)
    index = {name: position for position, name in enumerate(ordered)}
    incoming = {
        name: {
            item
            for item in dependencies.get(name, ())
            if item in index and item != name
        }
        for name in ordered
    }
    placed: set[str] = set()
    remaining = list(ordered)
    levels: list[tuple[str, ...]] = []
    while remaining:
        ready = [name for name in remaining if incoming[name] <= placed]
        if not ready:
            break
        ready.sort(key=lambda name: index[name])
        levels.append(tuple(ready))
        placed.update(ready)
        remaining = [name for name in remaining if name not in placed]
    return tuple(levels)
