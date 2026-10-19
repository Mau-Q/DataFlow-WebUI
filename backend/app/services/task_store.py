"""Atomic per-task merges for API and worker processes."""
from app.services.resource_store import ResourceStore


def patch_task(path, task_id, updates=None, partial_output=None, create=False):
    with ResourceStore(path).writing() as data:
        tasks = data.setdefault('tasks', {})
        if task_id not in tasks and not create:
            return None
        task = tasks.setdefault(task_id, {})
        if task.get('status') == 'cancelled':
            return dict(task)
        task.update(updates or {})
        if partial_output:
            task.setdefault('output', {}).update(partial_output)
        return dict(task)
