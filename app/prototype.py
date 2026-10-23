"""Product, planning, persistent jobs and operational task bounded contexts.

All writes are serialized with the application's local lock. Queue state is
durable in SQL and can be resumed after restart; one application worker only.
"""
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Literal
import uuid
from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator

def utc():
    return datetime.now(timezone.utc)

class ProductInput(BaseModel):
    title: str = Field(min_length=1,max_length=200)
    item_id: str = Field(min_length=1,max_length=100)
    sku: str = Field(min_length=1,max_length=100)
    role: Literal['own','competitor'] = 'competitor'
    category: str = Field(default='通用',max_length=100)
    price: str | None = None
    description: str = Field(default='',max_length=10000)
    promotion: str = Field(default='无额外优惠条件',max_length=3000)
    review: str = Field(default='',max_length=10000)
    source: Literal['manual','synthetic'] = 'manual'
    authorized: bool = False
    cost: str | None = None

    @field_validator('price','cost')
    @classmethod
    def valid_money(cls,value):
        if value is not None:
            try:
                amount=Decimal(value)
                if not amount.is_finite() or amount < 0 or amount > 100000000:
                    raise ValueError()
                return str(amount.quantize(Decimal('.01')))
            except Exception:
                raise ValueError('金额必须是非负有效数字')
        return value

class ProductEdit(ProductInput):
    version: int = Field(ge=1)

class PlanInput(BaseModel):
    product_id: str
    interval_minutes: int = Field(default=60,ge=1,le=43200)
    enabled: bool = True

class ImportInput(BaseModel):
    products: list[ProductInput] = Field(min_length=1,max_length=200)

class TaskInput(BaseModel):
    recommendation_id: str
    owner: str = Field(default='运营',max_length=100)
    kind: Literal['operation','creative'] = 'operation'
    deadline: str = Field(default='',max_length=40)

class TaskEdit(BaseModel):
    status: Literal['TODO','DOING','DONE','CANCELLED']
    note: str = Field(default='',max_length=3000)
    version: int = Field(ge=1)

class FeedbackInput(BaseModel):
    recommendation_id: str
    rating: int = Field(ge=1,le=5)
    comment: str = Field(default='',max_length=3000)

class PairInput(BaseModel):
    own_id: str
    competitor_id: str

class JobInput(BaseModel):
    product_id: str

class KnowledgeInput(BaseModel):
    title: str = Field(min_length=1,max_length=200)
    content: str = Field(min_length=1,max_length=10000)

class Prototype:
    def __init__(self,service):
        self.service=service
        self.store=service.store

    def create_product(self,tenant,body):
        if not body.authorized:
            raise ValueError('请确认拥有录入数据的使用权')
        if any(p['item_id']==body.item_id and p['sku']==body.sku and p['active'] for p in self.store.list(tenant,'product')):
            raise ValueError('商品与规格已存在，请修改现有商品')
        product=self.store.add(tenant,'product',{**body.model_dump(),'active':True,'version':1})
        self.store.audit(tenant,'product_created',{'product_id':product['id']})
        return product

    def enqueue(self,tenant,product_id,key):
        product=self.store.get(tenant,'product',product_id)
        if not product['active'] or not product['authorized']:
            raise ValueError('商品已归档或未获得数据使用授权')
        existing=next((j for j in self.store.list(tenant,'job') if j['request_key']==key),None)
        if existing:return existing
        # Freeze the input at enqueue time: later edits must not change a run.
        return self.store.add(tenant,'job',{'product_id':product_id,'product_version':product['version'],
            'input':product,'status':'PENDING','request_key':key,'attempts':0},key)

    def tick(self):
        """Bounded polling, persistent deadlines and idempotent run identifiers."""
        with self.service.lock:
            for tenant in ['a','b']:
                for plan in self.store.list(tenant,'plan'):
                    if plan['enabled'] and datetime.fromisoformat(plan['next_due']) <= utc():
                        try:
                            self.enqueue(tenant,plan['product_id'],'plan:'+plan['id']+':'+plan['next_due'])
                            self.store.update(tenant,'plan',plan['id'],{'next_due':(utc()+timedelta(minutes=plan['interval_minutes'])).isoformat(),'error':None})
                        except ValueError as exc:
                            self.store.update(tenant,'plan',plan['id'],{'enabled':False,'error':str(exc)})
                pending=[j for j in self.store.list(tenant,'job') if j['status']=='PENDING'][:2]
                for job in pending:
                    self.store.update(tenant,'job',job['id'],{'status':'RUNNING','attempts':job['attempts']+1})
                    try:
                        p=job['input']
                        payload={k:p[k] for k in ['item_id','sku','title','price','description','promotion','review']}
                        payload.update(currency='CNY',synthetic=p['source']=='synthetic')
                        run=self.service.run(tenant,'imported','job:'+job['id'],payload,p['id'])
                        status='COMPLETED' if run['status'] in {'COMPLETED','BASELINE','UNCHANGED'} else 'FAILED'
                        self.store.update(tenant,'job',job['id'],{'status':status,'run_id':run['id'],'result':run['status'],'error':run.get('error')})
                    except Exception as exc:
                        self.store.update(tenant,'job',job['id'],{'status':'FAILED','error':type(exc).__name__+': '+str(exc)[:200]})

    def recover(self):
        for tenant in ['a','b']:
            for job in self.store.list(tenant,'job'):
                if job['status']=='RUNNING':
                    self.store.update(tenant,'job',job['id'],{'status':'FAILED','error':'进程中断，请重试；已完成运行可幂等查询'})

    def report(self,tenant):
        products=self.store.list(tenant,'product')
        tasks=self.store.list(tenant,'task')
        recs=self.store.list(tenant,'recommendation')
        feedback=self.store.list(tenant,'feedback')
        return {'products':sum(p['active'] for p in products),'recommendations':len(recs),
            'approved':sum(r['status']=='APPROVED' for r in recs),
            'tasks_done':sum(t['status']=='DONE' for t in tasks),'tasks_total':len(tasks),
            'average_rating':round(sum(f['rating'] for f in feedback)/len(feedback),2) if feedback else None,
            'jobs_failed':sum(j['status']=='FAILED' for j in self.store.list(tenant,'job'))}

def build_router(proto,identity):
    router=APIRouter(prefix='/api/v1')
    store,service=proto.store,proto.service

    @router.get('/workspace')
    def workspace(tenant=Depends(identity)):
        return {**{k:store.list(tenant,k) for k in ['product','plan','job','task','feedback','pair','knowledge']},'metrics':proto.report(tenant)}

    @router.post('/products')
    def create(body:ProductInput,tenant=Depends(identity)):
        with service.lock:return proto.create_product(tenant,body)

    @router.put('/products/{identifier}')
    def edit(identifier:str,body:ProductEdit,tenant=Depends(identity)):
        with service.lock:
            old=store.get(tenant,'product',identifier)
            if old['version']!=body.version:raise ValueError('商品已被修改，请刷新后重试')
            if not body.authorized:raise ValueError('需要数据使用授权')
            if any(p['id']!=identifier and p['active'] and p['item_id']==body.item_id and p['sku']==body.sku for p in store.list(tenant,'product')):
                raise ValueError('商品与规格重复')
            store.audit(tenant,'product_updated',{'id':identifier,'version':body.version+1})
            return store.update(tenant,'product',identifier,{**body.model_dump(),'version':body.version+1})

    @router.post('/products/{identifier}/archive')
    def archive(identifier:str,tenant=Depends(identity)):
        with service.lock:
            product=store.get(tenant,'product',identifier)
            for p in store.list(tenant,'plan'):
                if p['product_id']==identifier:store.update(tenant,'plan',p['id'],{'enabled':False})
            return store.update(tenant,'product',identifier,{'active':False,'version':product['version']+1})

    @router.post('/imports')
    def imports(body:ImportInput,tenant=Depends(identity)):
        # Explicit per-row results: partial imports are never reported as atomic.
        with service.lock:
            rows=[]
            for index,p in enumerate(body.products):
                try:rows.append({'row':index+1,'product':proto.create_product(tenant,p)})
                except ValueError as exc:rows.append({'row':index+1,'error':str(exc)})
            return {'rows':rows,'success':sum('product' in r for r in rows)}

    @router.get('/products/{identifier}/timeline')
    def timeline(identifier:str,tenant=Depends(identity)):
        store.get(tenant,'product',identifier)
        return {k:[r for r in store.list(tenant,k) if r.get('product_id')==identifier] for k in ['snapshot','run','recommendation']}

    @router.post('/plans')
    def plan(body:PlanInput,tenant=Depends(identity)):
        with service.lock:
            p=store.get(tenant,'product',body.product_id)
            if not p['active']:raise ValueError('商品已归档')
            existing=next((r for r in store.list(tenant,'plan') if r['product_id']==body.product_id),None)
            data={**body.model_dump(),'next_due':utc().isoformat()}
            return store.update(tenant,'plan',existing['id'],data) if existing else store.add(tenant,'plan',data)

    @router.post('/jobs',status_code=202)
    def enqueue(body:JobInput,tenant=Depends(identity),idempotency_key:str=Header(default='')):
        with service.lock:return proto.enqueue(tenant,body.product_id,idempotency_key or str(uuid.uuid4()))

    @router.post('/jobs/{identifier}/retry',status_code=202)
    def retry(identifier:str,tenant=Depends(identity)):
        with service.lock:
            old=store.get(tenant,'job',identifier)
            if old['status']!='FAILED':raise ValueError('只允许重试失败任务')
            return proto.enqueue(tenant,old['product_id'],'retry:'+str(uuid.uuid4()))

    @router.post('/jobs/{identifier}/cancel')
    def cancel(identifier:str,tenant=Depends(identity)):
        with service.lock:
            old=store.get(tenant,'job',identifier)
            if old['status']!='PENDING':raise ValueError('只允许取消待执行任务')
            return store.update(tenant,'job',identifier,{'status':'CANCELLED'})

    @router.post('/pairs')
    def pair(body:PairInput,tenant=Depends(identity)):
        with service.lock:
            own=store.get(tenant,'product',body.own_id);other=store.get(tenant,'product',body.competitor_id)
            if own['role']!='own' or other['role']!='competitor' or own['sku']!=other['sku']:
                raise ValueError('请选择同规格的自有商品与竞品')
            existing=next((r for r in store.list(tenant,'pair') if r['own_id']==body.own_id and r['competitor_id']==body.competitor_id),None)
            return existing or store.add(tenant,'pair',body.model_dump())

    @router.get('/comparisons')
    def comparisons(tenant=Depends(identity)):
        results=[]
        for pair in store.list(tenant,'pair'):
            a=store.get(tenant,'product',pair['own_id']);b=store.get(tenant,'product',pair['competitor_id'])
            compatible=a['sku']==b['sku'] and a['promotion']==b['promotion'] and a['active'] and b['active']
            delta=str(Decimal(b['price'])-Decimal(a['price'])) if compatible and a['price'] is not None and b['price'] is not None else None
            results.append({'own':a['title'],'competitor':b['title'],'own_price':a['price'],'competitor_price':b['price'],
                'delta':delta,'conditions_match':compatible,'basis':'当前已录入数据，非实时成交价'})
        return results

    @router.post('/tasks')
    def task(body:TaskInput,tenant=Depends(identity)):
        with service.lock:
            rec=store.get(tenant,'recommendation',body.recommendation_id)
            if rec['status']!='APPROVED':raise ValueError('请先批准建议')
            existing=next((r for r in store.list(tenant,'task') if r['recommendation_id']==rec['id'] and r['kind']==body.kind),None)
            if existing:return existing
            return store.add(tenant,'task',{**body.model_dump(),'title':rec['title'],
                'brief':rec['action'],'acceptance':'核对事实和证据，记录执行结果；不承诺经营收益。',
                'status':'TODO','version':1,'note':''})

    @router.patch('/tasks/{identifier}')
    def task_edit(identifier:str,body:TaskEdit,tenant=Depends(identity)):
        with service.lock:
            old=store.get(tenant,'task',identifier)
            if old['version']!=body.version:raise ValueError('任务版本已变化')
            allowed={'TODO':{'DOING','CANCELLED'},'DOING':{'DONE','CANCELLED'},'DONE':set(),'CANCELLED':set()}
            if body.status not in allowed[old['status']]:raise ValueError('不允许的任务状态变化')
            rec=store.get(tenant,'recommendation',old['recommendation_id'])
            if body.status!='CANCELLED' and (rec['status']!='APPROVED' or not all(store.get(tenant,'snapshot',e)['active'] for e in rec['evidence'])):
                raise ValueError('建议或证据已失效，任务需重新审核')
            store.audit(tenant,'task_updated',{'id':identifier,'status':body.status})
            return store.update(tenant,'task',identifier,{**body.model_dump(),'version':body.version+1})

    @router.post('/feedback')
    def feedback(body:FeedbackInput,tenant=Depends(identity)):
        store.get(tenant,'recommendation',body.recommendation_id)
        return store.add(tenant,'feedback',body.model_dump())

    @router.post('/knowledge')
    def knowledge(body:KnowledgeInput,tenant=Depends(identity)):
        with service.lock:
            candidate=service.memory.propose(tenant,body.title+'：'+body.content)
            return store.add(tenant,'knowledge',{**body.model_dump(),'memory_id':candidate['id'],'status':'CANDIDATE'})

    @router.get('/report.md')
    def report(tenant=Depends(identity)):
        metrics=proto.report(tenant)
        lines=['# 商品监控运营报告','',f'生成时间：{utc().isoformat()}','',*['- '+k+': '+str(v) for k,v in metrics.items()], '\n## 运营建议']
        for rec in store.list(tenant,'recommendation'):
            lines.extend(['', '### '+rec['title'],rec['action'],'状态：'+rec['status']])
        return Response('\n'.join(lines),media_type='text/markdown',headers={'Content-Disposition':'attachment; filename=report.md'})

    return router
