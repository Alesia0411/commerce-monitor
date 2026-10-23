from app.prototype import Prototype, ProductInput
from app.store import Store
from app.service import MonitorService
from app.ingestion import SyntheticSource, RateGate
from app.models import OfflineModel
import pytest

@pytest.fixture
def proto(tmp_path):
    store=Store('sqlite:///'+str(tmp_path/'prototype.db'))
    service=MonitorService(store,SyntheticSource(),RateGate(limit=1000),OfflineModel())
    service.seed('a');service.seed('b')
    yield Prototype(service)
    store.engine.dispose()

def product(identifier='1',price='109'):
    return ProductInput(title='商品'+identifier,item_id=identifier,sku='500ml',price=price,authorized=True)

def test_independent_products_and_frozen_jobs(proto):
    a=proto.create_product('a',product());b=proto.create_product('a',product('2','200'))
    first=proto.enqueue('a',a['id'],'one');proto.enqueue('a',b['id'],'two')
    proto.tick()
    assert [j['result'] for j in proto.store.list('a','job')]==['BASELINE','BASELINE']
    assert proto.enqueue('a',a['id'],'one')['id']==first['id']
    proto.store.update('a','product',a['id'],{'price':'99.00','version':2})
    proto.enqueue('a',a['id'],'three')
    proto.store.update('a','product',a['id'],{'price':'88.00','version':3})
    proto.tick()
    rec=proto.store.list('a','recommendation')[0]
    assert rec['product_id']==a['id']
    assert rec['facts']['price_delta']=='-10.00'

def test_authorization_and_duplicates(proto):
    with pytest.raises(ValueError):proto.create_product('a',ProductInput(title='无授权',item_id='0',sku='x'))
    row=proto.create_product('a',product())
    with pytest.raises(ValueError):proto.create_product('a',product())
    with pytest.raises(KeyError):proto.enqueue('b',row['id'],'foreign')
    for price in ['NaN','-1','Infinity']:
        with pytest.raises(ValueError):product(price=price)

def test_plan_and_recovery(proto):
    p=proto.create_product('a',product())
    proto.store.add('a','plan',{'product_id':p['id'],'interval_minutes':60,'enabled':True,'next_due':'2020-01-01T00:00:00+00:00'})
    proto.tick();proto.tick()
    assert len(proto.store.list('a','job'))==1
    j=proto.enqueue('a',p['id'],'crash')
    proto.store.update('a','job',j['id'],{'status':'RUNNING'})
    proto.recover()
    assert proto.store.get('a','job',j['id'])['status']=='FAILED'
