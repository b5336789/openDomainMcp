import json

import pytest

from opendomainmcp.tasks.store import TaskStore


def test_create_list_ordering_and_persistence(tmp_path):
    s = TaskStore(tmp_path)
    a = s.create("ingest", "A", "c", {"path": "/a"})
    b = s.create("synthesize", "B", "c", {})
    s.update(a.id, status="done")
    # reload from disk (new instance) -> persisted
    s2 = TaskStore(tmp_path)
    ids = [t.id for t in s2.list()]
    assert ids[0] == b.id          # queued before terminal
    assert a.id in ids
    assert s2.get(a.id).status == "done"


def test_next_queued_is_oldest(tmp_path):
    s = TaskStore(tmp_path)
    a = s.create("ingest", "A", "c", {})
    s.create("ingest", "B", "c", {})
    assert s.next_queued().id == a.id


def test_children_names_and_derived_status(tmp_path):
    s = TaskStore(tmp_path)
    t = s.create("ingest", "A", "c", {})
    s.set_children_names(t.id, ["f0", "f1", "f2", "f3"])
    s.update(t.id, status="running", done=2,
             failures=[{"name": "f1", "status": "skipped"}])
    page = s.read_children(t.id, offset=0, limit=10)
    assert page["total"] == 4
    by_name = {c["name"]: c["status"] for c in page["children"]}
    assert by_name == {"f0": "done", "f1": "skipped", "f2": "running", "f3": "pending"}


def test_read_children_pagination(tmp_path):
    s = TaskStore(tmp_path)
    t = s.create("ingest", "A", "c", {})
    s.set_children_names(t.id, [f"f{i}" for i in range(250)])
    page = s.read_children(t.id, offset=100, limit=50)
    assert page["total"] == 250
    assert [c["name"] for c in page["children"]][:2] == ["f100", "f101"]
    assert len(page["children"]) == 50


def test_clear_finished_keeps_active(tmp_path):
    s = TaskStore(tmp_path)
    a = s.create("ingest", "A", "c", {})
    b = s.create("ingest", "B", "c", {})
    s.update(a.id, status="done")
    assert s.clear_finished() == 1
    remaining = [t.id for t in s.list()]
    assert remaining == [b.id]


def test_load_rejects_unknown_persisted_status(tmp_path):
    (tmp_path / "tasks.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "bad",
                        "type": "ingest",
                        "title": "Bad",
                        "collection": "c",
                        "status": "mystery",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown task status"):
        TaskStore(tmp_path)


def test_transition_validates_status_and_records_metadata(tmp_path):
    s = TaskStore(tmp_path)
    t = s.create("ingest", "A", "c", {})

    s.transition(t.id, "running", started_at=123.0)
    running = s.get(t.id)
    assert running.status == "running"
    assert running.started_at == 123.0
    assert running.last_transition == "queued_to_running"
    assert running.finished_at is None

    s.transition(t.id, "done", result={"ok": True})
    done = s.get(t.id)
    assert done.status == "done"
    assert done.result == {"ok": True}
    assert done.last_transition == "running_to_done"
    assert done.finished_at is not None

    with pytest.raises(ValueError, match="unknown task status"):
        s.transition(t.id, "bogus")


def test_update_validates_status(tmp_path):
    s = TaskStore(tmp_path)
    t = s.create("ingest", "A", "c", {})

    with pytest.raises(ValueError, match="unknown task status"):
        s.update(t.id, status="bogus")


def test_mark_recovered_records_recovery_metadata(tmp_path):
    s = TaskStore(tmp_path)
    t = s.create("ingest", "A", "c", {})
    s.update(t.id, status="running", cancel_requested=True, recovery_count=1)

    recovered = s.mark_recovered(t.id)

    assert recovered is True
    row = s.get(t.id)
    assert row.status == "queued"
    assert row.cancel_requested is False
    assert row.recovery_count == 2
    assert row.recovered_at is not None
    assert row.last_transition == "recovered_running_to_queued"


def test_retry_clones_retryable_task_with_original_reference(tmp_path):
    s = TaskStore(tmp_path)
    original = s.create("ingest", "Original", "c", {"path": "/src"})
    s.transition(
        original.id,
        "error",
        error="RuntimeError('boom')",
        error_type="RuntimeError",
        error_message="boom",
    )

    retry = s.retry(original.id)

    assert retry.id != original.id
    assert retry.type == original.type
    assert retry.title == original.title
    assert retry.collection == original.collection
    assert retry.params == original.params
    assert retry.status == "queued"
    assert retry.result["retry_of"] == original.id
    assert retry.result["retry_status"] == "error"


def test_retry_rejects_non_retryable_task(tmp_path):
    s = TaskStore(tmp_path)
    queued = s.create("ingest", "Queued", "c", {})
    done = s.create("ingest", "Done", "c", {})
    s.transition(done.id, "done")

    with pytest.raises(ValueError, match="not retryable"):
        s.retry(queued.id)
    with pytest.raises(ValueError, match="not retryable"):
        s.retry(done.id)
