#!/usr/bin/env python3
from pathlib import Path

p=Path('.github/ai_live_patch.py')
s=p.read_text()
old='insert_before(V25/"storage.py", "            await db.commit()\\n", \'\'\''
new='insert_before(V25/"storage.py", "            shadow_cols={r[1] for r in await (await db.execute(\\"PRAGMA table_info(shadow_checks)\\")).fetchall()}\\n", \'\'\''
if old not in s:
    raise SystemExit('expected V2.5 storage migration anchor not found in patcher')
s=s.replace(old,new,1)
exec(compile(s,str(p),'exec'),{'__name__':'__main__'})
