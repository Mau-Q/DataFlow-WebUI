"""Backend completion hook: one idempotent generated dataset per successful run."""
import copy
from pathlib import Path
from types import SimpleNamespace
from app.services.data_library import DataLibrary, LibraryError
from app.services.resource_store import ResourceStore
from app.services.task_results import TaskResults


def freeze_collection_target(config, library):
    # Workers must use the submitter's library, including isolated/custom roots.
    config.setdefault('execution_options', {})['collection_library_root'] = str(library.root.resolve())


def collect_completed_result(config, result, execution_path):
    if result.get('status') != 'completed' or not execution_path:
        return result
    output = result.setdefault('output', {})
    task_id = result['task_id']
    try:
        stored = ResourceStore(execution_path).read().get('tasks', {}).get(task_id)
        if not stored or stored.get('status') == 'cancelled':
            output['auto_collection'] = dict(status='skipped', reason='任务记录不存在或已取消')
            return result
        root = config.get('execution_options', {}).get('collection_library_root')
        if not root:
            raise LibraryError('未固定生成数据集数据库位置，自动收录未执行')
        library = DataLibrary(Path(root))
        task = {**copy.deepcopy(stored), **result, 'pipeline_config': config}
        service = TaskResults(SimpleNamespace(data_library=library, task_registry=SimpleNamespace(get=lambda _: task)))
        try:
            item, rows, _ = service._file(task)
            service._contract(rows)
        except LibraryError as exc:
            output['auto_collection'] = dict(status='skipped', reason=str(exc))
            return result
        name = f"{stored.get('name') or 'Pipeline'} · {task_id}"[:240]
        collected = service.collect(task_id, item['sha256'], name=name)
        output['auto_collection'] = dict(status='collected', dataset_id=collected['id'], name=collected['name'],
                                         row_count=collected['row_count'], added=collected['added'], reused=collected['reused'])
    except Exception as exc:
        # Generation is still complete; expose database failures separately.
        output['auto_collection'] = dict(status='failed', reason=str(exc))
        result.setdefault('logs', []).append(f'自动收录失败: {type(exc).__name__}: {exc}')
    return result
