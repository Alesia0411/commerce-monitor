"""AWM + MemoryOS adaptations; MINJA-inspired admission control.

These are constrained engineering adaptations, not full algorithm reproductions.
The workflow DSL can reference approved operators, never executable source code.
"""
from datetime import datetime, timezone

OPERATORS = {'compare', 'retrieve', 'price', 'content', 'verify'}

def suspicious(text):
    # Heuristic triage only. Actual safety comes from no approval capability,
    # scoped tools and independent review, not keyword detection alone.
    return any(term in text.lower() for term in
               ['忽略规则', '导出其他租户', 'ignore previous', 'system:', '批准这条记忆'])

class MemoryService:
    def __init__(self, store):
        self.store = store

    def propose(self, tenant, content, tier='long', workflow=None, evidence=None):
        if workflow and (not workflow or not set(workflow) <= OPERATORS):
            raise ValueError('Workflow contains unsupported operators')
        if evidence:
            self.store.get(tenant, 'snapshot', evidence)
        return self.store.add(tenant, 'memory', {'content': content,
            'tier': tier, 'workflow': workflow, 'evidence': evidence,
            'status': 'QUARANTINED' if suspicious(content) else 'CANDIDATE',
            'version': 1, 'valid_until': None, 'submitted_by': 'agent',
            'paper': 'AWM' if workflow else 'MemoryOS', 'eval_passed': False})

    def evaluate(self, tenant, identifier):
        entry = self.store.get(tenant, 'memory', identifier)
        passed = not suspicious(entry['content']) and entry['status'] != 'RETIRED'
        if entry.get('workflow'):
            passed = passed and 'verify' in entry['workflow'] and 'compare' in entry['workflow']
        self.store.update(tenant, 'memory', identifier, {'eval_passed': passed})
        return {'passed': passed, 'scope': 'DSL/schema + deterministic safety checks; not LLM quality evaluation'}

    def review(self, tenant, identifier, decision):
        entry = self.store.get(tenant, 'memory', identifier)
        if decision == 'APPROVED' and (entry['status'] != 'CANDIDATE' or not entry['eval_passed']):
            raise ValueError('Only evaluated candidates can be approved')
        if decision == 'APPROVED' and entry.get('evidence'):
            if not self.store.get(tenant, 'snapshot', entry['evidence']).get('active', True):
                raise ValueError('Evidence has been revoked')
        self.store.audit(tenant, 'memory_review', {'id': identifier, 'decision': decision})
        return self.store.update(tenant, 'memory', identifier, {'status': decision})

    def approved(self, tenant, query=''):
        entries = []
        for entry in self.store.list(tenant, 'memory'):
            if entry['status'] != 'APPROVED':
                continue
            if entry.get('valid_until') and datetime.fromisoformat(entry['valid_until']) <= datetime.now(timezone.utc):
                continue
            if entry.get('evidence') and not self.store.get(tenant, 'snapshot', entry['evidence']).get('active', True):
                continue
            entries.append(entry)
        # Minimal RAG: lexical matching with tenant/status filtering before ranking.
        terms = set(query)
        return sorted(entries, key=lambda e: len(terms & set(e['content'])), reverse=True)[:4]

    def revoke(self, tenant, evidence_id):
        # Mark the root first: runtime retrieval checks it even before propagation.
        self.store.update(tenant, 'snapshot', evidence_id, {'active': False})
        affected = []
        for entry in self.store.list(tenant, 'memory'):
            if entry.get('evidence') == evidence_id:
                self.store.update(tenant, 'memory', entry['id'], {'status': 'RETIRED'})
                affected.append(entry['id'])
        for rec in self.store.list(tenant, 'recommendation'):
            if evidence_id in rec['evidence'] or set(affected) & set(rec.get('memory_ids', [])):
                self.store.update(tenant, 'recommendation', rec['id'], {'status': 'NEEDS_REVIEW'})
        self.store.audit(tenant, 'evidence_revoked', {'id': evidence_id, 'memory_ids': affected})
        return {'retired_memory_ids': affected}
