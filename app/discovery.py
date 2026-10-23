"""Competitor discovery over authorized, tenant-scoped catalogs.

No invented listings or public-page scraping. Providers can be replaced without
changing scoring and association. Scores are rule scores, not probabilities.
"""
import re
from datetime import datetime,timezone,timedelta
from typing import Protocol
from fastapi import APIRouter,Depends
from pydantic import BaseModel,Field
from .prototype import ProductInput

class CatalogProvider(Protocol):
    def search(self,tenant:str,own:dict)->list[dict]: ...

class LocalCatalogProvider:
    def __init__(self,store):self.store=store
    def search(self,tenant,own):
        registered=[{**p,'origin':'product','origin_id':p['id']} for p in self.store.list(tenant,'product')
                    if p['role']=='competitor' and p['active'] and p['authorized']]
        catalog=[{**p,'origin':'catalog','origin_id':p['id']} for p in self.store.list(tenant,'catalog')
                 if p['active'] and p['authorized']]
        # Registered records take precedence over imported duplicates.
        unique={}
        for p in registered+catalog:
            if p['item_id']!=own['item_id']:
                unique.setdefault((p['item_id'],p['sku']),p)
        return list(unique.values())

def terms(text):
    normalized=re.sub(r'\s+','',text.lower())
    return set(normalized[i:i+2] for i in range(len(normalized)-1)) or {normalized}

def score(own,candidate):
    a,b=terms(own['title']),terms(candidate['title'])
    similarity=len(a&b)/max(len(a|b),1)
    same_sku=own['sku']==candidate['sku']
    same_category=own['category']==candidate['category'] and own['category']!='通用'
    value=round(55*similarity+30*same_sku+15*same_category,1)
    reasons=[f'标题相似度 {similarity:.0%}', '规格一致' if same_sku else '规格不同，仅供查看',
             '类目一致' if same_category else '类目未确认或不同']
    # Ambiguous categories and unrelated titles never auto-link on SKU alone.
    auto=same_sku and same_category and similarity>=.45 and value>=70
    return {'score':value,'reasons':reasons,'same_sku':same_sku,'auto_eligible':auto}

class SearchInput(BaseModel):
    own_id:str
    auto_link:bool=False
    limit:int=Field(default=10,ge=1,le=30)

class LinkInput(BaseModel):
    candidate_ids:list[str]=Field(min_length=1,max_length=30)

class CatalogInput(BaseModel):
    products:list[ProductInput]=Field(min_length=1,max_length=500)

class Discovery:
    def __init__(self,proto,provider=None):
        self.proto=proto;self.store=proto.store
        self.provider=provider or LocalCatalogProvider(self.store)

    def own(self,tenant,identifier):
        p=self.store.get(tenant,'product',identifier)
        if p['role']!='own' or not p['active'] or not p['authorized']:
            raise ValueError('请选择有效且已授权的自有商品')
        return p

    def search(self,tenant,body):
        with self.proto.service.lock:
            own=self.own(tenant,body.own_id)
            candidates=[]
            for p in self.provider.search(tenant,own):
                match=score(own,p)
                if match['score']>=30:
                    candidates.append({'candidate_id':p['origin']+':'+p['origin_id'],
                        'product':p,**match})
            candidates.sort(key=lambda c:(-c['score'],c['candidate_id']))
            candidates=candidates[:body.limit]
            result=self.store.add(tenant,'discovery',{'own_id':own['id'],'own_version':own['version'],
                'query':{'title':own['title'],'category':own['category'],'sku':own['sku']},
                'provider':'本租户已登记竞品及授权导入商品库','external_search_connected':False,
                'expires':(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat(),
                'candidates':candidates})
            linked=[]
            if body.auto_link:
                ids=[c['candidate_id'] for c in candidates if c['auto_eligible']]
                if ids:linked=self.link(tenant,result['id'],ids,automatic=True)
            self.store.audit(tenant,'competitor_search',{'search_id':result['id'],'count':len(candidates),'auto_linked':len(linked)})
            return {**result,'linked':linked}

    def link(self,tenant,search_id,ids,automatic=False):
        with self.proto.service.lock:
            result=self.store.get(tenant,'discovery',search_id)
            own=self.own(tenant,result['own_id'])
            if own['version']!=result['own_version'] or datetime.fromisoformat(result['expires'])<=datetime.now(timezone.utc):
                raise ValueError('商品已修改或搜索结果过期，请重新搜索')
            indexed={c['candidate_id']:c for c in result['candidates']}
            validated=[]
            # Validate the whole selection before writing associations.
            for cid in dict.fromkeys(ids):
                if cid not in indexed:raise ValueError('候选不属于本次搜索')
                cached=indexed[cid]['product']
                live=self.store.get(tenant,cached['origin'],cached['origin_id'])
                if not live['active'] or not live['authorized'] or live.get('version')!=cached.get('version'):
                    raise ValueError('候选状态已改变，请重新搜索')
                if live['role']!='competitor' or live['item_id']==own['item_id']:
                    raise ValueError('无效竞品')
                match=score(own,live)
                if not match['same_sku'] or (automatic and not match['auto_eligible']):
                    raise ValueError('候选不满足关联条件')
                validated.append((cached,live,match))
            links=[]
            for cached,live,match in validated:
                if cached['origin']=='catalog':
                    existing=next((p for p in self.store.list(tenant,'product') if p['active'] and p['item_id']==live['item_id'] and p['sku']==live['sku']),None)
                    if existing and existing['role']!='competitor':raise ValueError('该商品已登记为自有商品')
                    competitor=existing or self.proto.create_product(tenant,ProductInput(**live))
                else:competitor=live
                old=next((p for p in self.store.list(tenant,'pair') if p['own_id']==own['id'] and p['competitor_id']==competitor['id']),None)
                link=old or self.store.add(tenant,'pair',{'own_id':own['id'],'competitor_id':competitor['id'],
                    'discovery_id':search_id,'match_score':match['score'],'method':'automatic' if automatic else 'selected'})
                links.append(link)
            self.store.audit(tenant,'competitors_linked',{'search_id':search_id,'pair_ids':[p['id'] for p in links]})
            return links

def build_discovery_router(proto,identity):
    router=APIRouter(prefix='/api/v1/discovery')
    discovery=Discovery(proto)
    @router.post('/search')
    def search(body:SearchInput,tenant=Depends(identity)):
        return discovery.search(tenant,body)

    @router.post('/{identifier}/link')
    def link(identifier:str,body:LinkInput,tenant=Depends(identity)):
        return {'linked':discovery.link(tenant,identifier,body.candidate_ids)}

    @router.post('/catalog/import')
    def catalog(body:CatalogInput,tenant=Depends(identity)):
        with proto.service.lock:
            rows=[]
            for index,p in enumerate(body.products):
                if not p.authorized or p.role!='competitor':
                    rows.append({'row':index+1,'error':'只接受已授权的竞品数据'});continue
                old=next((r for r in proto.store.list(tenant,'catalog') if r['item_id']==p.item_id and r['sku']==p.sku),None)
                data={**p.model_dump(),'active':True,'version':old['version']+1 if old else 1}
                row=proto.store.update(tenant,'catalog',old['id'],data) if old else proto.store.add(tenant,'catalog',data)
                rows.append({'row':index+1,'id':row['id']})
            proto.store.audit(tenant,'catalog_imported',{'rows':len(rows)})
            return {'rows':rows,'success':sum('id' in r for r in rows)}
    return router
