"""Small MCP tool registry shared by JSON-RPC and application tests.

Tenant identity comes from the authenticated request, never from arguments.
Approval and external network tools deliberately do not exist in this registry.
"""
from pydantic import BaseModel, ConfigDict

class Query(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query: str = ''

class Resource(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str

class Candidate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    content: str

class ToolGateway:
    schemas = {'memory.search_approved': Query, 'evidence.get_snapshot': Resource,
               'memory.propose_candidate': Candidate}

    def __init__(self, service):
        self.service = service

    def descriptors(self):
        return [{'name': name, 'description': name,
                 'inputSchema': schema.model_json_schema()} for name, schema in self.schemas.items()]

    def call(self, tenant, name, arguments):
        if name not in self.schemas:
            raise PermissionError('Tool capability is not granted')
        args = self.schemas[name].model_validate(arguments)
        if name == 'memory.search_approved':
            return self.service.memory.approved(tenant, args.query)
        if name == 'evidence.get_snapshot':
            return self.service.store.get(tenant, 'snapshot', args.id)
        with self.service.lock:
            return self.service.memory.propose(tenant, args.content)
