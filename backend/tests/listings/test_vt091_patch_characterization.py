"""VT-091: characterize the real router/service with the existing fake UoW.

This freezes the approved last-commit-wins contract; it is not a PostgreSQL race
test or evidence that published Listings already provide an autosave feature.
"""

from dataclasses import replace

import pytest


@pytest.mark.parametrize(
    ("field", "older", "newer"),
    [
        ("mock_price_per_hour", "10.00", "20.00"),
        ("gpu_model", "OLDER EDIT", "NEWER EDIT"),
    ],
)
def test_vt18_real_patch_accepts_older_edit_when_it_arrives_last(
    env, field, older, newer
):
    # Both payloads are prepared before delivery. No jobs block hardware edits.
    env.store.job_rows[env.store.l1.id] = []
    env.store.records[env.store.l1.id] = replace(env.store.l1, allocated_gpu_count=0)
    path = f"/api/v1/gpu-listings/{env.store.l1.id}"
    older_snapshot, newer_snapshot = {field: older}, {field: newer}

    newer_response = env.client.patch(path, json=newer_snapshot)
    assert newer_response.status_code == 200
    assert newer_response.json()[field] == newer

    delayed_older_response = env.client.patch(path, json=older_snapshot)
    assert delayed_older_response.status_code == 200
    assert delayed_older_response.json()[field] == older

    restored = env.client.get(path)
    assert restored.status_code == 200
    assert restored.json()[field] == older
    assert env.store.commits == 2
    assert len(env.store.audit_events) == 2
    # Assert the application layer issued both writes, not a coursework model.
    writes = [value for event, value in env.store.events if event == "update"]
    assert len(writes) == 2
    assert str(writes[0][field]) == newer
    assert str(writes[1][field]) == older
