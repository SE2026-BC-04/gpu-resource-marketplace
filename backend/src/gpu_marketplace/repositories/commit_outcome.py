"""Conservative PostgreSQL COMMIT error classification.

Only SQLSTATEs that establish a failed transaction are treated as a definite
rollback. PostgreSQL's ``40003`` (``statement_completion_unknown``) is
deliberately excluded from class 40 and must stay an unknown COMMIT outcome.
"""

from __future__ import annotations


_DEFINITE_TRANSACTION_ROLLBACK_SQLSTATES = frozenset(
    {"40000", "40001", "40002", "40P01"}
)


def is_definite_commit_rollback(sqlstate: str | None) -> bool:
    """Return whether PostgreSQL proves that a failed COMMIT did not commit.

    Integrity-constraint violations (class 23), including deferred constraints
    raised at COMMIT, and the enumerated transaction-rollback conditions are
    definite aborts. Unknown and future codes are handled as uncertain.
    """
    if not isinstance(sqlstate, str) or len(sqlstate) != 5:
        return False
    return sqlstate.startswith("23") or sqlstate in _DEFINITE_TRANSACTION_ROLLBACK_SQLSTATES
