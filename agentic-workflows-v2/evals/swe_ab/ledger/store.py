"""The ledger API: connection setup, writes, cross-row validation, and
JSONL export/import for version control.

`open_ledger` produces a correctly configured `sqlite3.Connection` (foreign
keys on, WAL, busy timeout, `schema_version` check). `LedgerStore` wraps
that connection with:

  - `register()` for content-addressed reference/design rows, where
    re-registering the same entity is a no-op (`ON CONFLICT DO NOTHING`).
  - `append_*()` for the append-only observation tables, whose schema
    triggers reject any UPDATE/DELETE (ADR: history is corrected by
    inserting a superseding row, never by mutation).
  - `check_*()` validations that the database's CHECK/trigger vocabulary
    cannot express on its own (judge calibration gating, arm balance,
    wave completeness).
  - `export_jsonl` / `import_jsonl` for a diff-stable, version-controllable
    on-disk representation of the whole ledger.

Standard library only. Do not add third-party imports here.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import sqlite3
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from . import SCHEMA_PATH
from .ids import canonical_json
from .models import (
    TABLE_ORDER,
    Arm,
    ArmConfig,
    Blob,
    Campaign,
    Grade,
    Grader,
    Image,
    JudgeCalibration,
    Model,
    PlanCell,
    PriceSnapshot,
    Prompt,
    Spend,
    StepUsage,
    Substrate,
    Task,
    TaskSet,
    Trial,
    Wave,
    WaveTask,
    Workflow,
    WorkflowPrompt,
)

__all__ = [
    "EXPECTED_SCHEMA_VERSION",
    "DEFAULT_BUSY_TIMEOUT_MS",
    "JUDGE_TNR_FLOOR",
    "JUDGE_TPR_FLOOR",
    "open_ledger",
    "LedgerStore",
    "ArmCompleteness",
    "WaveCompleteness",
    "LedgerError",
    "SchemaVersionMismatch",
    "LedgerIntegrityError",
    "AppendOnlyViolation",
    "JudgeNotCalibrated",
    "ArmsUnbalanced",
    "UnknownWave",
    "BlobMissing",
    "BlobCorrupt",
]

# ---------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------

#: `schema_meta.schema_version` value this code was written against
#: (schema.sql section 1). `open_ledger` refuses to operate on a database
#: stamped with any other value.
EXPECTED_SCHEMA_VERSION = "1"

#: Minimum `PRAGMA busy_timeout` (milliseconds) applied by `open_ledger`,
#: so a writer waiting behind another connection's write lock retries
#: instead of failing immediately with `database is locked`.
DEFAULT_BUSY_TIMEOUT_MS = 5000

#: Ratified calibration floors (D-1 / hard_gate policy): a judge-kind
#: grader may gate a wave only once its most recent calibration clears
#: both of these simultaneously and has not expired as of the wave's
#: `opened_at`. See `LedgerStore.check_judge_gating`.
JUDGE_TNR_FLOOR = 0.95
JUDGE_TPR_FLOOR = 0.85


# ---------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------


class LedgerError(Exception):
    """Base class for every error raised by the ledger persistence layer."""


class SchemaVersionMismatch(LedgerError):
    """The database's `schema_meta.schema_version` does not match the
    version this code expects (`EXPECTED_SCHEMA_VERSION`), or the database
    has no readable `schema_meta` table at all."""


class LedgerIntegrityError(LedgerError):
    """A write violated a database integrity constraint (foreign key,
    CHECK, UNIQUE, or one of schema.sql's invariant triggers).

    Wraps the underlying `sqlite3.IntegrityError` so callers of this
    module's API never need to import `sqlite3` themselves, or pattern
    match on a driver-specific message, to catch a predictable,
    ledger-scoped exception type.
    """


class AppendOnlyViolation(LedgerIntegrityError):
    """Raised when schema.sql's append-only triggers reject a write to
    `trial`, `step_usage`, `spend`, or `grade` — i.e. an UPDATE or DELETE
    against one of those tables. `LedgerStore`'s own API never issues
    UPDATE/DELETE (only append-only INSERTs), so this is reachable only
    by writing directly against the connection returned by `open_ledger`;
    a duplicate append through `LedgerStore` instead raises the more
    general `LedgerIntegrityError` (a UNIQUE/PRIMARY KEY conflict).
    """


class JudgeNotCalibrated(LedgerError):
    """A wave's substrate uses a `kind='judge'` grader with no
    `judge_calibration` row clearing `JUDGE_TNR_FLOOR` / `JUDGE_TPR_FLOOR`
    and unexpired as of the wave's `opened_at`."""


class ArmsUnbalanced(LedgerError):
    """The set of `(task_id, run_idx)` pairs carrying at least one `ok`
    trial differs between two or more arms in the same wave, which would
    break paired statistics computed across those arms."""


class UnknownWave(LedgerError):
    """No `wave` row exists for the given `wave_id`."""


class BlobMissing(LedgerError):
    """No blob is stored for the requested digest. Shared with
    `ledger.blobs.BlobStore` so callers only need one exception type."""


class BlobCorrupt(LedgerError):
    """The bytes stored at a digest's on-disk path do not hash back to
    that digest. Shared with `ledger.blobs.BlobStore`."""


def _wrap_integrity_error(exc: sqlite3.IntegrityError) -> LedgerIntegrityError:
    """Translate a raw `sqlite3.IntegrityError` into a `LedgerError`
    subclass so callers of this module's insert paths never have to
    import `sqlite3` themselves to catch a predictable type.

    `AppendOnlyViolation` is reserved for the literal message schema.sql's
    `trg_*_no_update` / `trg_*_no_delete` triggers raise. This module never
    issues UPDATE/DELETE itself, so in practice every error reaching here
    (a duplicate `trial_id`/`grade_id`/... on a plain append, an FK
    failure, a CHECK failure) is the generic `LedgerIntegrityError` — which
    is exactly the point: whatever the underlying constraint, the caller
    gets one well-known ledger exception type instead of a raw driver
    exception carrying a SQLite-flavored message.
    """
    message = str(exc)
    if "append-only" in message:
        return AppendOnlyViolation(message)
    return LedgerIntegrityError(message)


# ---------------------------------------------------------------------
# open_ledger
# ---------------------------------------------------------------------


def open_ledger(path: Path | str, *, create: bool = True) -> sqlite3.Connection:
    """Open (and, if needed, initialize) a ledger database.

    Applies `schema.sql` when the database is new (an `:memory:` database
    is always "new"). Sets `foreign_keys`, `journal_mode`, `synchronous`
    and `busy_timeout`, and `row_factory = sqlite3.Row`. `foreign_keys` is
    re-asserted on every call because SQLite defaults it OFF per
    connection and does not persist it in the file.

    Raises `FileNotFoundError` if `path` does not exist and `create` is
    False, and `SchemaVersionMismatch` if an existing database's
    `schema_meta.schema_version` does not match `EXPECTED_SCHEMA_VERSION`.
    """
    is_memory = str(path) == ":memory:"
    needs_schema = True

    if not is_memory:
        file_path = Path(path)
        needs_schema = not file_path.exists()
        if needs_schema:
            if not create:
                raise FileNotFoundError(
                    f"ledger database does not exist and create=False: {file_path}"
                )
            file_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        # DEFAULT_BUSY_TIMEOUT_MS is a fixed internal int constant, never
        # attacker/user-controlled input, so interpolating it is safe.
        conn.execute(f"PRAGMA busy_timeout = {DEFAULT_BUSY_TIMEOUT_MS}")

        if needs_schema:
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            conn.commit()
        else:
            _assert_schema_version(conn)
    except BaseException:
        # Never hand back (or strand) a half-configured, unusable
        # connection -- e.g. a version mismatch must not leak the file
        # handle `open_ledger` just opened to check it.
        conn.close()
        raise

    return conn


def _assert_schema_version(conn: sqlite3.Connection) -> None:
    try:
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise SchemaVersionMismatch(
            f"database is missing the schema_meta table: {exc}"
        ) from exc

    if row is None:
        raise SchemaVersionMismatch(
            "database has no schema_meta.schema_version row; "
            f"expected {EXPECTED_SCHEMA_VERSION!r}"
        )
    found = row["value"]
    if found != EXPECTED_SCHEMA_VERSION:
        raise SchemaVersionMismatch(
            f"schema_version mismatch: database has {found!r}, "
            f"code expects {EXPECTED_SCHEMA_VERSION!r}"
        )


# ---------------------------------------------------------------------
# Table metadata, derived once, reused by register/append/export/import
# ---------------------------------------------------------------------

#: Every row-mapped dataclass this module writes, keyed by primary key
#: column(s) — used to order `export_jsonl` output deterministically and
#: to build column lists for import. Mirrors TABLE_ORDER exactly.
_PK_COLUMNS: dict[str, tuple[str, ...]] = {
    "blob": ("digest",),
    "model": ("model_id",),
    "price_snapshot": ("snapshot_id",),
    "prompt": ("prompt_id",),
    "workflow": ("workflow_id",),
    "workflow_prompt": ("workflow_id", "prompt_id"),
    "grader": ("grader_id",),
    "judge_calibration": ("calibration_id",),
    "image": ("image_id",),
    "task_set": ("task_set_id",),
    "task": ("task_id",),
    "substrate": ("substrate_id",),
    "arm_config": ("arm_config_id",),
    "campaign": ("campaign_id",),
    "arm": ("arm_id",),
    "wave": ("wave_id",),
    "wave_task": ("wave_id", "task_id"),
    "plan_cell": ("wave_id", "arm_id", "task_id", "run_idx"),
    "trial": ("trial_id",),
    "step_usage": ("trial_id", "step_idx"),
    "spend": ("spend_id",),
    "grade": ("grade_id",),
}

if set(_PK_COLUMNS) != set(TABLE_ORDER):
    # Load-time guardrail, not an `assert` (which `-O` would strip): if
    # models.TABLE_ORDER ever gains/loses a table, this module's export
    # ordering and column-derivation metadata must be updated in lockstep.
    raise AssertionError(
        "programmer error: _PK_COLUMNS drifted from models.TABLE_ORDER"
    )

#: The content-addressed reference/design dataclasses `register()`
#: accepts, mapped to the table they populate.
_REGISTERABLE: dict[type, str] = {
    Blob: "blob",
    Model: "model",
    PriceSnapshot: "price_snapshot",
    Prompt: "prompt",
    Workflow: "workflow",
    WorkflowPrompt: "workflow_prompt",
    Grader: "grader",
    JudgeCalibration: "judge_calibration",
    Image: "image",
    TaskSet: "task_set",
    Task: "task",
    Substrate: "substrate",
    ArmConfig: "arm_config",
    Campaign: "campaign",
    Arm: "arm",
    Wave: "wave",
    WaveTask: "wave_task",
    PlanCell: "plan_cell",
}

RegisterableEntity = (
    Blob
    | Model
    | PriceSnapshot
    | Prompt
    | Workflow
    | WorkflowPrompt
    | Grader
    | JudgeCalibration
    | Image
    | TaskSet
    | Task
    | Substrate
    | ArmConfig
    | Campaign
    | Arm
    | Wave
    | WaveTask
    | PlanCell
)

LedgerRow = RegisterableEntity | Trial | StepUsage | Spend | Grade


def _row_columns(obj: LedgerRow) -> list[str]:
    return [f.name for f in dataclasses.fields(obj)]


# ---------------------------------------------------------------------
# Completeness report
# ---------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class ArmCompleteness:
    """`plan_cell` tallies for one arm within one wave."""

    arm_id: str
    planned: int
    done: int
    missing: int


@dataclasses.dataclass(frozen=True, slots=True)
class WaveCompleteness:
    """`plan_cell` tallies for a whole wave, plus the per-arm breakdown.

    `planned` counts every `plan_cell` row regardless of status (the
    design's total cell count); `done` counts `status = 'done'`; `missing`
    is everything not yet done (`planned - done`, so `abandoned` cells
    still count as missing rather than silently vanishing from the
    total).
    """

    wave_id: str
    planned: int
    done: int
    missing: int
    per_arm: tuple[ArmCompleteness, ...]


# ---------------------------------------------------------------------
# LedgerStore
# ---------------------------------------------------------------------


class LedgerStore:
    """The ledger's write and validation API, wrapping one connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    @contextlib.contextmanager
    def transaction(self) -> Iterator[None]:
        """Commit on success, roll back on any exception.

        Never nest calls to this: an inner call's commit would make the
        outer call's rollback (on a later failure) unable to undo the
        inner call's writes, breaking the atomicity `append_batch` and
        `import_jsonl` depend on. Multi-row operations in this class call
        the private `_insert_row` helper directly inside one `transaction`
        block rather than reusing the public single-row methods.
        """
        try:
            yield
        except BaseException:
            self._conn.rollback()
            raise
        else:
            self._conn.commit()

    def _insert_row(
        self, table: str, obj: LedgerRow, *, ignore_conflicts: bool = False
    ) -> None:
        columns = _row_columns(obj)
        placeholders = ",".join(["?"] * len(columns))
        conflict_clause = " ON CONFLICT DO NOTHING" if ignore_conflicts else ""
        # `table`/`columns` come from this module's own fixed metadata
        # (_PK_COLUMNS keys, dataclasses.fields), never from caller-supplied
        # strings.
        sql = (
            f"INSERT INTO {table} ({','.join(columns)}) "  # noqa: S608
            f"VALUES ({placeholders}){conflict_clause}"
        )
        try:
            self._conn.execute(sql, obj.to_row())
        except sqlite3.IntegrityError as exc:
            raise _wrap_integrity_error(exc) from exc

    # -- Reference/design entities -------------------------------------

    def register(self, obj: RegisterableEntity) -> str:
        """Insert a content-addressed reference/design row if it is not
        already present, and return its primary key.

        Idempotent by construction *when the caller supplies the same
        primary key for the same logical entity* — true automatically for
        every type whose id is computed by `ledger.ids` (Model, Prompt,
        Workflow, Grader, Image, TaskSet, Task, Substrate, ArmConfig).
        `Campaign`, `Arm`, `Wave`, `WaveTask` and `PlanCell` have no id
        function in `ledger.ids`; for those, idempotency is only as good
        as the caller's own id stability.

        The insert uses a bare `ON CONFLICT DO NOTHING`, which suppresses
        *any* unique-constraint collision, not just one on the primary
        key. That alone would let this method return a primary key for a
        row it never persisted -- a caller registering a second `Wave`
        under an existing `UNIQUE(campaign_id, wave_no)` would get its own
        `wave_id` back and every later foreign key against it would fail
        somewhere else entirely. So the row is read back by primary key
        and a miss raises `LedgerIntegrityError` naming the slot. A ledger
        whose whole purpose is to make a silent overwrite impossible
        cannot have a write path that quietly does nothing.
        """
        table = _REGISTERABLE.get(type(obj))
        if table is None:
            raise TypeError(f"{type(obj).__name__} is not a registerable ledger entity")
        pk_columns = _PK_COLUMNS[table]
        pk_values = tuple(getattr(obj, name) for name in pk_columns)
        with self.transaction():
            self._insert_row(table, obj, ignore_conflicts=True)
            if not self._row_exists(table, pk_columns, pk_values):
                slot = dict(zip(pk_columns, pk_values, strict=True))
                raise LedgerIntegrityError(
                    f"register({type(obj).__name__}) persisted nothing: the insert "
                    f"was suppressed by a UNIQUE constraint other than the primary "
                    f"key, so {slot} is absent from {table!r}. A different row "
                    f"already occupies that logical slot -- reconcile the ids "
                    f"rather than re-registering."
                )
        return (
            str(pk_values[0])
            if len(pk_values) == 1
            else ":".join(str(value) for value in pk_values)
        )

    def _row_exists(
        self, table: str, pk_columns: tuple[str, ...], pk_values: tuple[Any, ...]
    ) -> bool:
        """Whether *table* holds a row at the given primary key."""
        where = " AND ".join(f"{column} = ?" for column in pk_columns)
        # `table`/`pk_columns` come from this module's own fixed metadata
        # (_PK_COLUMNS), never from caller-supplied strings.
        sql = f"SELECT 1 FROM {table} WHERE {where} LIMIT 1"  # noqa: S608
        return self._conn.execute(sql, pk_values).fetchone() is not None

    # -- Observations (append-only) -------------------------------------

    def append_trial(self, trial: Trial) -> None:
        with self.transaction():
            self._insert_row("trial", trial)

    def append_step_usage(self, rows: Sequence[StepUsage]) -> None:
        with self.transaction():
            for row in rows:
                self._insert_row("step_usage", row)

    def append_spend(self, spend: Spend) -> None:
        with self.transaction():
            self._insert_row("spend", spend)

    def append_grade(self, grade: Grade) -> None:
        with self.transaction():
            self._insert_row("grade", grade)

    def append_batch(
        self,
        *,
        trials: Sequence[Trial] = (),
        step_usage: Sequence[StepUsage] = (),
        spends: Sequence[Spend] = (),
        grades: Sequence[Grade] = (),
    ) -> None:
        """Append all given rows in one transaction: all rows land, or
        none do."""
        with self.transaction():
            for trial in trials:
                self._insert_row("trial", trial)
            for usage in step_usage:
                self._insert_row("step_usage", usage)
            for spend in spends:
                self._insert_row("spend", spend)
            for grade in grades:
                self._insert_row("grade", grade)

    # -- Validation the schema cannot express ---------------------------

    def check_judge_gating(self, wave_id: str) -> None:
        """Raise `JudgeNotCalibrated` if `wave_id`'s substrate uses a
        `kind='judge'` grader with no calibration clearing
        `JUDGE_TNR_FLOOR` / `JUDGE_TPR_FLOOR`, unexpired as of the wave's
        `opened_at`. A non-judge grader always passes. Raises
        `UnknownWave` if the wave does not exist.
        """
        wave_row = self._conn.execute(
            "SELECT substrate_id, opened_at FROM wave WHERE wave_id = ?",
            (wave_id,),
        ).fetchone()
        if wave_row is None:
            raise UnknownWave(f"no wave with wave_id={wave_id!r}")

        grader_row = self._conn.execute(
            "SELECT grader.grader_id AS grader_id, grader.kind AS kind "
            "FROM substrate JOIN grader ON grader.grader_id = substrate.grader_id "
            "WHERE substrate.substrate_id = ?",
            (wave_row["substrate_id"],),
        ).fetchone()
        if grader_row is None:
            # Unreachable under the schema's FK constraints (substrate.
            # grader_id and wave.substrate_id are both NOT NULL foreign
            # keys) — guarded anyway rather than trusting that invariant.
            raise UnknownWave(
                f"wave {wave_id!r} references a substrate/grader that does not exist"
            )
        if grader_row["kind"] != "judge":
            return

        calibration = self._conn.execute(
            "SELECT 1 FROM judge_calibration "
            "WHERE grader_id = ? AND tnr >= ? AND tpr >= ? AND expires_at > ? "
            "LIMIT 1",
            (
                grader_row["grader_id"],
                JUDGE_TNR_FLOOR,
                JUDGE_TPR_FLOOR,
                wave_row["opened_at"],
            ),
        ).fetchone()
        if calibration is None:
            raise JudgeNotCalibrated(
                f"grader {grader_row['grader_id']!r} (kind='judge') used by "
                f"wave {wave_id!r} has no judge_calibration row clearing "
                f"tnr>={JUDGE_TNR_FLOOR}, tpr>={JUDGE_TPR_FLOOR}, unexpired "
                f"as of {wave_row['opened_at']!r}"
            )

    def check_wave_complete(self, wave_id: str) -> WaveCompleteness:
        """Report `plan_cell` planned/done/missing counts for `wave_id`,
        overall and per arm. Never raises — an unknown or empty wave just
        reports all-zero counts; this is a report, not a gate.
        """
        rows = self._conn.execute(
            "SELECT arm_id, status, COUNT(*) AS n FROM plan_cell "
            "WHERE wave_id = ? GROUP BY arm_id, status",
            (wave_id,),
        ).fetchall()

        per_arm_counts: dict[str, dict[str, int]] = {}
        for row in rows:
            counts = per_arm_counts.setdefault(row["arm_id"], {"planned": 0, "done": 0})
            counts["planned"] += row["n"]
            if row["status"] == "done":
                counts["done"] += row["n"]

        per_arm = tuple(
            ArmCompleteness(
                arm_id=arm_id,
                planned=counts["planned"],
                done=counts["done"],
                missing=counts["planned"] - counts["done"],
            )
            for arm_id, counts in sorted(per_arm_counts.items())
        )
        total_planned = sum(a.planned for a in per_arm)
        total_done = sum(a.done for a in per_arm)
        return WaveCompleteness(
            wave_id=wave_id,
            planned=total_planned,
            done=total_done,
            missing=total_planned - total_done,
            per_arm=per_arm,
        )

    def check_arm_balance(self, wave_id: str) -> None:
        """Raise `ArmsUnbalanced` if the set of `(task_id, run_idx)` pairs
        with at least one `ok` trial differs between arms planned into
        `wave_id`. An arm with zero `ok` trials still participates in the
        comparison (as the empty set), so a wholly-missing arm is caught
        too. Raises `UnknownWave` if the wave does not exist.
        """
        wave_row = self._conn.execute(
            "SELECT wave_id FROM wave WHERE wave_id = ?", (wave_id,)
        ).fetchone()
        if wave_row is None:
            raise UnknownWave(f"no wave with wave_id={wave_id!r}")

        by_arm: dict[str, set[tuple[str, int]]] = {
            row["arm_id"]: set()
            for row in self._conn.execute(
                "SELECT DISTINCT arm_id FROM plan_cell WHERE wave_id = ?",
                (wave_id,),
            ).fetchall()
        }
        for row in self._conn.execute(
            "SELECT arm_id, task_id, run_idx FROM trial "
            "WHERE wave_id = ? AND op_status = 'ok'",
            (wave_id,),
        ).fetchall():
            by_arm.setdefault(row["arm_id"], set()).add(
                (row["task_id"], row["run_idx"])
            )

        arms = sorted(by_arm)
        if len(arms) <= 1:
            return
        reference_arm = arms[0]
        reference_set = by_arm[reference_arm]
        for arm_id in arms[1:]:
            pairs = by_arm[arm_id]
            if pairs != reference_set:
                missing = sorted(reference_set - pairs)
                extra = sorted(pairs - reference_set)
                raise ArmsUnbalanced(
                    f"arms {reference_arm!r} and {arm_id!r} in wave "
                    f"{wave_id!r} disagree on which (task_id, run_idx) "
                    f"pairs have an ok trial: missing_in_{arm_id}="
                    f"{missing!r}, extra_in_{arm_id}={extra!r}"
                )

    # -- Export / import --------------------------------------------------

    def export_jsonl(self, out_dir: Path) -> dict[str, int]:
        """Write one `<table>.jsonl` file per table under `out_dir`, rows
        sorted by primary key so output is diff-stable, and return
        table -> row count.
        """
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        counts: dict[str, int] = {}
        for table in TABLE_ORDER:
            order_by = ", ".join(_PK_COLUMNS[table])
            rows = self._conn.execute(
                f"SELECT * FROM {table} ORDER BY {order_by}"  # noqa: S608
                # `table` is always a TABLE_ORDER member, never external
                # input.
            ).fetchall()
            path = out_dir / f"{table}.jsonl"
            with path.open("w", encoding="utf-8", newline="\n") as handle:
                for row in rows:
                    # sqlite3.Row.keys() must be called explicitly here:
                    # iterating a Row directly (`for key in row`) yields
                    # column *values*, not names, unlike a real dict.
                    record: dict[str, Any] = {
                        key: row[key]
                        for key in row.keys()  # noqa: SIM118
                    }
                    handle.write(canonical_json(record))
                    handle.write("\n")
            counts[table] = len(rows)
        return counts

    def import_jsonl(self, in_dir: Path) -> dict[str, int]:
        """Load `<table>.jsonl` files from `in_dir` in `TABLE_ORDER` so
        foreign keys resolve, in one transaction, and return table -> row
        count. A missing file is treated as zero rows for that table.
        """
        in_dir = Path(in_dir)
        counts: dict[str, int] = {}
        with self.transaction():
            for table in TABLE_ORDER:
                path = in_dir / f"{table}.jsonl"
                n = 0
                if path.is_file():
                    with path.open("r", encoding="utf-8") as handle:
                        for line in handle:
                            line = line.strip()
                            if not line:
                                continue
                            record = json.loads(line)
                            self._insert_record(table, record)
                            n += 1
                counts[table] = n
        return counts

    def _insert_record(self, table: str, record: dict[str, Any]) -> None:
        # `table` is always a TABLE_ORDER member and `columns` come from a
        # file this same class's export_jsonl wrote, never external input.
        columns = list(record.keys())
        placeholders = ",".join(["?"] * len(columns))
        sql = (
            f"INSERT INTO {table} ({','.join(columns)}) "  # noqa: S608
            f"VALUES ({placeholders})"
        )
        try:
            self._conn.execute(sql, tuple(record[name] for name in columns))
        except sqlite3.IntegrityError as exc:
            raise _wrap_integrity_error(exc) from exc
