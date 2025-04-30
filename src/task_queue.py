"""
Task queue management extracted from main.py for better readability.
"""
import time
import uuid
import logging
import threading
from collections import deque
from datetime import datetime
from typing import Dict, Any, Callable, Optional, List

logger = logging.getLogger(__name__)

class TaskInfo:
    def __init__(self, task_id: str, task_type: str, status: str = "queued",
                 params: Dict[str, Any] = None):
        self.id = task_id
        self.type = task_type
        self.status = status
        self.params = params or {}
        self.created_at = datetime.utcnow()
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.error: Optional[str] = None
        self.result: Optional[Any] = None
        self.progress: int = 0
        self.logs: List[Dict[str, Any]] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error": self.error,
            "progress": self.progress,
            "logs": self.logs,
        }

    def log(self, message: str, level: str = "INFO") -> None:
        entry = {"timestamp": datetime.utcnow().isoformat(), "level": level, "message": message}
        self.logs.append(entry)

    def start(self) -> None:
        self.status = "running"
        self.started_at = datetime.utcnow()
        self.log(f"Task {self.id} started")

    def complete(self, result: Any = None) -> None:
        self.status = "completed"
        self.completed_at = datetime.utcnow()
        self.result = result
        self.progress = 100
        self.log(f"Task {self.id} completed")

    def fail(self, error: str) -> None:
        self.status = "failed"
        self.completed_at = datetime.utcnow()
        self.error = error
        self.log(f"Task {self.id} failed: {error}", "ERROR")

    def update_progress(self, progress: int) -> None:
        self.progress = min(max(progress, 0), 100)
        self.log(f"Progress updated: {self.progress}%")

class TaskQueue:
    def __init__(self, max_concurrent: int = 3):
        self.tasks: Dict[str, TaskInfo] = {}
        self.queue = deque()
        self.max_concurrent = max_concurrent
        self.running = 0
        self.lock = threading.Lock()
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()

    def add_task(self, task_type: str, task_func: Callable, params: Dict[str, Any] = None) -> str:
        task_id = str(uuid.uuid4())
        info = TaskInfo(task_id, task_type, params=params)
        with self.lock:
            self.tasks[task_id] = info
            self.queue.append((task_id, task_func, params or {}))
        return task_id

    def get_task_info(self, task_id: str) -> Optional[Dict[str, Any]]:
        if task_id in self.tasks:
            return self.tasks[task_id].to_dict()
        return None

    def get_all_tasks(self) -> List[Dict[str, Any]]:
        return [t.to_dict() for t in self.tasks.values()]

    def _worker_loop(self) -> None:
        while True:
            if not self.queue or self.running >= self.max_concurrent:
                time.sleep(0.5)
                continue
            with self.lock:
                task_id, task_func, params = self.queue.popleft()
                self.running += 1
            self._execute_task(task_id, task_func, params)

    def _execute_task(self, task_id: str, task_func: Callable, params: Dict[str, Any]) -> None:
        info = self.tasks.get(task_id)
        if not info:
            with self.lock:
                self.running -= 1
            return
        info.start()
        try:
            result = task_func(**params)
            info.complete(result)
        except Exception as e:
            info.fail(str(e))
            logger.error(f"Task {task_id} failed", exc_info=True)
        finally:
            with self.lock:
                self.running -= 1
