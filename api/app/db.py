"""本地数据库连接与会话管理。"""

import os

from sqlalchemy import URL, create_engine
from sqlalchemy.orm import sessionmaker

url = URL.create(
    "postgresql+psycopg",
    username=os.getenv("PGUSER", os.getenv("POSTGRES_USER", "etf_sentinel")),
    password=os.getenv("PGPASSWORD", os.getenv("POSTGRES_PASSWORD", "")),
    host=os.getenv("PGHOST", "localhost"),
    port=int(os.getenv("PGPORT", "5432")),
    database=os.getenv("PGDATABASE", os.getenv("POSTGRES_DB", "etf_sentinel")),
)
engine = create_engine(url, pool_pre_ping=True)
Session = sessionmaker(engine, expire_on_commit=False)
