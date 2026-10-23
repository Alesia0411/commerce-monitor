from app.access import Access, password_hash
from app.store import Store
from datetime import datetime,timezone,timedelta
import hashlib

def test_accounts_sessions_and_expiry(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    store=Store('sqlite:///'+str(tmp_path/'access.db'))
    access=Access(store);access.bootstrap()
    assert (tmp_path/'.local-credentials.json').exists()
    access.add('a','operator','a-long-test-password','operator')
    user=store.list('a','member')[-1]
    assert user['hash']==password_hash('a-long-test-password',user['salt'])
    assert 'password' not in user
    session=store.add('a','session',{'digest':hashlib.sha256(b'test-token').hexdigest(),'expires':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'active':True,'role':'viewer','username':'reader'})
    assert access.resolve('test-token')['role']=='viewer'
    store.update('a','session',session['id'],{'active':False})
    assert access.resolve('test-token') is None
    store.engine.dispose()
