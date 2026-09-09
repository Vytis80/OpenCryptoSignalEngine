#!/usr/bin/env python3
from pathlib import Path

p=Path('.github/ai_live_patch.py')
s=p.read_text()

old='insert_before(V25/"storage.py", "            await db.commit()\\n", \'\'\''
new='insert_before(V25/"storage.py", "            shadow_cols={r[1] for r in await (await db.execute(\\"PRAGMA table_info(shadow_checks)\\")).fetchall()}\\n", \'\'\''
if old not in s:
    raise SystemExit('expected V2.5 storage migration anchor not found in patcher')
s=s.replace(old,new,1)

def escape_block_after(src,prefix,start,end):
    base=src.find(prefix)
    if base<0:
        raise SystemExit(f'prefix not found: {prefix[:60]!r}')
    i=src.find(start,base+len(prefix))
    if i<0:
        raise SystemExit(f'block start not found after prefix: {prefix[:60]!r}')
    j=src.find(end,i+len(start))
    if j<0:
        raise SystemExit(f'block end not found after prefix: {prefix[:60]!r}')
    body_start=i+len(start)
    body=src[body_start:j].replace('\\n','\\\\n')
    return src[:body_start]+body+src[j:]

s=escape_block_after(s,'p = V26 / "alerts.py"','insert_before(p, "    if blocks:\\n", \'\'\'','\'\'\')\n\np = V25 / "alerts.py"')
s=escape_block_after(s,'p = V25 / "alerts.py"','insert_before(p, "    if blocks:\\n", \'\'\'','\'\'\')\n\n# Storage schemas')
s=escape_block_after(s,'# Discord inspection commands.\n',"V26_COMMANDS='''","'''\ninsert_before(V26/\"discord_control.py\"")
s=escape_block_after(s,'insert_before(V26/"discord_control.py"',"V25_COMMANDS='''","'''\ninsert_before(V25/\"discord_control.py\"")

exec(compile(s,str(p),'exec'),{'__name__':'__main__'})
