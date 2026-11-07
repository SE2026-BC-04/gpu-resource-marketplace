"""BT3 VT-088: unit and property-based tests for bulk account import (no database).

Change request: a bad record must never lose a valid record.
Invariant: a record is reported ``created`` if and only if its account was committed.

The property tests compute the expected result from how each record was *generated*
(valid/invalid label and the base login name), not by calling the code under test, so the
oracle does not inherit the implementation's assumptions (Lecture 07, "missing oracle").
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from gpu_marketplace.identity.account_import import (
    AccountWriter,
    Created,
    FailReason,
    Failed,
    ImportReport,
    LoginNameTaken,
    NewAccount,
    RejectReason,
    Rejected,
    import_accounts,
)
from gpu_marketplace.identity.passwords import PasswordHashingBusy, ScryptPasswordHasher, ScryptProfile
from gpu_marketplace.identity.ports import AccountStoreUnavailable

PROPERTY_SETTINGS = settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])


# --------------------------------------------------------------------------- test doubles


class FakeHasher:
    """Deterministic, cheap stand-in for scrypt. Counts calls; can be told to be busy."""

    def __init__(self, busy_for: frozenset[str] = frozenset()) -> None:
        self.calls = 0
        self.busy_for = busy_for

    def hash_password(self, password: str) -> str:
        self.calls += 1
        if password in self.busy_for:
            raise PasswordHashingBusy()
        return "fake$" + hashlib.sha256(password.encode("utf-8")).hexdigest()

    def verify_password(self, password: str, encoded: str) -> bool:  # pragma: no cover - unused
        return encoded == self.hash_password(password)

    def burn_verification(self, password: str) -> None:  # pragma: no cover - unused
        pass


class FakeWriter:
    """In-memory store with commit semantics: an account is stored only if no error is raised."""

    def __init__(self, fail: Callable[[NewAccount], Exception | None] = lambda account: None) -> None:
        self.rows: dict[UUID, NewAccount] = {}
        self.calls = 0
        self._fail = fail

    def create_account(self, account: NewAccount) -> UUID:
        self.calls += 1
        if any(row.login_name == account.login_name for row in self.rows.values()):
            raise LoginNameTaken()
        error = self._fail(account)
        if error is not None:
            raise error
        user_id = account.user_id or uuid4()
        self.rows[user_id] = account
        return user_id

    def names(self) -> set[str]:
        return {row.login_name for row in self.rows.values()}


def record(login_name: object = "alice", password: object = "pw-1", role: object = "CLIENT", **extra: object) -> dict:
    return {"login_name": login_name, "password": password, "role_code": role, **extra}


def indexes(report: ImportReport) -> list[int]:
    return sorted([c.index for c in report.created] + [r.index for r in report.rejected] + [f.index for f in report.failed])


def reasons(items: tuple[Rejected, ...] | tuple[Failed, ...]) -> dict[int, str]:
    return {item.index: item.reason for item in items}


# --------------------------------------------------------------------------- example-based tests


def test_tc01_valid_batch_is_saved_with_normalized_names_and_one_role() -> None:
    writer, hasher = FakeWriter(), FakeHasher()
    report = import_accounts(
        [record("  alice\t", role="CLIENT"), record("bob", role="WORKER"), record("carol", role="ADMIN", status="DISABLED")],
        writer,
        hasher,
    )
    assert [c.index for c in report.created] == [0, 1, 2]
    assert report.rejected == () and report.failed == ()
    stored = {row.login_name: (row.role_code, row.status) for row in writer.rows.values()}
    assert stored == {"alice": ("CLIENT", "ACTIVE"), "bob": ("WORKER", "ACTIVE"), "carol": ("ADMIN", "DISABLED")}
    assert all(row.password_hash.startswith("fake$") for row in writer.rows.values())


@pytest.mark.parametrize(
    ("bad", "reason"),
    [
        (["not", "a", "mapping"], RejectReason.INVALID_RECORD),
        (None, RejectReason.INVALID_RECORD),
        (record(id="not-a-uuid"), RejectReason.INVALID_ID),
        (record(login_name=" \t\r\n"), RejectReason.INVALID_LOGIN_NAME),
        (record(login_name="a" * 129), RejectReason.INVALID_LOGIN_NAME),
        (record(login_name="bad" + chr(0) + "name"), RejectReason.INVALID_LOGIN_NAME),
        (record(login_name=42), RejectReason.INVALID_LOGIN_NAME),
        ({"password": "x", "role_code": "CLIENT"}, RejectReason.INVALID_LOGIN_NAME),
        (record(password=""), RejectReason.INVALID_PASSWORD),
        (record(password=None), RejectReason.INVALID_PASSWORD),
        (record(password="ab" + chr(0xD800)), RejectReason.INVALID_PASSWORD),
        (record(role="client"), RejectReason.INVALID_ROLE),
        (record(role="ROOT"), RejectReason.INVALID_ROLE),
        (record(status="active"), RejectReason.INVALID_STATUS),
    ],
)
def test_tc02_invalid_record_is_rejected_without_hashing_and_does_not_block_valid_ones(bad: object, reason: RejectReason) -> None:
    """Negative test: the bad record is rejected with its reason; the valid records around it are saved."""
    writer, hasher = FakeWriter(), FakeHasher()
    report = import_accounts([record("first"), bad, record("last")], writer, hasher)
    assert reasons(report.rejected) == {1: reason}
    assert [c.index for c in report.created] == [0, 2]
    assert writer.names() == {"first", "last"}
    assert hasher.calls == 2  # the invalid record was never hashed


def test_tc03_duplicate_after_normalization_first_valid_record_wins() -> None:
    writer = FakeWriter()
    report = import_accounts(
        [record("dup", role="NOPE"), record(" dup"), record("dup\t"), record("other")], writer, FakeHasher()
    )
    assert reasons(report.rejected) == {0: RejectReason.INVALID_ROLE, 2: RejectReason.DUPLICATE_IN_BATCH}
    assert [c.index for c in report.created] == [1, 3]
    assert writer.names() == {"dup", "other"}


def test_tc04_supplied_uuid_is_kept() -> None:
    wanted = UUID("6f1c2d3e-4a5b-4c6d-8e7f-9a0b1c2d3e4f")
    writer = FakeWriter()
    report = import_accounts([record(id=str(wanted)), record("bob", id=None)], writer, FakeHasher())
    assert report.created[0] == Created(0, wanted)
    assert len(report.created) == 2 and report.created[1].user_id != wanted


def test_tc05_existing_name_fails_and_rerun_creates_nothing() -> None:
    """NFR-3: importing the same batch twice does not duplicate accounts."""
    writer, batch = FakeWriter(), [record("alice"), record("bob")]
    import_accounts(batch, writer, FakeHasher())
    second = import_accounts(batch, writer, FakeHasher())
    assert second.created == ()
    assert reasons(second.failed) == {0: FailReason.LOGIN_NAME_TAKEN, 1: FailReason.LOGIN_NAME_TAKEN}
    assert len(writer.rows) == 2


def test_tc06_failure_path_persistence_error_is_never_reported_as_created() -> None:
    """Failure path for the core risk: the writer fails, so the record must be ``failed``."""
    writer = FakeWriter(fail=lambda account: RuntimeError("commit failed") if account.login_name == "boom" else None)
    report = import_accounts([record("ok-1"), record("boom"), record("ok-2")], writer, FakeHasher())
    assert reasons(report.failed) == {1: FailReason.PERSISTENCE_ERROR}
    assert [c.index for c in report.created] == [0, 2]
    assert {c.user_id for c in report.created} == set(writer.rows)


def test_tc07_store_unavailable_stops_the_batch_and_saves_nothing_after_it() -> None:
    writer = FakeWriter(fail=lambda account: AccountStoreUnavailable() if account.login_name == "down" else None)
    report = import_accounts([record("a"), record("down"), record("b"), record("bad", role="x"), record("c")], writer, FakeHasher())
    assert [c.index for c in report.created] == [0]
    assert reasons(report.failed) == {1: FailReason.DB_UNAVAILABLE, 2: FailReason.DB_UNAVAILABLE, 4: FailReason.DB_UNAVAILABLE}
    assert reasons(report.rejected) == {3: RejectReason.INVALID_ROLE}
    assert writer.calls == 2  # nothing is written after the store went down


def test_tc08_busy_hasher_is_a_failure_not_a_data_error() -> None:
    hasher = ScryptPasswordHasher(profile=ScryptProfile(n=2**10, r=8, p=1), max_concurrent=1, acquire_timeout_seconds=0.01)
    hasher._slots.acquire()  # simulate another request holding the only slot
    try:
        report = import_accounts([record("alice")], FakeWriter(), hasher)
    finally:
        hasher._slots.release()
    assert reasons(report.failed) == {0: FailReason.HASHER_BUSY}
    assert report.created == ()


def test_tc09_report_and_logs_never_contain_passwords_or_hashes(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    secret = "s3cret-password-value"
    writer = FakeWriter()
    report = import_accounts([record("alice", password=secret), record("x", role="bad", password=secret + "2")], writer, FakeHasher())
    stored_hash = next(iter(writer.rows.values())).password_hash
    text = repr(report) + caplog.text + repr(next(iter(writer.rows.values())))
    assert secret not in text and stored_hash not in text


def test_tc10_empty_batch_returns_an_empty_report() -> None:
    assert import_accounts([], FakeWriter(), FakeHasher()) == ImportReport((), (), ())


# --------------------------------------------------------------------------- property-based tests

TRIM = st.text(alphabet=" \t\r\n", max_size=3)
BASES = st.sampled_from(["alice", "bob", "Bob", "carol", "đức", "e" * 128])
PASSWORDS = st.text(alphabet=st.characters(blacklist_categories=("Cs",)), min_size=1, max_size=12)
ROLES = st.sampled_from(["CLIENT", "WORKER", "ADMIN"])


@dataclass(frozen=True)
class Generated:
    record: object
    valid: bool
    base: str | None  # the normalized login name the generator intended (valid records only)


@st.composite
def valid_records(draw: st.DrawFn) -> Generated:
    base = draw(BASES)
    raw = draw(TRIM) + base + draw(TRIM)
    fields = {"login_name": raw, "password": draw(PASSWORDS), "role_code": draw(ROLES)}
    if draw(st.booleans()):
        fields["status"] = draw(st.sampled_from(["ACTIVE", "DISABLED"]))
    return Generated(fields, True, base)


@st.composite
def invalid_records(draw: st.DrawFn) -> Generated:
    good = draw(valid_records()).record
    corruption = draw(
        st.sampled_from(
            ["not_mapping", "empty_name", "long_name", "nul_name", "no_password", "surrogate_password", "bad_role", "bad_status", "bad_id"]
        )
    )
    bad: object = dict(good)
    if corruption == "not_mapping":
        bad = draw(st.sampled_from([None, 7, "alice", ["alice", "pw", "CLIENT"]]))
    elif corruption == "empty_name":
        bad["login_name"] = draw(TRIM)
    elif corruption == "long_name":
        bad["login_name"] = "x" * draw(st.integers(129, 200))
    elif corruption == "nul_name":
        bad["login_name"] = "a" + chr(0) + "b"
    elif corruption == "no_password":
        bad["password"] = draw(st.sampled_from(["", None, 123]))
    elif corruption == "surrogate_password":
        bad["password"] = "p" + chr(draw(st.integers(0xD800, 0xDFFF)))
    elif corruption == "bad_role":
        bad["role_code"] = draw(st.sampled_from(["client", "ROOT", "", None, "CLIENT "]))
    elif corruption == "bad_status":
        bad["status"] = draw(st.sampled_from(["active", "LOCKED", "", None]))
    else:
        bad["id"] = draw(st.sampled_from(["", "123", "not-a-uuid"]))
    return Generated(bad, False, None)


BATCHES = st.lists(st.one_of(valid_records(), invalid_records()), max_size=25)


def expected_created_indexes(batch: list[Generated]) -> dict[int, str]:
    """Oracle from the generator: first VALID occurrence of each base name is created."""
    seen: set[str] = set()
    expected: dict[int, str] = {}
    for index, item in enumerate(batch):
        if item.valid and item.base not in seen:
            seen.add(item.base)
            expected[index] = item.base
    return expected


@PROPERTY_SETTINGS
@given(BATCHES)
def test_p1_report_is_a_partition_of_the_input_positions(batch: list[Generated]) -> None:
    report = import_accounts([g.record for g in batch], FakeWriter(), FakeHasher())
    assert indexes(report) == list(range(len(batch)))


@PROPERTY_SETTINGS
@given(BATCHES)
def test_p2_every_valid_record_is_saved_wherever_the_bad_records_are(batch: list[Generated]) -> None:
    writer = FakeWriter()
    report = import_accounts([g.record for g in batch], writer, FakeHasher())
    expected = expected_created_indexes(batch)
    assert {c.index for c in report.created} == set(expected)
    assert writer.names() == set(expected.values())
    invalid = {i for i, g in enumerate(batch) if not g.valid}
    assert invalid <= {r.index for r in report.rejected}


@PROPERTY_SETTINGS
@given(BATCHES, st.sets(BASES), st.sampled_from([RuntimeError, LoginNameTaken, ValueError]))
def test_p3_created_if_and_only_if_committed(batch: list[Generated], failing: set[str], error: type[Exception]) -> None:
    """The VT-088 invariant under random persistence failures."""
    writer = FakeWriter(fail=lambda account: error() if account.login_name in failing else None)
    report = import_accounts([g.record for g in batch], writer, FakeHasher())
    assert {c.user_id for c in report.created} == set(writer.rows)
    for created in report.created:
        assert writer.rows[created.user_id].login_name == batch[created.index].base
    expected = expected_created_indexes(batch)
    assert {c.index for c in report.created} == {i for i, name in expected.items() if name not in failing}
    assert {f.index for f in report.failed} == {i for i, name in expected.items() if name in failing}


@PROPERTY_SETTINGS
@given(st.lists(valid_records(), max_size=12), st.lists(invalid_records(), max_size=12), st.randoms(use_true_random=False))
def test_p4_adding_bad_records_anywhere_does_not_change_what_is_saved(valid, invalid, rnd) -> None:
    """Metamorphic: interleaving invalid records at random positions keeps the saved set identical."""
    alone = FakeWriter()
    import_accounts([g.record for g in valid], alone, FakeHasher())
    mixed_batch = list(valid)
    for item in invalid:
        mixed_batch.insert(rnd.randint(0, len(mixed_batch)), item)
    mixed = FakeWriter()
    report = import_accounts([g.record for g in mixed_batch], mixed, FakeHasher())
    assert mixed.names() == alone.names()
    assert {r.index for r in report.rejected} >= {i for i, g in enumerate(mixed_batch) if not g.valid}


@PROPERTY_SETTINGS
@given(BATCHES)
def test_p5_stored_names_are_normalized_unique_and_secrets_never_leak(batch: list[Generated]) -> None:
    writer = FakeWriter()
    report = import_accounts([g.record for g in batch], writer, FakeHasher())
    names = [row.login_name for row in writer.rows.values()]
    assert len(names) == len(set(names))
    assert all(name == name.strip(" \t\r\n") and 0 < len(name) <= 128 for name in names)
    shown = repr(report)
    for row in writer.rows.values():
        assert row.password_hash not in shown
    for item in batch:
        password = item.record.get("password") if isinstance(item.record, dict) else None
        if isinstance(password, str) and len(password) >= 4:
            assert password not in shown


@PROPERTY_SETTINGS
@given(st.lists(valid_records(), min_size=1, max_size=15), st.data())
def test_p6_store_outage_stops_writing_and_nothing_after_it_is_created(valid, data) -> None:
    expected = expected_created_indexes(valid)
    if not expected:
        return
    down_at = data.draw(st.sampled_from(sorted(expected)))
    writes_before = sorted(i for i in expected if i < down_at)
    down_name = expected[down_at]
    writer = FakeWriter(fail=lambda account: AccountStoreUnavailable() if account.login_name == down_name else None)
    report = import_accounts([g.record for g in valid], writer, FakeHasher())
    assert [c.index for c in report.created] == writes_before
    assert {f.index for f in report.failed} == {i for i in expected if i >= down_at}
    assert all(f.reason == FailReason.DB_UNAVAILABLE for f in report.failed)
    assert writer.calls == len(writes_before) + 1


def test_writer_protocol_is_satisfied_by_the_fake() -> None:
    writer: AccountWriter = FakeWriter()
    assert callable(writer.create_account)
