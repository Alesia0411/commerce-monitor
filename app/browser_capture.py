"""Optional Playwright adapter with server-configured approved site profiles.

No user-supplied execution code/selectors, no cookies from personal browsers,
no CAPTCHA solving, no hidden API calls. Network requests are allowlisted.
"""
import base64
import ipaddress
import json
import os
import socket
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit,quote,urljoin
from datetime import datetime,timezone
from fastapi import APIRouter,Depends
from pydantic import BaseModel,Field
from .capture import AssistedInput

class BrowserInput(BaseModel):
    own_id:str
    profile_id:str
    authorized:bool=False
    allow_model_processing:bool=False
    max_items:int=Field(default=3,ge=1,le=5)

def safe_url(url,domains):
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.username or parsed.password or parsed.port not in {None,443} or parsed.hostname not in domains:
        raise ValueError('URL 不在批准的 HTTPS 站点范围')
    addresses=socket.getaddrinfo(parsed.hostname,443,type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('禁止访问本地、私网或保留地址')
    return url

def blocked(text,url,status):
    if status in {401,403,429}:return '访问拒绝或限流'
    if any(word in url.lower() for word in ['/login','/captcha','/verify','passport.']):return '需要登录或验证'
    if any(word in text for word in ['请完成验证','滑动验证','访问过于频繁','请先登录','安全验证','验证码']):return '页面要求人工验证'
    return None

class BrowserCapture:
    def __init__(self,capture):
        self.capture=capture;self.store=capture.store;self.lock=threading.Lock()

    def config(self):
        filename=os.getenv('BROWSER_PROFILES_FILE','browser-profiles.json')
        try:
            with open(filename,encoding='utf-8-sig') as stream:return json.load(stream)
        except FileNotFoundError:return {}

    def profiles(self):
        return [{'id':key,'name':p['name'],'domains':p['domains']} for key,p in self.config().items() if p.get('enabled')]

    def enqueue(self,tenant,body):
        if not body.authorized:raise ValueError('请确认本次浏览与材料使用已获允许')
        own=self.capture.own(tenant,body.own_id)
        profile=self.config().get(body.profile_id)
        if not profile or not profile.get('enabled'):raise ValueError('管理员尚未启用此浏览器站点')
        with self.capture.proto.service.lock:
            previous=[j for j in self.store.list(tenant,'browser_job') if j['profile_id']==body.profile_id]
            if any(j['status'] in {'PENDING','RUNNING','PAUSED'} for j in previous):raise ValueError('该站点已有待执行、运行中或暂停任务')
            if previous and time.time()-datetime.fromisoformat(previous[-1]['created']).timestamp()<max(60,profile.get('min_interval_seconds',60)):
                raise ValueError('仍在访问冷却期内')
            query=' '.join([own['title'],own['category'] if own['category']!='通用' else ''])[:150]
            return self.store.add(tenant,'browser_job',{**body.model_dump(),'own_version':own['version'],
                'query':query,'status':'PENDING','candidate_ids':[]})

    def tick(self):
        if not self.lock.acquire(blocking=False):return
        try:
            for tenant in ['a','b']:
                job=next((j for j in self.store.list(tenant,'browser_job') if j['status']=='PENDING'),None)
                if job:self.execute(tenant,job);break
        finally:self.lock.release()

    def execute(self,tenant,job):
        profile=self.config().get(job['profile_id'],{})
        if not profile.get('enabled'):
            self.store.update(tenant,'browser_job',job['id'],{'status':'FAILED','error':'站点配置已停用'});return
        self.store.update(tenant,'browser_job',job['id'],{'status':'RUNNING'})
        candidates=[]
        try:
            own=self.capture.own(tenant,job['own_id'])
            if own['version']!=job['own_version']:raise ValueError('自有商品已修改，请重新搜索')
            from playwright.sync_api import sync_playwright
            os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(Path(__file__).resolve().parents[1]/'.browsers'))
            url=profile['search_url'].replace('{query}',quote(job['query']))
            safe_url(url,profile['domains'])
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True)
                try:
                    context=browser.new_context(viewport={'width':1280,'height':900},service_workers='block',accept_downloads=False)
                    # Bound every redirect/subresource too; fail closed on DNS errors.
                    requests=[0]
                    def route(request_route):
                        try:
                            requests[0]+=1
                            if requests[0]>120:raise ValueError('请求预算耗尽')
                            safe_url(request_route.request.url,profile['domains'])
                            request_route.continue_()
                        except Exception:request_route.abort()
                    context.route('**/*',route)
                    context.route_web_socket('**/*',lambda ws:ws.close())
                    page=context.new_page();page.set_default_timeout(10000)
                    response=page.goto(url,wait_until='domcontentloaded',timeout=20000)
                    text=page.locator('body').inner_text()[:30000]
                    reason=blocked(text,page.url,response.status if response else 0)
                    if reason:raise PermissionError(reason)
                    locator=page.locator(profile['result_link_selector'])
                    urls=[]
                    for i in range(min(locator.count(),20)):
                        href=locator.nth(i).get_attribute('href')
                        if not href:continue
                        candidate=urljoin(page.url,href)
                        if candidate not in urls:
                            try:safe_url(candidate,profile['domains']);urls.append(candidate)
                            except ValueError:continue
                        if len(urls)>=job['max_items']:break
                    for target in urls:
                        # Intentional pacing applies even within one search task.
                        time.sleep(max(2,min(profile.get('page_interval_seconds',3),10)))
                        response=page.goto(target,wait_until='domcontentloaded',timeout=20000)
                        text=page.locator('body').inner_text()[:30000]
                        reason=blocked(text,page.url,response.status if response else 0)
                        if reason:raise PermissionError(reason)
                        screenshot='data:image/png;base64,'+base64.b64encode(page.screenshot(full_page=False)).decode()
                        result=self.capture.collect(tenant,AssistedInput(own_id=job['own_id'],source_url=page.url,text=text,
                            image_data=screenshot,authorized=True,allow_model_processing=job['allow_model_processing']),mode='browser')
                        candidates.append(result['id'])
                finally:browser.close()
            self.store.update(tenant,'browser_job',job['id'],{'status':'COMPLETED','candidate_ids':candidates,
                'note':'未找到候选链接，请核验站点选择器或改用辅助采集' if not candidates else '候选待审核'})
        except PermissionError as exc:
            self.store.update(tenant,'browser_job',job['id'],{'status':'PAUSED','error':str(exc),'candidate_ids':candidates})
        except Exception as exc:
            self.store.update(tenant,'browser_job',job['id'],{'status':'FAILED','error':type(exc).__name__+': 浏览器执行失败，请核验依赖与站点配置','candidate_ids':candidates})

def routes(browser,identity):
    router=APIRouter(prefix='/api/v1/capture/browser')
    @router.post('/jobs',status_code=202)
    def enqueue(body:BrowserInput,tenant=Depends(identity)):return browser.enqueue(tenant,body)
    @router.post('/jobs/{id}/review')
    def acknowledge(id:str,tenant=Depends(identity)):
        with browser.capture.proto.service.lock:
            job=browser.store.get(tenant,'browser_job',id)
            if job['status']!='PAUSED':raise ValueError('任务并非暂停状态')
            # No resume into a challenge: reviewer acknowledges and cancels it.
            browser.store.audit(tenant,'browser_pause_acknowledged',{'job_id':id})
            return browser.store.update(tenant,'browser_job',id,{'status':'CANCELLED'})
    return router
