"""Same-origin LAN gateway. Legacy project backends are private Unix-socket workers."""
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import tempfile
import shutil
from urllib.parse import urlsplit
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from app.services.data_library import LibraryError
from app.services.team_store import TeamStore, digest, password_hash, verify

BACKEND = Path(__file__).resolve().parents[1]
DIST = BACKEND.parent / 'frontend/dist'


class Workers:
    def __init__(self, state):
        self.state = Path(state)
        self.runtime = Path(tempfile.mkdtemp(prefix='df-lan-'))
        self.runtime.chmod(0o700)
        self.processes = {}
        self.locks = {}

    async def client(self, project):
        pid = project['id']
        async with self.locks.setdefault(pid, asyncio.Lock()):
            socket = self.runtime / (pid + '.sock')
            process = self.processes.get(pid)
            if process is None or process.poll() is not None:
                socket.unlink(missing_ok=True)
                env = os.environ.copy()
                env['DATAFLOW_WORKSPACE_DIR'] = project['root']
                env['DATAFLOW_TEAM_WORKER'] = '1'
                env['DATAFLOW_PROJECT_ID'] = pid
                env['DATAFLOW_DATASET_BACKUP_DIR'] = str(Path(project['root'])/'backups/datasets')
                env['DATAFLOW_TRAINING_DIR'] = str(Path(project['root'])/'data/model_training')
                log = (self.state / (pid + '.worker.log')).open('ab')
                try:
                    process = subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--uds',str(socket),'--no-access-log'],cwd=BACKEND,env=env,stdout=log,stderr=log)
                finally:
                    log.close()
                self.processes[pid] = process
                for _ in range(300):
                    if process.poll() is not None:
                        raise LibraryError('项目服务启动失败，请在主机检查工作进程日志',503)
                    if socket.exists():break
                    await asyncio.sleep(.1)
                else:raise LibraryError('项目服务启动超时',503)
        return httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=str(socket)),base_url='http://project',timeout=120)

    async def close(self):
        for process in self.processes.values():
            if process.poll() is None:process.terminate()
        for process in self.processes.values():
            try:await asyncio.to_thread(process.wait,10)
            except subprocess.TimeoutExpired:process.kill()
        shutil.rmtree(self.runtime)


def clean_secrets(obj):
    if isinstance(obj,list):return [clean_secrets(v) for v in obj]
    if isinstance(obj,dict):
        if str(obj.get('name','')).lower() in {'api_key','password','secret','token','access_token'}:
            return {k: ('****' if k in {'value','default_value'} and v else clean_secrets(v)) for k,v in obj.items()}
        return {k: ('****' if k.lower() in {'api_key','password','secret','token','access_token'} and v else clean_secrets(v)) for k,v in obj.items()}
    return obj


def policy(path, method, roles):
    """Fail closed. Review-only users have no access to legacy business routes."""
    if path.startswith('/api/v1/team-data/'):
        if '/reviews' in path and method=='GET':return
        if any(path.endswith('/'+s) for s in ('claim','release','save','submit','revise','reopen')):
            if 'review' in roles:return
        elif set(roles)&{'manage','develop'}:return
        raise LibraryError('无此操作权限',403)
    if not set(roles)&{'manage','develop'}:raise LibraryError('需要项目开发权限',403)
    route = path.removeprefix('/api/v1/').split('/')[0]
    if route not in {'library','datasets','operators','tasks','pipelines','prompts','serving','text2sql_database','text2sql_database_manager','json_schemas','generation','multimodal','training'}:
        raise LibraryError('团队模式未开放此入口',403)
    if any(part in path for part in ('choose-local','import-local','list_dir','/materials/register','/results/import')) or (route=='datasets' and method=='POST' and path.rstrip('/')=='/api/v1/datasets'):
        raise LibraryError('请使用上传，团队模式不开放任意主机路径',403)
    if route in {'text2sql_database','text2sql_database_manager'}:
        raise LibraryError('团队模式未开放主机数据库入口',403)
    if (route=='serving' and method!='GET') or path.startswith('/api/v1/training/host'):
        if 'manage' not in roles:raise LibraryError('需要项目管理权限',403)


def create_gateway(state=None, workers=None, secure=None):
    store=TeamStore(state or os.environ.get('DATAFLOW_TEAM_DIR',BACKEND/'data/collaboration'))
    workers=workers or Workers(store.root)
    secure=secure if secure is not None else os.environ.get('DATAFLOW_COOKIE_SECURE','1')=='1'
    @asynccontextmanager
    async def lifespan(app):
        yield
        await workers.close()
    app=FastAPI(title='DataFlow LAN',docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
    app.state.store=store
    app.state.workers=workers
    app.state.write_locks={}

    @app.exception_handler(LibraryError)
    async def library_error(request,exc):
        return JSONResponse({'detail':str(exc)},status_code=exc.status)

    @app.middleware('http')
    async def security(request,call_next):
        # Mutations require an explicit same-origin Origin even on login/accept.
        if request.method not in {'GET','HEAD','OPTIONS'}:
            origin=request.headers.get('origin','')
            expected=str(request.base_url).rstrip('/')
            if origin!=expected:
                return JSONResponse({'detail':'写操作需要同源 Origin'},status_code=403)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='same-origin'
        response.headers['X-Frame-Options']='DENY'
        if request.url.path.startswith(('/api/','/team/')):response.headers['Cache-Control']='no-store'
        return response

    def actor(request,write=True):
        user=store.identity(request.cookies.get('df_session'))
        if write and request.method not in {'GET','HEAD'} and not secrets.compare_digest(request.headers.get('x-csrf-token',''),user['csrf']):
            raise LibraryError('会话校验失败，请刷新',403)
        return user

    @app.get('/team/status')
    def status():
        with store.tx() as c:initialized=bool(c.execute('SELECT 1 FROM users').fetchone())
        return {'mode':'lan','initialized':initialized}

    @app.post('/team/login')
    async def login(request:Request):
        body=await request.json()
        token,csrf=store.login(body.get('name'),body.get('password'),request.client.host)
        result=JSONResponse({'csrf':csrf})
        result.set_cookie('df_session',token,httponly=True,secure=secure,samesite='strict',max_age=43200)
        return result

    @app.post('/team/accept')
    async def accept(request:Request):
        body=await request.json();store.accept(body.get('invitation',''),body.get('password'));return {'ok':True}

    @app.get('/team/me')
    def me(request:Request):
        user=actor(request)
        return dict(user,projects=store.projects(user['id']))

    @app.post('/team/logout')
    def logout(request:Request):
        user=actor(request)
        with store.tx() as c:
            c.execute('DELETE FROM sessions WHERE token=?',(digest(request.cookies.get('df_session','')),))
            store.audit(c,user['id'],user['project'],'logout')
        response=JSONResponse({'ok':True});response.delete_cookie('df_session');return response

    @app.post('/team/password')
    async def password(request:Request):
        user=actor(request);body=await request.json();hashed=password_hash(body.get('password'))
        with store.tx() as c:
            old=c.execute('SELECT password FROM users WHERE id=?',(user['id'],)).fetchone()[0]
            if not verify(body.get('current'),old):raise LibraryError('当前密码无效',400)
            c.execute('UPDATE users SET password=? WHERE id=?',(hashed,user['id']))
            c.execute('DELETE FROM sessions WHERE user=?',(user['id'],))
            store.audit(c,user['id'],None,'change-password')
        return {'ok':True}

    @app.post('/team/project')
    async def select_project(request:Request):
        user=actor(request);body=await request.json();project=store.access(user['id'],body.get('project'))
        with store.tx() as c:c.execute('UPDATE sessions SET project=? WHERE token=?',(project['id'],digest(request.cookies.get('df_session',''))))
        return {'ok':True}

    @app.post('/team/projects')
    async def create_project(request:Request):
        user=actor(request)
        if not user['admin']:raise LibraryError('需要系统管理权限',403)
        body=await request.json();name=body.get('name','').strip()
        if not name or len(name)>120:raise LibraryError('项目名称无效')
        pid='p_'+secrets.token_hex(12);root=store.root/'projects'/pid;root.mkdir(parents=True,mode=0o700)
        with store.tx() as c:
            c.execute('INSERT INTO projects VALUES(?,?,?)',(pid,name,str(root)))
            c.execute('INSERT INTO members(project,user,roles) VALUES(?,?,?)',(pid,user['id'],'manage,develop,review'))
            store.audit(c,user['id'],pid,'create-project',pid)
        return {'id':pid,'name':name}

    @app.get('/team/users')
    def users(request:Request):
        user=actor(request)
        if not user['admin']:raise LibraryError('需要系统管理权限',403)
        with store.tx() as c:return [dict(r) for r in c.execute('SELECT id,name,admin,enabled FROM users')]

    @app.post('/team/invitations')
    async def invite(request:Request):
        user=actor(request);body=await request.json()
        return store.invite(user,body.get('name'),body.get('admin',False),body.get('ttl',3600),body.get('reset'))

    @app.post('/team/users/{uid}/enabled')
    async def enabled(uid:str,request:Request):
        user=actor(request);body=await request.json()
        if not isinstance(body.get('enabled'),bool):raise LibraryError('状态无效')
        store.disable(user,uid,body['enabled']);return {'ok':True}

    @app.get('/team/projects/{pid}/members')
    def members(pid:str,request:Request):
        user=actor(request);project=store.access(user['id'],pid)
        if 'manage' not in project['roles']:raise LibraryError('需要项目管理权限',403)
        with store.tx() as c:return [dict(r,roles=r['roles'].split(',')) for r in c.execute('SELECT m.user,u.name,m.roles,m.version FROM members m JOIN users u ON u.id=m.user WHERE project=?',(pid,))]

    @app.put('/team/projects/{pid}/members/{uid}')
    async def member(pid:str,uid:str,request:Request):
        user=actor(request);body=await request.json();store.member(user,pid,uid,body.get('roles'),body.get('version'));return {'ok':True}

    @app.get('/team/audit')
    def audit(request:Request,project:str):
        user=actor(request);p=store.access(user['id'],project)
        if 'manage' not in p['roles']:raise LibraryError('需要项目管理权限',403)
        with store.tx() as c:return [dict(r) for r in c.execute('SELECT * FROM audit WHERE project=? ORDER BY id DESC LIMIT 200',(project,))]

    @app.api_route('/api/v1/preferences/',methods=['GET','POST'])
    async def preferences(request:Request):
        user=actor(request)
        with store.tx() as c:
            if request.method=='POST':
                body=await request.json();body={k:body[k] for k in ('language','theme') if k in body}
                c.execute('UPDATE users SET preferences=? WHERE id=?',(json.dumps(body),user['id']))
            row=c.execute('SELECT preferences FROM users WHERE id=?',(user['id'],)).fetchone()
            return {'code':200,'data':json.loads(row[0])}

    @app.api_route('/api/{rest:path}',methods=['GET','HEAD','POST','PUT','PATCH','DELETE'])
    async def proxy(rest:str,request:Request):
        user=actor(request);pid=request.headers.get('x-project-id') or user['project']
        if not pid:raise LibraryError('请选择项目',400)
        project=store.access(user['id'],pid)
        policy(request.url.path,request.method,project['roles'])
        body=await request.body()
        # Host paths may only be referenced if they are managed by this project.
        if body and 'application/json' in request.headers.get('content-type',''):
            try:payload=json.loads(body)
            except ValueError:raise LibraryError('JSON 无效')
            def check_paths(value):
                if isinstance(value,dict):
                    for key,v in value.items():
                        if key in {'path','root','output_dir','output_path','file_path','local_path','working_dir','result_path'} and isinstance(v,str) and v:
                            path=Path(v).expanduser().resolve()
                            if not path.is_relative_to(Path(project['root']).resolve()):
                                raise LibraryError('路径必须属于当前项目受管目录，请使用上传',403)
                        check_paths(v)
                elif isinstance(value,list):
                    for v in value:check_paths(v)
            check_paths(payload)
        headers={k:v for k,v in request.headers.items() if k.lower() in {'content-type','accept','if-match'}}
        headers.update({'x-team-user':user['id'],'x-team-roles':','.join(project['roles'])})
        # Serialize gateway writes per project; workers retain their own file/DB locks.
        async with app.state.write_locks.setdefault(pid,asyncio.Lock()):
            versioned = not request.url.path.startswith('/api/v1/team-data/')
            with store.tx() as c:
                row=c.execute("SELECT version FROM versions WHERE project=? AND object='*'",(pid,)).fetchone()
                version=row[0] if row else 0
            if versioned and request.method not in {'GET','HEAD'} and request.headers.get('if-match') != str(version):
                raise LibraryError('内容已更新，请刷新后保留并重新提交编辑',409)
            client=await workers.client(project)
            async with client:
                response=await client.request(request.method,request.url.path,params=request.query_params,content=body,headers=headers)
            if versioned and request.method not in {'GET','HEAD'} and response.status_code<400:
                version+=1
                with store.tx() as c:c.execute("INSERT INTO versions VALUES(?,'*',?) ON CONFLICT(project,object) DO UPDATE SET version=excluded.version",(pid,version))
        output=response.content
        response_headers={k:v for k,v in response.headers.items() if k.lower() in {'content-type','content-disposition','etag','x-resource-version'}}
        response_headers['X-Resource-Version']=str(version)
        if 'application/json' in response.headers.get('content-type',''):
            try:output=json.dumps(clean_secrets(response.json()),ensure_ascii=False).encode()
            except ValueError:pass
        if request.method not in {'GET','HEAD'}:
            with store.tx() as c:store.audit(c,user['id'],pid,request.method,request.url.path,str(response.status_code))
        return Response(output,status_code=response.status_code,headers=response_headers)

    @app.websocket('/{rest:path}')
    async def no_websocket(websocket,rest):
        await websocket.close(code=1008)

    if DIST.exists():app.mount('/',StaticFiles(directory=DIST,html=True),name='ui')
    return app

app=create_gateway()
