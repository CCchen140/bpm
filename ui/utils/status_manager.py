from PyQt6.QtCore import QObject, pyqtSignal, QMutex
from collections import OrderedDict
import time

class StatusManager(QObject):
    """
    Status Manager to handle application tasks and update the status bar.
    Implements a queue-based display strategy (earliest task first).
    """
    _instance = None
    
    # Signal emitted when status text changes: (current_message, is_idle)
    status_changed = pyqtSignal(str, bool)
    
    def __init__(self):
        super().__init__()
        self._tasks = OrderedDict() # id -> (message, timestamp)
        self._task_counter = 0
        self._lock = QMutex()
        
    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
        
    def start_task(self, message):
        """Start a task and return its ID"""
        self._lock.lock()
        try:
            task_id = self._task_counter
            self._task_counter += 1
            self._tasks[task_id] = (message, time.time())
            self._update_status()
            return task_id
        finally:
            self._lock.unlock()
        
    def update_task(self, task_id, message):
        """更新任务消息"""
        self._lock.lock()
        try:
            if task_id in self._tasks:
                self._tasks[task_id] = (message, self._tasks[task_id][1])
                self._update_status()
        finally:
            self._lock.unlock()

    def finish_task(self, task_id):
        """Finish a task by ID"""
        self._lock.lock()
        try:
            if task_id in self._tasks:
                del self._tasks[task_id]
                self._update_status()
        finally:
            self._lock.unlock()
            
    def _update_status(self):
        # Note: This method is called within the lock, so no need to lock again
        if not self._tasks:
            self.status_changed.emit("就绪", True)
            return
            
        # Get the first (earliest) task
        # OrderedDict keys are ordered by insertion
        first_task = next(iter(self._tasks.values()))
        message = first_task[0]
        self.status_changed.emit(message, False)
