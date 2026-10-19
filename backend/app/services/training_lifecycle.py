"""SFT membership, provenance and immutable, portable release bundles."""
import copy
import io
import json
import re
import zipfile
from pathlib import Path
from app.services.data_library import LibraryError, _hash, _json_bytes, _now, _parse_json


class TrainingLifecycle:
    def __init__(self, library):
        self.lib = library
        self.releases = library.root / 'releases'
        self.releases.mkdir(exist_ok=True)

    def _members(self, rec):
        ids = rec.setdefault('sample_ids', [])
        while len(ids) < len(rec['rows']):
            i = len(ids)
            ids.append('sample_' + _hash(_json_bytes([rec['id'], i, rec['rows'][i], rec.get('updated_at')])))
        rec.setdefault('sample_sources', {})
        return ids

    def view(self, draft_id, offset=0, limit=20):
        rec = self.lib._get('drafts', draft_id)
        ids = self._members(rec)
        return dict(self.lib._summary(rec), rows=rec['rows'][offset:offset+limit],
                    sample_ids=ids[offset:offset+limit], offset=offset, limit=limit)

    def _validate(self, rec):
        refs = set()
        for i, row in enumerate(rec['rows'], 1):
            try:
                refs.update(self.lib._validate_row(row, rec['modality'], rec.get('training_type', 'sft')))
            except LibraryError as exc:
                raise LibraryError(f'第 {i} 条样本: {exc}') from exc
        media = {}
        for ref in refs:
            mid = rec['media_bindings'].get(ref)
            if not mid:
                raise LibraryError(f'媒体缺失: {ref}')
            path, mat = self.lib.material_file(mid)
            if mat['kind'] != 'image':
                raise LibraryError(f'媒体不是图片: {ref}')
            media[ref] = (path, mat)
        return media

    def edit(self, draft_id, sample_id, row=None, delete=False):
        with self.lib._writing():
            rec = self.lib._get('drafts', draft_id)
            ids = self._members(rec)
            if sample_id not in ids:
                raise LibraryError('样本不存在', 404)
            index = ids.index(sample_id)
            if delete:
                del rec['rows'][index]
                del ids[index]
                rec['sample_sources'].pop(sample_id, None)
            else:
                rec['rows'][index] = copy.deepcopy(row)
                self._validate(rec)
            rec['updated_at'] = _now()
            self.lib._atomic(self.lib._path('drafts', draft_id), _json_bytes(rec))
        return self.view(draft_id)

    def map_fields(self, draft_id, mapping):
        if not isinstance(mapping, dict) or set(mapping) != {'instruction', 'input', 'output'} or any(not isinstance(v, str) for v in mapping.values()):
            raise LibraryError('字段映射需要 instruction/input/output 到源字段名；input 可留空')
        with self.lib._writing():
            rec = self.lib._get('drafts', draft_id)
            if rec.get('training_type', 'sft') != 'sft':
                raise LibraryError('instruction/input/output 字段映射仅适用于 SFT')
            self._members(rec)
            for i, row in enumerate(rec['rows'], 1):
                original = copy.deepcopy(row)
                for target, source in mapping.items():
                    if not source and target == 'input':
                        row[target] = ''
                    elif source not in original:
                        raise LibraryError(f'第 {i} 条样本缺少源字段: {source}')
                    else:
                        row[target] = original[source]
            self._validate(rec)
            rec['field_mapping'] = mapping
            rec['updated_at'] = _now()
            self.lib._atomic(self.lib._path('drafts', draft_id), _json_bytes(rec))
        return self.view(draft_id)

    def collect(self, draft_id, task, artifact):
        if task.get('status') != 'completed' or artifact.get('kind') != 'training':
            raise LibraryError('只能收集已完成任务的训练产物')
        path = Path(artifact['path'])
        if not path.is_file() or _hash(path.read_bytes()) != artifact['sha256']:
            raise LibraryError('任务产物缺失或内容已变化', 409)
        rows = [_parse_json(line) for line in path.read_text('utf-8').splitlines() if line.strip()]
        key = task['task_id'] + ':' + artifact['id']
        with self.lib._writing():
            rec = self.lib._get('drafts', draft_id)
            if rec.get('training_type', 'sft') != 'sft':
                raise LibraryError('当前文本生成产物仅能收集到 SFT 草稿')
            ids = self._members(rec)
            if key in rec.get('collections', []):
                raise LibraryError('该任务产物已经收集，未重复写入', 409)
            # Only the training contract enters drafts. Evidence remains in task artifacts.
            existing = {_hash(_json_bytes(r)): sid for r, sid in zip(rec['rows'], ids)}
            added = 0
            for index, row in enumerate(rows):
                self.lib._validate_row(row, rec['modality'], rec.get('training_type', 'sft'))
                digest = _hash(_json_bytes(row))
                sid = existing.get(digest)
                if sid is None:
                    sid = 'sample_' + _hash(_json_bytes([key, index]))[:24]
                    rec['rows'].append(row)
                    ids.append(sid)
                    existing[digest] = sid
                    added += 1
                source = {'task_id': task['task_id'], 'artifact_id': artifact['id'], 'sha256': artifact['sha256'], 'row_index': index}
                rec['sample_sources'].setdefault(sid, []).append(source)
            self._validate(rec)
            rec.setdefault('collections', []).append(key)
            rec['updated_at'] = _now()
            self.lib._atomic(self.lib._path('drafts', draft_id), _json_bytes(rec))
        return dict(self.view(draft_id), added=added)

    def list_releases(self, draft_id):
        self.lib._get('drafts', draft_id)
        return sorted([json.loads(p.read_text('utf-8')) for p in self.releases.glob(f'{draft_id}_v*.json')], key=lambda x: x['version'])

    def _path(self, release_id, suffix):
        if not re.fullmatch(r'ds_[0-9a-f]{32}_v[1-9][0-9]*', release_id):
            raise LibraryError('发布版本不存在', 404)
        return self.releases / (release_id + suffix)

    def _portable(self, row, paths):
        row = copy.deepcopy(row)
        if 'image' in row:
            row['image'] = paths[row['image']]
        if 'images' in row:
            row['images'] = [paths[r] for r in row['images']]
        for message in row.get('messages', []):
            if isinstance(message['content'], list):
                for block in message['content']:
                    if block['type'] == 'image_url':
                        value = block['image_url']
                        if isinstance(value, dict):
                            value['url'] = paths[value['url']]
                        else:
                            block['image_url'] = paths[value]
        return row

    def publish(self, draft_id):
        with self.lib._writing():
            rec = self.lib._get('drafts', draft_id)
            ids = self._members(rec)
            if not rec['rows']:
                raise LibraryError('空草稿不能发布；0 条通过筛选仍可保留为完成任务')
            media = self._validate(rec)
            paths = {ref: f'media/{mat["id"]}{path.suffix.lower()}' for ref, (path, mat) in media.items()}
            rows = [self._portable(row, paths) for row in rec['rows']]
            data = b''.join(_json_bytes(row) + b'\n' for row in rows)
            # Alpaca export is available only when every row has those fields.
            alpaca = None
            if rec['training_type'] == 'sft' and all(all(isinstance(r.get(k), str) and r[k].strip() for k in ('instruction', 'output')) and isinstance(r.get('input',''), str) for r in rows):
                alpaca = b''.join(_json_bytes({k: row.get(k, '') for k in ('instruction', 'input', 'output')}) + b'\n' for row in rows)
            version = len(self.list_releases(draft_id)) + 1
            rid = f'{draft_id}_v{version}'
            manifest = dict(id=rid, draft_id=draft_id, version=version, created_at=_now(), name=rec['name'],
                            modality=rec['modality'], training_type=rec['training_type'], row_count=len(rows),
                            sample_ids=ids, sample_sources=rec['sample_sources'], data_sha256=_hash(data),
                            media={ref: {'material_id': mat['id'], 'path': paths[ref], 'sha256': mat['sha256']} for ref, (_, mat) in media.items()},
                            formats=['jsonl', 'package'] + (['alpaca'] if alpaca is not None else []))
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as bundle:
                bundle.writestr('data.jsonl', data)
                bundle.writestr('manifest.json', _json_bytes(manifest))
                if alpaca is not None:
                    bundle.writestr('alpaca.jsonl', alpaca)
                copied = set()
                for ref, (path, mat) in media.items():
                    if paths[ref] not in copied:
                        content = path.read_bytes()
                        if _hash(content) != mat['sha256']:
                            raise LibraryError(f'发布期间图片变化: {ref}', 409)
                        bundle.writestr(paths[ref], content)
                        copied.add(paths[ref])
            # Metadata is the commit marker; incomplete writes never become listed releases.
            blobs = {'.jsonl': data, '.zip': buffer.getvalue()}
            if alpaca is not None:
                blobs['.alpaca.jsonl'] = alpaca
            written = []
            try:
                for suffix, content in blobs.items():
                    target = self._path(rid, suffix)
                    self.lib._atomic(target, content)
                    written.append(target)
                manifest['files'] = {suffix: _hash(content) for suffix, content in blobs.items()}
                self.lib._atomic(self._path(rid, '.json'), _json_bytes(manifest))
            except Exception:
                for path in written:
                    path.unlink(missing_ok=True)
                raise
            return manifest

    def download(self, release_id, format='package'):
        meta_path = self._path(release_id, '.json')
        if not meta_path.is_file():
            raise LibraryError('发布版本不存在', 404)
        rec = json.loads(meta_path.read_text('utf-8'))
        if format not in rec['formats']:
            raise LibraryError('该版本不支持此导出格式')
        suffix = {'package': '.zip', 'jsonl': '.jsonl', 'alpaca': '.alpaca.jsonl'}[format]
        path = self._path(release_id, suffix)
        if not path.is_file() or _hash(path.read_bytes()) != rec['files'][suffix]:
            raise LibraryError('发布文件缺失或损坏', 409)
        return path

    def fork(self, release_id):
        from app.schemas.data_library import DraftCreate
        package = self.download(release_id)
        with zipfile.ZipFile(package) as bundle:
            meta = json.loads(bundle.read('manifest.json'))
            rows = [_parse_json(s) for s in bundle.read('data.jsonl').decode().splitlines()]
            bindings = {}
            # Reuse only the exact material IDs/hashes in the release, never filenames.
            for item in meta['media'].values():
                material_id = item['material_id']
                path, material = self.lib.material_file(material_id)
                if material['sha256'] != item['sha256']:
                    raise LibraryError('原图片不可用，无法建立新草稿', 409)
                bindings[item['path']] = material_id
        created = self.lib.create_draft(DraftCreate(name=meta['name'] + ' · 新草稿', modality=meta['modality'], training_type=meta.get('training_type', 'sft')))
        with self.lib._writing():
            rec = self.lib._get('drafts', created['id'])
            rec.update(rows=rows, sample_ids=meta['sample_ids'], sample_sources=meta['sample_sources'],
                       media_bindings=bindings, parent_release=release_id)
            self.lib._atomic(self.lib._path('drafts', rec['id']), _json_bytes(rec))
        return self.view(rec['id'])
