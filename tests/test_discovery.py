import pytest
from app.discovery import Discovery,SearchInput
from app.prototype import ProductInput,Prototype
from app.service import MonitorService
from app.store import Store
from app.ingestion import SyntheticSource,RateGate
from app.models import OfflineModel

@pytest.fixture
def setup(tmp_path):
    store=Store('sqlite:///'+str(tmp_path/'discovery.db'))
    proto=Prototype(MonitorService(store,SyntheticSource(),RateGate(),OfflineModel()))
    own=proto.create_product('a',ProductInput(title='轻量保温杯500ml',item_id='own',sku='500ml-1',category='保温杯',role='own',authorized=True))
    yield proto,own,Discovery(proto)
    store.engine.dispose()

def add_catalog(proto,tenant='a',**changes):
    data=ProductInput(title='轻量保温杯500ml',item_id='other',sku='500ml-1',category='保温杯',authorized=True).model_dump()
    return proto.store.add(tenant,'catalog',{**data,'active':True,'version':1,**changes})

def test_search_auto_link_dedup(setup):
    proto,own,discovery=setup;add_catalog(proto)
    result=discovery.search('a',SearchInput(own_id=own['id'],auto_link=True))
    assert len(result['linked'])==1
    assert len(proto.store.list('a','product'))==2
    discovery.search('a',SearchInput(own_id=own['id'],auto_link=True))
    assert len(proto.store.list('a','pair'))==1

def test_empty_and_tenant_scope(setup):
    proto,own,discovery=setup;add_catalog(proto,'b')
    assert not discovery.search('a',SearchInput(own_id=own['id']))['candidates']
    with pytest.raises(KeyError):discovery.search('b',SearchInput(own_id=own['id']))

def test_mismatch_and_stale(setup):
    proto,own,discovery=setup
    add_catalog(proto,sku='1L-1')
    result=discovery.search('a',SearchInput(own_id=own['id'],auto_link=True))
    assert not result['linked']
    with pytest.raises(ValueError):discovery.link('a',result['id'],[result['candidates'][0]['candidate_id']])
    proto.store.update('a','product',own['id'],{'version':2})
    with pytest.raises(ValueError):discovery.link('a',result['id'],['made-up'])

def test_registered_candidate_and_unknown_category(setup):
    proto,own,discovery=setup
    p=proto.create_product('a',ProductInput(title=own['title'],item_id='registered',sku=own['sku'],authorized=True))
    result=discovery.search('a',SearchInput(own_id=own['id'],auto_link=True))
    assert not result['linked']
    ids=[c['candidate_id'] for c in result['candidates']]
    linked=discovery.link('a',result['id'],ids)
    assert linked[0]['competitor_id']==p['id']
    assert len(proto.store.list('a','product'))==2
