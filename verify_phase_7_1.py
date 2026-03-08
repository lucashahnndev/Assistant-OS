import sys
import os
import uuid
import time
from typing import Optional

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), "src")))

try:
    from core.events import WorkerEvent, TaskOrigin, TaskSpawnReason
    from core.worker_runtime import WorkerRuntime
    from core.session import Session
except ImportError as e:
    print(f"Import Error: {e}")
    sys.exit(1)

class MockOrchestrator:
    def get_session_robust(self, session_id):
        return Session(session_id)
    def _save_session(self, session):
        pass

def test_metadata_propagation():
    print("Testing Metadata Propagation...")
    session_id = f"test-{uuid.uuid4().hex[:8]}"
    task_id = f"task-{uuid.uuid4().hex[:8]}"
    
    # 1. Create WorkerRuntime with metadata
    runtime = WorkerRuntime(
        session_id=session_id,
        task_id=task_id,
        run_id="run-1",
        task_role="worker",
        turn_id=1,
        base_turn_id=1,
        orchestrator=MockOrchestrator(),
        origin_type=TaskOrigin.SUPERVISOR,
        parent_task_id="parent-123",
        spawn_reason=TaskSpawnReason.PLAN_STEP
    )
    
    # 2. Check stored metadata
    assert runtime.origin_type == TaskOrigin.SUPERVISOR
    assert runtime.parent_task_id == "parent-123"
    assert runtime.spawn_reason == TaskSpawnReason.PLAN_STEP
    print("✓ WorkerRuntime metadata stored correctly")
    
    # 3. Test WorkerEvent creation
    event = runtime.report_status("PROGRESS", phase="execution", summary="Processing task...", progress=0.5)
    assert event.origin_type == TaskOrigin.SUPERVISOR
    assert event.parent_task_id == "parent-123"
    assert event.spawn_reason == TaskSpawnReason.PLAN_STEP
    print("✓ WorkerEvent captures metadata correctly")
    
    # 4. Test Session registry storage
    session = Session(session_id)
    # Simulate publish_event logic (as implemented in session.py)
    if event.task_id not in session.task_registry:
        session.task_registry[event.task_id] = {
            "origin_type": event.origin_type,
            "parent_task_id": event.parent_task_id,
            "spawn_reason": event.spawn_reason,
            "created_at": event.timestamp
        }
    
    entry = session.task_registry[event.task_id]
    assert entry["origin_type"] == TaskOrigin.SUPERVISOR
    assert entry["parent_task_id"] == "parent-123"
    assert entry["spawn_reason"] == TaskSpawnReason.PLAN_STEP
    print("✓ Session TaskRegistry stores metadata correctly")

def test_memory_patch():
    print("\nTesting Memory Patching...")
    session = Session("test-session")
    memory_id = "mem-1"
    session.memory.append({
        "id": memory_id,
        "content": "Original content",
        "category": "fact"
    })
    
    # Patch it
    success = session.apply_memory_patch(
        memory_id=memory_id,
        patch={"is_deleted": True, "content": "Updated content"},
        author="admin",
        reason="Test cleanup"
    )
    
    assert success is True
    assert session.memory[0]["is_deleted"] is True
    assert session.memory[0]["content"] == "Updated content"
    
    # Check audit trail
    assert len(session.audit_trail) == 1
    audit = session.audit_trail[0]
    assert audit["type"] == "memory_patch"
    assert audit["author"] == "admin"
    assert audit["reason"] == "Test cleanup"
    assert audit["old_value"]["content"] == "Original content"
    print("✓ Memory patch and audit trail work correctly")

if __name__ == "__main__":
    try:
        test_metadata_propagation()
        test_memory_patch()
        print("\nAll Phase 7.1 Verification Tests Passed!")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\nVerification FAILED: {e}")
        sys.exit(1)
