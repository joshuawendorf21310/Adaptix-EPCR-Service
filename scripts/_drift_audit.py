import asyncio
from sqlalchemy import text
from epcr_app import models
from epcr_app.db import _get_session_maker, _require_database_url


async def main():
    sm = _get_session_maker(_require_database_url())
    eng = sm.kw['bind']
    async with eng.connect() as c:
        for tbl in sorted(models.Base.metadata.tables.values(), key=lambda t: t.name):
            r = await c.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name=:t"),
                {"t": tbl.name},
            )
            db_cols = {row[0] for row in r}
            if not db_cols:
                continue
            orm_cols = {col.name for col in tbl.columns}
            missing = orm_cols - db_cols
            if missing:
                print(tbl.name, sorted(missing))


asyncio.run(main())
