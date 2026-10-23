"""SQL adapter. SQLite for single-process local use; MySQL for Compose.

Payloads simplify this demo's schema. Tenant and kind are indexed columns,
not model-generated filters. Production migrations should promote hot fields.
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import create_engine, String, JSON, UniqueConstraint, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

def now():
    return datetime.now(timezone.utc).isoformat()

class Base(DeclarativeBase):
    pass

class Record(Base):
    __tablename__ = 'records'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    key: Mapped[str] = mapped_column(String(191))
    payload: Mapped[dict] = mapped_column(JSON)
    created: Mapped[str] = mapped_column(String(40))
    __table_args__ = (UniqueConstraint('tenant', 'kind', 'key'),)

class Store:
    def __init__(self, url):
        args = {'check_same_thread': False} if url.startswith('sqlite') else {}
        self.engine = create_engine(url, connect_args=args, pool_pre_ping=True)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def add(self, tenant, kind, data, key=None):
        identifier = str(uuid.uuid4())
        with self.sessions.begin() as s:
            row = Record(id=identifier, tenant=tenant, kind=kind,
                         key=key or identifier, payload=data, created=now())
            s.add(row)
        return self.get(tenant, kind, identifier)

    @staticmethod
    def as_dict(row):
        return {'id': row.id, 'created': row.created, **row.payload}

    def get(self, tenant, kind, identifier):
        with self.sessions() as s:
            row = s.scalar(select(Record).where(Record.tenant == tenant,
                Record.kind == kind, Record.id == identifier))
            if row is None:
                raise KeyError('Resource not found in this tenant')
            return self.as_dict(row)

    def list(self, tenant, kind):
        with self.sessions() as s:
            return [self.as_dict(r) for r in s.scalars(select(Record).where(
                Record.tenant == tenant, Record.kind == kind).order_by(Record.created))]

    def update(self, tenant, kind, identifier, changes):
        with self.sessions.begin() as s:
            row = s.scalar(select(Record).where(Record.tenant == tenant,
                Record.kind == kind, Record.id == identifier).with_for_update())
            if row is None:
                raise KeyError('Resource not found in this tenant')
            row.payload = {**row.payload, **changes}
        return self.get(tenant, kind, identifier)

    def audit(self, tenant, event, detail):
        self.add(tenant, 'audit', {'event': event, 'detail': detail})
