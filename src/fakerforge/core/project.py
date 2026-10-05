"""Project documents in memory, JSON, and YAML."""

import json
from collections.abc import Mapping
from importlib import import_module
from pathlib import Path
from types import MappingProxyType
from typing import Any

from fakerforge.core.errors import PlanError
from fakerforge.core.plan import ESTIMATED_BYTES_PER_COLUMN, GenerationPlan
from fakerforge.graph.dag import DependencyGraph
from fakerforge.schema.dataset import DatabaseSchema, SchemaError
from fakerforge.schema.generate import _resolve_providers

# Same values ``FakerForge`` accepts, without importing that module.
Seed = int | float | str | bytes | bytearray | None

_TOP_KEYS = frozenset({"project", "tables"})
_PROJECT_KEYS = frozenset({"name", "seed"})


class Project:
    """A named relational schema plus the seed recorded for it.

    The ``tables`` mapping uses the same shape as ``FakerForge.generate``:
    each table has ``rows`` and ``fields``. Loading a document does not
    generate rows and does not reseed a forge.

    Args:
        name: Project name.
        seed: Seed from the document. ``None`` when the document omitted it.
        tables: Relational schema mapping.
    """

    def __init__(
        self,
        name: str,
        seed: Seed,
        tables: Mapping[str, Any],
    ) -> None:
        if not isinstance(name, str) or name == "":
            raise PlanError("project name must be a non-empty string")
        if not isinstance(tables, Mapping):
            raise PlanError("tables must be a mapping", project=name)
        self.name = name
        self.seed = seed
        self.tables = dict(tables)

    def schema(self) -> DatabaseSchema:
        """Parse ``tables`` into a relational schema.

        Circular dependencies raise :class:`PlanError`. Other schema
        problems raise :class:`~fakerforge.schema.SchemaError`.

        Returns:
            The parsed database schema.
        """
        try:
            return DatabaseSchema.from_dict(self.tables)
        except SchemaError as exc:
            circular = _circular_error(self.name, exc)
            if circular is not None:
                raise circular from exc
            raise

    def build_dependency_graph(self) -> DependencyGraph:
        """Return the table and column dependency graph.

        Returns:
            A graph whose table order matches the schema generation order.

        Raises:
            PlanError: The tables contain a circular dependency.
            SchemaError: The tables are otherwise invalid.
        """
        return DependencyGraph.from_database(self.schema())

    def validate_dependency_graph(self) -> DependencyGraph:
        """Return the graph when every table can be ordered.

        Returns:
            The dependency graph.

        Raises:
            PlanError: A table or field cycle is present.
            SchemaError: The tables are otherwise invalid.
        """
        graph = self.build_dependency_graph()
        if graph.cycle:
            raise PlanError(
                f"circular table dependency: {', '.join(graph.cycle)}",
                project=self.name,
                dependency=", ".join(graph.cycle),
            )
        return graph

    def generation_plan(self, forge: Any) -> GenerationPlan:
        """Validate providers and dependencies without generating rows.

        Args:
            forge: FakerForge instance whose registered providers are checked.

        Returns:
            Row counts, generation order, and parallel groups.

        Raises:
            PlanError: The document has a circular dependency.
            SchemaError: A field, provider, or row count is invalid.
        """
        graph = self.validate_dependency_graph()
        database = self.schema()
        for table in database.in_generation_order():
            _resolve_providers(forge, table.dataset, table.rows)
        counts = {table.name: table.rows for table in database.tables}
        estimates = {
            table.name: ESTIMATED_BYTES_PER_COLUMN * len(table.dataset.columns)
            for table in database.tables
        }
        return GenerationPlan(
            project=self.name,
            seed=self.seed,
            order=graph.order,
            row_counts=MappingProxyType(counts),
            parallel_groups=graph.levels,
            estimated_bytes_per_row=MappingProxyType(estimates),
            total_rows=sum(counts[name] for name in graph.order),
        )


def load_project(source: str | Path | Mapping[str, Any]) -> Project:
    """Load a project from a mapping or a JSON or YAML file.

    YAML requires PyYAML (``pip install 'fakerforge[yaml]'``). Files are
    parsed as data. They are not executed.

    Args:
        source: A project mapping, or a path to ``.json``, ``.yaml``, or
            ``.yml``.

    Returns:
        The parsed project. Tables are not validated until
        :meth:`Project.schema` or :meth:`Project.generation_plan`.

    Raises:
        PlanError: The document, path, or YAML dependency is invalid.
    """
    document = _read_document(source)
    if not isinstance(document, Mapping):
        raise PlanError("project document must be a mapping")
    unknown = sorted(set(document) - _TOP_KEYS)
    if unknown:
        raise PlanError(f"unknown project keys {unknown}")
    if "project" not in document or "tables" not in document:
        raise PlanError("project document requires 'project' and 'tables'")
    meta = document["project"]
    if not isinstance(meta, Mapping):
        raise PlanError("project must be a mapping")
    unknown_meta = sorted(str(key) for key in set(meta) - _PROJECT_KEYS)
    if unknown_meta:
        raise PlanError(f"unknown keys in project: {unknown_meta}")
    name = meta.get("name")
    if not isinstance(name, str) or name == "":
        raise PlanError("project name must be a non-empty string")
    seed = _parse_seed(meta["seed"], name) if "seed" in meta else None
    tables = document["tables"]
    if not isinstance(tables, Mapping):
        raise PlanError("tables must be a mapping", project=name)
    return Project(name=name, seed=seed, tables=tables)


def _read_document(source: str | Path | Mapping[str, Any]) -> Any:
    if isinstance(source, Mapping):
        return source
    path = Path(source)
    if not path.is_file():
        raise PlanError(f"project file {path} does not exist")
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise PlanError(f"invalid JSON in {path}: {exc.msg}") from exc
    if suffix in {".yaml", ".yml"}:
        return _read_yaml(path, text)
    raise PlanError(f"project file {path} must be JSON (.json) or YAML (.yaml, .yml)")


def _read_yaml(path: Path, text: str) -> Any:
    yaml = _import_yaml()
    if yaml is None:
        raise PlanError(
            "YAML projects require PyYAML. "
            "Install it with: pip install 'fakerforge[yaml]'"
        )
    try:
        loaded = yaml.safe_load(text)
    except Exception as exc:
        if type(exc).__module__.split(".")[0] != "yaml":
            raise
        raise PlanError(f"invalid YAML in {path}") from exc
    return loaded


def _import_yaml() -> Any:
    try:
        return import_module("yaml")
    except ImportError:
        return None


def _parse_seed(value: object, project: str) -> Seed:
    if value is None or isinstance(value, (str, bytes, bytearray)):
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PlanError(
            "project seed must be an int, float, str, or null",
            project=project,
        )
    return value


def _circular_error(project: str, exc: SchemaError) -> PlanError | None:
    circular = [item for item in exc.errors if "circular" in item]
    if not circular:
        return None
    message = circular[0]
    dependency = message.split(":", 1)[1].strip() if ":" in message else message
    table = _table_name(message)
    return PlanError(
        message,
        project=project,
        table=table,
        dependency=dependency,
    )


def _table_name(message: str) -> str | None:
    marker = "table '"
    if marker not in message:
        return None
    start = message.index(marker) + len(marker)
    end = message.find("'", start)
    if end == -1:
        return None
    return message[start:end]
