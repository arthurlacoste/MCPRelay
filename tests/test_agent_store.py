from agent_manager.models import AGENT_STATUS_COMPLETED, AGENT_STATUS_QUEUED, AgentSpec
from agent_manager.store import AgentStore


def test_agent_store_creates_schema_and_queued_agent(tmp_path):
    store = AgentStore(tmp_path / "agents.sqlite", tmp_path)

    record = store.create_agent("agt_test", AgentSpec(prompt="hello", purpose="unit"))

    assert record.agent_id == "agt_test"
    assert record.status == AGENT_STATUS_QUEUED
    assert (tmp_path / "agents.sqlite").exists()
    assert (tmp_path / "runs" / "agt_test" / "input.json").exists()


def test_agent_store_updates_status_and_lists_by_status(tmp_path):
    store = AgentStore(tmp_path / "agents.sqlite", tmp_path)
    store.create_agent("agt_test", AgentSpec(prompt="hello"))

    store.update_status("agt_test", AGENT_STATUS_COMPLETED, exit_code=0, completed=True)

    assert store.get_agent("agt_test").status == AGENT_STATUS_COMPLETED
    assert [record.agent_id for record in store.list_agents(status=AGENT_STATUS_COMPLETED)] == ["agt_test"]


def test_agent_store_stores_parent_id_on_retry(tmp_path):
    store = AgentStore(tmp_path / "agents.sqlite", tmp_path)

    store.create_agent("agt_parent", AgentSpec(prompt="parent"))
    child = store.create_agent("agt_child", AgentSpec(prompt="child"), parent_id="agt_parent")

    assert child.parent_id == "agt_parent"


def test_agent_store_tails_logs(tmp_path):
    store = AgentStore(tmp_path / "agents.sqlite", tmp_path)
    store.create_agent("agt_test", AgentSpec(prompt="hello"))
    log_path = store.run_dir("agt_test") / "stdout.log"
    log_path.write_text("\n".join(str(i) for i in range(10)), encoding="utf-8")

    assert store.tail_log("agt_test", "stdout", tail=3) == "7\n8\n9"
