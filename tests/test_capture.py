import json
from types import SimpleNamespace
import pytest
from app.capture import CaptureService,Extractor,AssistedInput,ApprovalInput,decode_image
from app.browser_capture import BrowserCapture,BrowserInput,safe_url,blocked
from app.prototype import Prototype,ProductInput
from app.service import MonitorService
from app.store import Store
from app.ingestion import SyntheticSource,RateGate
from app.models import OfflineModel

@pytest.fixture
def capture(tmp_path):
    store=Store('sqlite:///'+str(tmp_path/'capture.db'))
    proto=Prototype(MonitorService(store,SyntheticSource(),RateGate(),OfflineModel()))
    own=proto.create_product('a',ProductInput(title='保温杯',sku='500ml-1',item_id='own',role='own',authorized=True))
    service=CaptureService(proto,Extractor(SimpleNamespace(api_key='',model='')))
    yield service,own
    store.engine.dispose()

def test_assisted_extract_review_dedup(capture):
    service,own=capture
    body=AssistedInput(own_id=own['id'],text='标题：竞品保温杯\n价格：99.00\n规格：500ml 单只\n促销：会员价',authorized=True)
    row=service.collect('a',body)
    assert row['fields']['price']=='99.00'
    assert row['method']=='offline_labels'
    assert service.collect('a',body)['id']==row['id']
    approval=ApprovalInput(title='竞品保温杯',item_id='comp',specification='500ml 单只',price='99.00',promotion='会员价')
    with pytest.raises(ValueError):service.approve('a',row['id'],approval)
    approval=approval.model_copy(update={'authorized':True,'same_spec_confirmed':True})
    result=service.approve('a',row['id'],approval)
    assert result['status']=='APPROVED'
    assert service.approve('a',row['id'],approval)['id']==result['id']
    assert len(service.store.list('a','pair'))==1
    assert service.store.get('a','product',result['product_id'])['observed_specification']=='500ml 单只'

def test_tenant_and_stale(capture):
    service,own=capture
    body=AssistedInput(own_id=own['id'],text='标题：竞品',authorized=True)
    with pytest.raises(KeyError):service.collect('b',body)
    row=service.collect('a',body)
    service.store.update('a','product',own['id'],{'version':2})
    with pytest.raises(ValueError):service.approve('a',row['id'],ApprovalInput(title='竞品',item_id='c',specification='500ml',same_spec_confirmed=True,authorized=True))

def test_image_requires_visual_model(capture):
    service,own=capture
    # Header fixture validates protocol checks only, not pixel decoding quality.
    image='data:image/png;base64,iVBORw0KGgo='
    row=service.collect('a',AssistedInput(own_id=own['id'],image_data=image,authorized=True))
    assert row['method']=='manual_required'
    assert not row['fields']['title']
    with pytest.raises(ValueError):decode_image('data:image/svg+xml;base64,AAAA')
    with pytest.raises(ValueError):decode_image('data:image/png;base64,AAAA')

def test_network_policy_and_challenge(monkeypatch):
    monkeypatch.setattr('app.browser_capture.socket.getaddrinfo',lambda *a,**k:[(2,1,6,'',('127.0.0.1',443))])
    with pytest.raises(ValueError):safe_url('https://allowed.example/',['allowed.example'])
    with pytest.raises(ValueError):safe_url('https://evil.example/',['allowed.example'])
    with pytest.raises(ValueError):safe_url('http://allowed.example/',['allowed.example'])
    assert blocked('请完成验证','https://allowed.example/',200)
    assert blocked('','https://allowed.example/',429)
    assert blocked('商品详情','https://allowed.example/item',200) is None

def test_browser_config_cooldown_and_paused(capture,tmp_path,monkeypatch):
    service,own=capture
    path=tmp_path/'profiles.json';path.write_text(json.dumps({'test':{'enabled':True,'name':'test','domains':['allowed.example'],'search_url':'https://allowed.example/?q={query}','result_link_selector':'a'}}))
    monkeypatch.setenv('BROWSER_PROFILES_FILE',str(path))
    browser=BrowserCapture(service)
    body=BrowserInput(own_id=own['id'],profile_id='test',authorized=True)
    job=browser.enqueue('a',body)
    assert job['status']=='PENDING'
    with pytest.raises(ValueError):browser.enqueue('a',body)
    service.store.update('a','browser_job',job['id'],{'status':'PAUSED'})
    with pytest.raises(ValueError):browser.enqueue('a',body)
