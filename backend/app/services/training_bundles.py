"""Portable immutable run inputs. Export never creates a training run."""
import copy
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile
import uuid
import zipfile
import yaml
from app.services.model_training import TrainingError, canonical, digest
from app.services.training_compiler import compile_plan

MAX_FILE=100*1024*1024
MAX_BUNDLE=512*1024*1024


def safe_read(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file():raise TrainingError('输入必须是普通文件，不接受符号链接: '+str(path))
    if path.stat().st_size>MAX_FILE:raise TrainingError('输入过大，请使用显式引用模式')
    return path.read_bytes()


def safe_members(blob):
    try:
        archive=zipfile.ZipFile(io.BytesIO(blob));names=archive.namelist()
        if len(names)!=len(set(names)) or sum(i.file_size for i in archive.infolist())>MAX_BUNDLE:raise TrainingError('包重复成员或解压大小超限')
        result={}
        for info in archive.infolist():
            p=PurePosixPath(info.filename)
            if p.is_absolute() or '..' in p.parts or '\\' in info.filename or stat.S_ISLNK(info.external_attr>>16):raise TrainingError('包包含不安全路径或符号链接')
            if not info.is_dir():result[info.filename]=archive.read(info)
        return result
    except zipfile.BadZipFile as e:raise TrainingError('无效 ZIP 包') from e


def snapshot_source(root, custom_files):
    root=Path(root)
    try:
        commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
        dirty=bool(subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=root))
        tracked=subprocess.check_output(['git','ls-files','-z','src/dataflex','pyproject.toml','setup.py','requirements.txt'],cwd=root).decode().split('\0')
    except (OSError,subprocess.CalledProcessError) as e:raise TrainingError('DataFlex 源码目录不可用，请设置 DATAFLEX_SOURCE_DIR') from e
    files={}
    for name in [*filter(None,tracked),*custom_files]:
        p=PurePosixPath(name)
        if p.is_absolute() or '..' in p.parts or not (name.startswith('src/dataflex/') or name in ['pyproject.toml','setup.py','requirements.txt']):raise TrainingError('自定义源码必须显式位于 src/dataflex 下')
        path=root/name
        if not path.resolve().is_relative_to(root.resolve()):raise TrainingError('源码路径越界')
        if path.suffix not in ['.py','.yaml','.yml','.toml','.txt']:continue
        content=safe_read(path)
        # Fail closed on literal credential assignments, without echoing any value.
        if re.search(rb'(?im)^\s*(?:[\w]*api[_-]?key|[\w]*secret|[\w]*password|[\w]*token)\s*[:=]\s*[\'"][^\'"\s]{8,}[\'"]',content):raise TrainingError('源码包含疑似凭据字面值，请移除后重试')
        files['source/'+name]=content
    if 'source/src/dataflex/cli.py' not in files:raise TrainingError('DataFlex 入口缺失')
    return files,{'commit':commit,'dirty':dirty,'custom_files':custom_files,'files':{k:digest(v) for k,v in files.items()}}


def export_bundle(service, key, options=None):
    options=options or {};record=service.get('plans',key);plan=copy.deepcopy(record['plan']);compiled=compile_plan(service,plan)
    if compiled['checks']['errors']:raise TrainingError('; '.join(compiled['checks']['errors']))
    root=Path(os.environ.get('DATAFLEX_SOURCE_DIR') or Path(__file__).resolve().parents[5].parent/'DataFlex')
    files,source=snapshot_source(root,plan.get('custom_sources',[]))
    source_hash=digest(canonical(source));refs=[];inputs=[];mapping=[]
    train=compiled['train'];info=compiled['dataset_info']
    for i,b in enumerate(plan['data']):
        name='dataset_'+str(i);content=None;sample_ids=None
        if b['kind']=='release':
            from app.services.training_lifecycle import TrainingLifecycle
            lifecycle=TrainingLifecycle(service.library);meta=service.library.db.get('releases',b['ref'])
            if meta.get('modality','text')!=plan['modality'] or meta.get('training_type','sft')!=plan['task']:raise TrainingError(f'data[{i}]: 任务/模态与发布版本不兼容')
            package=lifecycle.download(b['ref']);members=safe_members(safe_read(package))
            content=members.get('data.jsonl') or members.get('train.jsonl')
            if content is None:
                candidates=[k for k in members if k.endswith('.jsonl')]
                if len(candidates)!=1:raise TrainingError('发布包缺少唯一数据文件')
                content=members[candidates[0]]
            sample_ids=meta.get('sample_ids')
            for media,body in members.items():
                if media.startswith('media/'):
                    files['data/'+media]=body
        elif b['kind']=='file':
            path=Path(b['ref']);content=safe_read(path)
            if path.suffix.lower() not in ['.jsonl','.json']:raise TrainingError('仅支持 JSONL/JSON 数据文件')
            if b.get('sha256') and digest(content)!=b['sha256']:raise TrainingError(f'data[{i}]: 文件哈希不匹配')
            if b.get('mode')=='reference':
                refs.append(dict(b,sha256=digest(content)));info[name]['file_name']=str(path.resolve());content=None
        else:
            refs.append(b);continue
        if content is not None:
            try:
                rows=json.loads(content) if content.lstrip().startswith(b'[') else [json.loads(line) for line in content.splitlines() if line.strip()]
                if not isinstance(rows,list) or not all(isinstance(r,dict) for r in rows):raise ValueError('rows')
            except ValueError as e:raise TrainingError(f'data[{i}]: 数据不是 JSON 对象序列') from e
            if plan['modality']=='image_text':
                # Release media are copied, but an unverified messages/media conversion must not silently run.
                raise TrainingError('图文发布结构到 DataFlex 处理器的转换待 G1 适配；当前可保存配置，不导出可执行图文包')
            files['data/'+name+'.jsonl']=b''.join(canonical(r)+b'\n' for r in rows)
            for index,row in enumerate(rows):mapping.append({'dataset':name,'source_index':index,'sample_id':sample_ids[index] if sample_ids and len(sample_ids)==len(rows) else None,'row_sha256':digest(canonical(row)),'preprocessed_index':None})
            inputs.append({'binding':b,'file':'data/'+name+'.jsonl','sha256':digest(files['data/'+name+'.jsonl']),'rows':len(rows)})
    # Snapshot explicitly referenced parameter artifacts, never follow arbitrary directories.
    def rewrite(value,key=''):
        if isinstance(value,dict):return {k:rewrite(v,k) for k,v in value.items()}
        if isinstance(value,list):return [rewrite(v,key) for v in value]
        if isinstance(value,str) and key.endswith(('_path','_file')) and value and key not in ['reference_model_path']:
            p=Path(value)
            if not p.is_absolute():p=root/p
            content=safe_read(p);name='assets/'+digest(content)[:16]+p.suffix;files[name]=content;return name
        return value
    components=rewrite(compiled['components'])
    files.update({'plan.json':canonical(plan),'train.yaml':yaml.safe_dump(train,allow_unicode=True,sort_keys=False).encode(),'components.yaml':yaml.safe_dump(components,allow_unicode=True,sort_keys=False).encode(),'data/dataset_info.json':canonical(info),'sample_map.json':canonical({'mapping':mapping,'preprocessing_mapping':'unknown until processor emits exact identity; packing disabled'}),'source_identity.json':canonical(source),'runner.py':(Path(__file__).parent/'training_runtime/runner.py').read_bytes()})
    files['run.sh']=b'#!/bin/sh\nset -eu\ncd "$(dirname "$0")"\nexec "${DATAFLEX_PYTHON:-python3}" runner.py "$@"\n'
    files['prepare_data.py']=PREPARE_DATA.encode()
    manifest={'schema_version':1,'format':'dataflex-run-bundle','bundle_id':uuid.uuid4().hex,'plan_id':key,'plan_version':record['version'],'source_sha256':source_hash,'source':{'commit':source['commit'],'dirty':source['dirty']},'inputs':inputs,'external_references':refs,'files':{k:digest(v) for k,v in files.items()},'limitations':compiled['checks'].get('warnings',[]),'model_included':False}
    files['manifest.json']=canonical(manifest)
    if sum(map(len,files.values()))>MAX_BUNDLE:raise TrainingError('运行包超过大小限制')
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for name,body in files.items():z.writestr(name,body)
    path=service.root/'bundles'/(manifest['bundle_id']+'.zip');path.parent.mkdir(exist_ok=True);path.write_bytes(out.getvalue())
    return service.put('bundles',{'manifest':manifest,'manifest_sha256':digest(files['manifest.json']),'archive_sha256':digest(out.getvalue()),'path':str(path),'plan_snapshot':plan},key=manifest['bundle_id'])

PREPARE_DATA='''"""Explicit HF materialization. Does not fetch model weights or install packages."""
import argparse,hashlib,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--allow-dataset-download',action='store_true');a=p.parse_args()
if not a.allow_dataset_download:raise SystemExit('Pass --allow-dataset-download explicitly; prepare in an isolated training environment')
from datasets import load_dataset
root=Path(__file__).resolve().parent
manifest=json.loads((root/'manifest.json').read_text());info=json.loads((root/'data/dataset_info.json').read_text())
for index,b in enumerate(json.loads((root/'plan.json').read_text())['data']):
    if b['kind']!='huggingface':continue
    ds=load_dataset(b['ref'],b.get('subset') or None,revision=b['revision'],split=b['split'])
    path=root/'data'/('dataset_'+str(index)+'.jsonl');ds.to_json(str(path),force_ascii=False)
    info['dataset_'+str(index)]={'file_name':path.name,'columns':b['columns']}
(root/'data/dataset_info.json').write_text(json.dumps(info))
# Materialization changes identity; create a derived input manifest, never claim the exported identity is unchanged.
manifest['parent_manifest_sha256']=hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest()
manifest['external_references']=[b for b in manifest['external_references'] if b['kind']!='huggingface']
for path in (root/'data').glob('*'):
    if path.is_file():manifest['files'][str(path.relative_to(root))]=hashlib.sha256(path.read_bytes()).hexdigest()
(root/'manifest.json').write_text(json.dumps(manifest,sort_keys=True))
print('Derived manifest ready. Register the derived bundle before starting through WebUI.')
'''
