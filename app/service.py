"""Application use cases. Local locking is intentionally single-process.

Compose also starts one worker process. A production deployment needs leases,
Outbox consumers and fencing before increasing worker count.
"""
import threading
from .ingestion import SourceFault, fingerprint, difference
from .runtime import AgentRuntime
from .memory import MemoryService

class MonitorService:
    def __init__(self, store, source, gate, model):
        self.store, self.source, self.gate = store, source, gate
        self.memory = MemoryService(store)
        self.runtime = AgentRuntime(store, self.memory, model)
        self.lock = threading.RLock()

    def seed(self, tenant):
        if not self.store.list(tenant, 'source'):
            self.store.add(tenant, 'source', {'status': 'ACTIVE', 'name': '合成授权源', 'reason': None}, 'default')
            entry = self.memory.propose(tenant, '品牌偏好：突出清洁便利性，促销前核验利润；禁止承诺销量。')
            self.memory.evaluate(tenant, entry['id'])
            self.memory.review(tenant, entry['id'], 'APPROVED')

    def run(self, tenant, scenario, key, supplied_product=None, product_id=None):
        with self.lock:
            self.seed(tenant)
            existing = next((r for r in self.store.list(tenant,'run') if r['request_key'] == key), None)
            if existing:
                return existing
            run = self.store.add(tenant, 'run', {'request_key': key, 'scenario': scenario,
                'status': 'RUNNING', 'synthetic': supplied_product is None, 'product_id':product_id}, key)
            source = self.store.list(tenant, 'source')[0]
            if source['status'] != 'ACTIVE':
                return self.finish(tenant, run['id'], status='PAUSED', error=source['reason'])
            try:
                self.gate.acquire()
                product = supplied_product if supplied_product is not None else self.source.fetch(scenario)
            except SourceFault as exc:
                if exc.code in {'429','403','captcha','expired','redis_unavailable'}:
                    self.store.update(tenant,'source',source['id'], {'status':'PAUSED', 'reason':exc.code})
                return self.finish(tenant, run['id'], status='FAILED', error=exc.code)
            snapshots = [s for s in self.store.list(tenant,'snapshot') if s.get('product_id') == product_id]
            before = snapshots[-1] if snapshots else None
            digest = fingerprint(product)
            self.store.add(tenant,'observation',{'hash':digest, 'run_id':run['id']})
            if before and before['hash'] == digest and before.get('active', True):
                return self.finish(tenant, run['id'], status='UNCHANGED')
            snapshot = self.store.add(tenant,'snapshot',{'product':product,'hash':digest,'active':True,'product_id':product_id})
            if not before or not before.get('active', True):
                return self.finish(tenant, run['id'],status='BASELINE', snapshot_id=snapshot['id'])
            facts = difference(before['product'],product)
            self.store.add(tenant,'change',{'facts':facts, 'evidence':[before['id'],snapshot['id']]})
            result = self.runtime.invoke({'tenant':tenant,'run_id':run['id'],
                'facts':facts,'product':product,'receipts':[]})
            if result.get('failure'):
                self.store.add(tenant,'failure',{'run_id':run['id'], 'category':'task_verification', 'code':result['failure']})
                return self.finish(tenant,run['id'], status='PARTIAL', error=result['failure'])
            rec = self.store.add(tenant,'recommendation',{**result['draft'], 'status':'DRAFT',
                'evidence':[before['id'],snapshot['id']], 'memory_ids':result.get('memory_ids',[]),
                'run_id':run['id'], 'facts':facts, 'product_id':product_id})
            return self.finish(tenant,run['id'],status='COMPLETED', recommendation_id=rec['id'])

    def finish(self, tenant, identifier, **data):
        return self.store.update(tenant,'run',identifier,data)

    def resume(self, tenant):
        with self.lock:
            row = self.store.list(tenant,'source')[0]
            self.store.audit(tenant,'source_resumed',{'source_id':row['id'], 'synthetic_only':True})
            return self.store.update(tenant,'source',row['id'],{'status':'ACTIVE','reason':None})

    def decide(self, tenant, identifier, decision):
        with self.lock:
            rec = self.store.get(tenant,'recommendation',identifier)
            if not all(self.store.get(tenant,'snapshot',e)['active'] for e in rec['evidence']):
                raise ValueError('Evidence revoked; regenerate analysis')
            if decision == 'APPROVED' and rec['status'] != 'DRAFT':
                raise ValueError('Only a current draft may be approved')
            return self.store.update(tenant,'recommendation',identifier,{'status':decision})

    def recover(self, tenant):
        # Do not claim completed work after a crash. New runs can retry safely.
        for run in self.store.list(tenant,'run'):
            if run['status'] == 'RUNNING':
                self.finish(tenant,run['id'],status='INTERRUPTED',error='Process restarted; retry with a new key')
