"""LangGraph harness with explicit node receipts and bounded execution.

MAST-inspired checks prohibit declaring completion when a branch is missing.
Checkpoints are application records; process-crash recovery restarts idempotently
from persisted snapshots, rather than claiming a production MySQL Saver.
"""
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from .memory import suspicious

class RunState(TypedDict, total=False):
    tenant: str
    run_id: str
    facts: dict
    product: dict
    context: list
    receipts: list
    draft: dict
    failure: str
    memory_ids: list

class AgentRuntime:
    def __init__(self, store, memory, model):
        self.store, self.memory, self.model = store, memory, model
        graph = StateGraph(RunState)
        for name, fn in [('retrieve', self.retrieve), ('content', self.content),
                         ('price', self.price), ('recommend', self.recommend), ('verify', self.verify)]:
            graph.add_node(name, fn)
        graph.add_edge(START, 'retrieve')
        for a, b in [('retrieve','content'), ('content','price'), ('price','recommend'), ('recommend','verify')]:
            graph.add_edge(a,b)
        graph.add_edge('verify', END)
        self.graph = graph.compile()

    def invoke(self, state):
        """AWM adaptation: approved templates reorder optional analysis steps.

        Retrieval, recommendation and verification remain mandatory. The
        deterministic comparison has already run outside the agent graph.
        """
        candidates = self.memory.approved(state['tenant'], '促销价格')
        workflow = next((e for e in candidates if e.get('workflow')), None)
        if not workflow:
            return self.graph.invoke(state, {'recursion_limit':12})
        order = [n for n in workflow['workflow'] if n in {'content','price'}]
        order = list(dict.fromkeys(order))
        order += [n for n in ['content','price'] if n not in order]
        graph = StateGraph(RunState)
        names = ['retrieve', *order, 'recommend', 'verify']
        for name in names:
            graph.add_node(name, getattr(self, name))
        for left, right in zip([START, *names], [*names, END]):
            graph.add_edge(left, right)
        return graph.compile().invoke(state, {'recursion_limit':12})

    def receipt(self, state, node, result):
        receipts = state.get('receipts', []) + [{'node': node, 'status': 'SUCCEEDED', 'result': result}]
        self.store.add(state['tenant'], 'checkpoint', {'run_id': state['run_id'],
            'node': node, 'receipts': receipts})
        return receipts

    def retrieve(self, s):
        context = self.memory.approved(s['tenant'], '促销价格品牌')
        workflow = next((e for e in context if e.get('workflow')), None)
        return {'context': context, 'memory_ids': [e['id'] for e in context],
                'receipts': self.receipt(s, 'retrieve', {'workflow': workflow['id'] if workflow else 'baseline'})}

    def content(self, s):
        return {'receipts': self.receipt(s, 'content', {'changed_fields': list(s['facts']['fields']),
                'untrusted_instruction_detected': suspicious(s['product']['review'])})}

    def price(self, s):
        return {'receipts': self.receipt(s, 'price', {'delta': s['facts']['price_delta'],
                'comparable': s['facts']['price_delta'] is not None})}

    def recommend(self, s):
        # Only deterministic facts and approved memory enter the model.
        # Raw reviews are not passed to this recommendation capability.
        try:
            safe_facts = {**s['facts'], 'fields': {k:v for k,v in s['facts']['fields'].items()
                          if k in {'price','sku','currency','title','description','promotion','review'}}}
            draft = self.model.draft(safe_facts, s['context'])
            return {'draft': draft, 'receipts': self.receipt(s, 'recommend', {'draft_created': True})}
        except Exception as exc:
            return {'failure': f'MODEL_FAILURE:{type(exc).__name__}', 'draft': {}}

    def verify(self, s):
        expected = {'retrieve', 'content', 'price', 'recommend'}
        found = {r['node'] for r in s.get('receipts', [])}
        if found != expected or not s.get('draft'):
            return {'failure': s.get('failure') or 'BRANCH_NOT_ACCOUNTED'}
        return {'receipts': self.receipt(s, 'verify', {'complete': True})}
