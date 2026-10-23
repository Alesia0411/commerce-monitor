"""HTTP contract tests with isolated storage (no changes to demo.db)."""
import importlib
from fastapi.testclient import TestClient

def test_http_and_mcp(tmp_path,monkeypatch):
    monkeypatch.setenv('ALLOW_LEGACY_TOKENS','1')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('DATABASE_URL','sqlite:///'+str(tmp_path/'http.db'))
    import app.config
    # Config is a frozen dataclass: replace the composition settings explicitly.
    from dataclasses import replace
    monkeypatch.setattr(app.config,'settings',replace(app.config.settings,
        database_url='sqlite:///'+str(tmp_path/'http.db'),scheduler_seconds=0,api_key=''))
    import app.main
    main=importlib.reload(app.main)
    with TestClient(main.app) as client:
        a={'Authorization':'Bearer local-demo-a'}
        b={'Authorization':'Bearer local-demo-b'}
        assert client.get('/api/state').status_code==401
        assert client.get('/').status_code==200
        assert client.post('/api/runs',headers=a,json={'scenario':'baseline'}).json()['status']=='BASELINE'
        result=client.post('/api/runs',headers=a,json={'scenario':'discount'}).json()
        identifier=result['recommendation_id']
        assert client.post(f'/api/recommendations/{identifier}/decision',headers=b,json={'decision':'APPROVED'}).status_code==404
        assert client.post(f'/api/recommendations/{identifier}/decision',headers=a,json={'decision':'APPROVED'}).status_code==200
        assert client.post(f'/api/recommendations/{identifier}/derive-workflow',headers=a).json()['status']=='CANDIDATE'
        rpc=client.post('/mcp',headers=a,json={'jsonrpc':'2.0','id':1,'method':'tools/list'}).json()
        assert len(rpc['result']['tools'])==3
        denied=client.post('/mcp',headers=a,json={'jsonrpc':'2.0','id':2,'method':'tools/call',
            'params':{'name':'memory.approve','arguments':{}}}).json()
        assert denied['result']['isError']
        # Full product -> durable job -> recommendation -> task lifecycle.
        product=client.post('/api/v1/products',headers=a,json={'title':'咖啡杯','item_id':'p1','sku':'300ml','price':'100','authorized':True}).json()
        job=client.post('/api/v1/jobs',headers=a,json={'product_id':product['id']})
        assert job.status_code==202
        main.prototype.tick()
        changed={**product,'price':'90'}
        assert client.put('/api/v1/products/'+product['id'],headers=a,json=changed).status_code==200
        assert client.put('/api/v1/products/'+product['id'],headers=a,json=changed).status_code==409
        client.post('/api/v1/jobs',headers=a,json={'product_id':product['id']})
        main.prototype.tick()
        rec=main.store.list('a','recommendation')[-1]
        client.post('/api/recommendations/'+rec['id']+'/decision',headers=a,json={'decision':'APPROVED'})
        task=client.post('/api/v1/tasks',headers=a,json={'recommendation_id':rec['id']}).json()
        assert client.patch('/api/v1/tasks/'+task['id'],headers=a,json={'status':'DOING','version':1}).status_code==200
        assert client.patch('/api/v1/tasks/'+task['id'],headers=a,json={'status':'DONE','version':2,'note':'完成'}).status_code==200
        assert client.get('/api/v1/report.md',headers=a).status_code==200
        # Password login and server-side read-only enforcement.
        main.access.add('a','reader','reader-long-password','viewer')
        login=client.post('/api/auth/login',json={'tenant':'a','username':'reader','password':'reader-long-password'}).json()
        viewer={'Authorization':'Bearer '+login['token']}
        assert client.get('/api/v1/workspace',headers=viewer).status_code==200
        assert client.post('/api/v1/jobs',headers=viewer,json={'product_id':product['id']}).status_code==403
        own=client.post('/api/v1/products',headers=a,json={'title':'自有杯','item_id':'own-capture','sku':'500ml','role':'own','authorized':True}).json()
        candidate=client.post('/api/v1/capture/assisted',headers=a,json={'own_id':own['id'],'text':'标题：竞品杯\n价格：88.00','authorized':True}).json()
        assert candidate['status']=='NEEDS_REVIEW'
        assert client.get('/api/v1/capture/evidence/'+candidate['evidence_id'],headers=b).status_code==404
        assert client.get('/api/v1/capture',headers=a).status_code==200
    main.store.engine.dispose()
