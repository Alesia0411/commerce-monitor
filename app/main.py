"""HTTP composition root; no platform access is enabled by this demo."""
import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .config import settings
from .store import Store
from .ingestion import SyntheticSource, RateGate
from .models import OfflineModel, RemoteModel
from .service import MonitorService
from .tools import ToolGateway
from .evaluation import evaluate_security
from .prototype import Prototype, build_router
from .access import Access, routes as access_routes
from .discovery import build_discovery_router
from .capture import CaptureService,Extractor,routes as capture_routes
from .browser_capture import BrowserCapture,routes as browser_routes
import os

store = Store(settings.database_url)
model = RemoteModel(settings) if settings.api_key and settings.model else OfflineModel()
service = MonitorService(store,SyntheticSource(),RateGate(settings.redis_url),model)
gateway = ToolGateway(service)
prototype = Prototype(service)
access = Access(store)
capture = CaptureService(prototype,Extractor(settings))
browser_capture = BrowserCapture(capture)

async def browser_worker():
    while True:
        try:
            await asyncio.to_thread(browser_capture.tick)
        except Exception:
            import logging
            logging.getLogger(__name__).exception('Browser worker iteration failed')
        await asyncio.sleep(3)

async def worker():
    while True:
        try:
            await asyncio.to_thread(prototype.tick)
        except Exception:
            import logging
            logging.getLogger(__name__).exception('Background worker iteration failed')
        await asyncio.sleep(2)

async def schedule():
    while True:
        await asyncio.sleep(max(settings.scheduler_seconds, 1))
        for tenant in ['a','b']:
            # Scheduler monitors the stable synthetic fixture; UI injects changes.
            await asyncio.to_thread(service.run,tenant,'baseline',f'schedule-{uuid.uuid4()}')

@asynccontextmanager
async def lifespan(app):
    access.bootstrap()
    for tenant in ['a','b']:
        service.seed(tenant); service.recover(tenant)
    prototype.recover()
    for tenant in ['a','b']:
        for job in store.list(tenant,'browser_job'):
            if job['status']=='RUNNING':store.update(tenant,'browser_job',job['id'],{'status':'FAILED','error':'运行中断；请重新提交'})
    worker_task=asyncio.create_task(worker())
    browser_task=asyncio.create_task(browser_worker())
    task = asyncio.create_task(schedule()) if settings.scheduler_seconds > 0 else None
    yield
    browser_task.cancel()
    try:
        await browser_task
    except asyncio.CancelledError:pass
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

app = FastAPI(title='Commerce Monitor', lifespan=lifespan)

def identity(authorization: str = Header(default='')):
    principal=access.resolve(authorization.removeprefix('Bearer '))
    if principal:return principal['tenant']
    tokens = {f'Bearer {settings.token_a}':'a', f'Bearer {settings.token_b}':'b'}
    if os.getenv('ALLOW_LEGACY_TOKENS','0')!='1' or authorization not in tokens:
        raise HTTPException(401,'Provide a valid local demo token')
    return tokens[authorization]

@app.middleware('http')
async def roles(request,call_next):
    path=request.url.path
    if path.startswith('/api/v1/capture'):
        try:
            length=int(request.headers.get('content-length','0'))
        except ValueError:
            return JSONResponse(status_code=400,content={'detail':'无效请求长度'})
        if length>9000000:
            return JSONResponse(status_code=413,content={'detail':'请求过大，截图上限 6MB'})
    if (path.startswith('/api/') or path=='/mcp') and not path.startswith('/api/auth/'):
        who=access.resolve(request.headers.get('authorization','').removeprefix('Bearer '))
        if who and request.method not in {'GET','HEAD','OPTIONS'}:
            if who['role']=='viewer':return JSONResponse(status_code=403,content={'detail':'只读账号不能修改数据'})
            if any(s in path for s in ['/review','/decision','/resume','/revoke']) and who['role'] not in {'admin','reviewer'}:
                return JSONResponse(status_code=403,content={'detail':'此操作需要审核员或管理员权限'})
    return await call_next(request)

@app.exception_handler(KeyError)
async def missing(request, exc):
    return JSONResponse(status_code=404, content={'detail':'Resource not found'})

@app.exception_handler(ValueError)
async def invalid(request, exc):
    return JSONResponse(status_code=409,content={'detail':str(exc)})

class RunInput(BaseModel):
    scenario: Literal['baseline','discount','missing','injection','429','403','captcha','timeout','expired'] = 'baseline'

class Decision(BaseModel):
    decision: Literal['APPROVED','REJECTED','RETIRED']

class MemoryInput(BaseModel):
    content: str = Field(min_length=1,max_length=3000)
    workflow: list[str] | None = None
    evidence: str | None = None

@app.get('/api/state')
def state(tenant=Depends(identity)):
    service.seed(tenant)
    return {'tenant':tenant,'mode':'remote' if isinstance(model,RemoteModel) else 'offline',
        'database':'mysql' if settings.database_url.startswith('mysql') else 'sqlite',
        'rate_backend':'redis' if settings.redis_url else 'local',
        'scheduler_seconds':settings.scheduler_seconds,
        **{kind:store.list(tenant,kind) for kind in ['source','run','snapshot','recommendation','memory','failure','checkpoint','audit','evaluation']}}

@app.post('/api/runs')
def run(body:RunInput,tenant=Depends(identity),idempotency_key:str=Header(default='')):
    return service.run(tenant,body.scenario,idempotency_key or str(uuid.uuid4()))

@app.post('/api/source/resume')
def resume(tenant=Depends(identity)):
    return service.resume(tenant)

@app.post('/api/recommendations/{identifier}/decision')
def decide(identifier:str,body:Decision,tenant=Depends(identity)):
    return service.decide(tenant,identifier,body.decision)

@app.post('/api/memory')
def propose(body:MemoryInput,tenant=Depends(identity)):
    with service.lock:
        return service.memory.propose(tenant,body.content,workflow=body.workflow,evidence=body.evidence)

@app.post('/api/memory/{identifier}/evaluate')
def memory_eval(identifier:str,tenant=Depends(identity)):
    return service.memory.evaluate(tenant,identifier)

@app.post('/api/recommendations/{identifier}/derive-workflow')
def derive(identifier:str,tenant=Depends(identity)):
    """Minimal AWM induction: abstract a human-approved trajectory into a DSL.

    This rule-based abstraction is labelled; it is not an LLM reproduction.
    """
    with service.lock:
        rec = store.get(tenant,'recommendation',identifier)
        if rec['status'] != 'APPROVED':
            raise ValueError('Approve the source recommendation before distillation')
        if not all(store.get(tenant,'snapshot',e)['active'] for e in rec['evidence']):
            raise ValueError('Evidence revoked')
        return service.memory.propose(tenant,'已审核促销分析经验：先检查同规格价格，再整理内容变化，最后验证证据。',
            workflow=['compare','retrieve','price','content','verify'],evidence=rec['evidence'][-1])

@app.post('/api/memory/{identifier}/review')
def review(identifier:str,body:Decision,tenant=Depends(identity)):
    with service.lock:
        return service.memory.review(tenant,identifier,body.decision)

@app.post('/api/evidence/{identifier}/revoke')
def revoke(identifier:str,tenant=Depends(identity)):
    with service.lock:
        return service.memory.revoke(tenant,identifier)

@app.post('/api/evaluations')
def evaluate(tenant=Depends(identity)):
    return store.add(tenant,'evaluation',evaluate_security())

@app.post('/mcp')
async def mcp(request:Request,tenant=Depends(identity)):
    """Minimal stateless JSON-RPC MCP endpoint: initialize/list/call.

    Only this subset is implemented; no claim of full SDK conformance/OAuth.
    """
    data = await request.json()
    if 'id' not in data:
        return Response(status_code=202)
    method, params = data.get('method'), data.get('params',{})
    try:
        if method == 'initialize':
            result = {'protocolVersion':'2025-03-26','capabilities':{'tools':{}},
                      'serverInfo':{'name':'commerce-demo','version':'0.1.0'}}
        elif method == 'tools/list':
            result = {'tools':gateway.descriptors()}
        elif method == 'tools/call':
            output = gateway.call(tenant,params['name'],params.get('arguments',{}))
            result = {'content':[{'type':'text','text':json.dumps(output,ensure_ascii=False)}]}
        else:
            return {'jsonrpc':'2.0','id':data['id'],'error':{'code':-32601,'message':'Method not supported'}}
        return {'jsonrpc':'2.0','id':data['id'],'result':result}
    except (KeyError,ValueError,PermissionError) as exc:
        return {'jsonrpc':'2.0','id':data['id'],'result':{'isError':True,
            'content':[{'type':'text','text':str(exc)}]}}

web = Path(__file__).resolve().parent.parent / 'web'
app.include_router(build_router(prototype,identity))
app.include_router(build_discovery_router(prototype,identity))
app.include_router(capture_routes(capture,identity,browser_capture))
app.include_router(browser_routes(browser_capture,identity))
app.include_router(access_routes(access))
app.mount('/',StaticFiles(directory=web,html=True),name='web')
