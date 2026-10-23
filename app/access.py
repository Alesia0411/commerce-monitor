"""Local accounts, PBKDF2 passwords and expiring bearer sessions.

Bootstrap secrets are generated once and written to a local ignored file.
Production should use an enterprise identity provider and managed secrets.
"""
import hashlib
import hmac
import json
import secrets
from datetime import datetime,timezone,timedelta
from pathlib import Path
from fastapi import APIRouter,HTTPException,Header
from pydantic import BaseModel,Field

def password_hash(password,salt):
    return hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),200000).hex()

class Login(BaseModel):
    tenant:str
    username:str
    password:str=Field(max_length=200)

class Member(BaseModel):
    username:str=Field(min_length=2,max_length=60)
    password:str=Field(min_length=10,max_length=200)
    role:str

class Access:
    def __init__(self,store):self.store=store

    def bootstrap(self):
        credentials=[]
        for tenant in ['a','b']:
            if not self.store.list(tenant,'member'):
                password=secrets.token_urlsafe(16)
                self.add(tenant,'admin',password,'admin')
                credentials.append({'tenant':tenant,'username':'admin','password':password})
        if credentials:
            target=Path('.local-credentials.json')
            target.write_text(json.dumps(credentials,ensure_ascii=False,indent=2),encoding='utf-8')

    def add(self,tenant,username,password,role):
        if role not in {'admin','operator','reviewer','viewer'}:raise ValueError('无效角色')
        if any(m['username']==username for m in self.store.list(tenant,'member')):raise ValueError('用户名已存在')
        salt=secrets.token_hex(16)
        self.store.add(tenant,'member',{'username':username,'salt':salt,'hash':password_hash(password,salt),'role':role})
        return {'username':username,'role':role}

    def resolve(self,token):
        digest=hashlib.sha256(token.encode()).hexdigest()
        for tenant in ['a','b']:
            for session in self.store.list(tenant,'session'):
                if hmac.compare_digest(session['digest'],digest) and session['active'] and datetime.fromisoformat(session['expires'])>datetime.now(timezone.utc):
                    return {'tenant':tenant,'role':session['role'],'username':session['username'],'session_id':session['id']}
        return None

def routes(access):
    router=APIRouter(prefix='/api/auth')
    @router.post('/login')
    def login(body:Login):
        if body.tenant not in {'a','b'}:raise HTTPException(401,'账号或密码错误')
        # Persistent attempt log limits repeated failures without trusting IP headers.
        recent=[r for r in access.store.list(body.tenant,'login_attempt') if r['username']==body.username and (datetime.now(timezone.utc)-datetime.fromisoformat(r['created'])).total_seconds()<60]
        if len(recent)>=10:raise HTTPException(429,'尝试过于频繁，请稍后再试')
        access.store.add(body.tenant,'login_attempt',{'username':body.username})
        member=next((m for m in access.store.list(body.tenant,'member') if m['username']==body.username),None)
        if not member or not hmac.compare_digest(password_hash(body.password,member['salt']),member['hash']):
            raise HTTPException(401,'账号或密码错误')
        token=secrets.token_urlsafe(32)
        access.store.add(body.tenant,'session',{'digest':hashlib.sha256(token.encode()).hexdigest(),
            'expires':(datetime.now(timezone.utc)+timedelta(hours=8)).isoformat(),'active':True,'role':member['role'],'username':member['username']})
        return {'token':token,'tenant':body.tenant,'role':member['role'],'username':member['username']}

    def principal(authorization):
        who=access.resolve(authorization.removeprefix('Bearer '))
        if not who:raise HTTPException(401,'请登录')
        return who

    @router.post('/logout')
    def logout(authorization:str=Header(default='')):
        who=principal(authorization)
        access.store.update(who['tenant'],'session',who['session_id'],{'active':False})
        return {'status':'LOGGED_OUT'}

    @router.post('/members')
    def member(body:Member,authorization:str=Header(default='')):
        who=principal(authorization)
        if who['role']!='admin':raise HTTPException(403,'需要管理员权限')
        return access.add(who['tenant'],body.username,body.password,body.role)

    return router
