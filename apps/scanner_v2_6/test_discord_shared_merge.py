import asyncio
from pathlib import Path
from types import SimpleNamespace

from discord_control import TradeDiscord


async def main():
    cfg=SimpleNamespace(discord_guild_id=456,discord_command_audit_sec=60)
    scanner=SimpleNamespace(last_discord_command_audit_at=0,discord_command_repairs=0)
    client=TradeDiscord(scanner,cfg)
    names=[command.name for command in client.tree.get_commands()]
    assert names and len(names)==len(set(names))
    assert all(name.startswith("byscan_") for name in names)
    assert "byscan_edge_stats" in names and "byscan_health" in names
    class FakeHTTP:
        def __init__(self):self.upserts=[]
        async def get_guild_commands(self,*args):
            return [{"name":name} for name in names if name!="byscan_edge_stats"]
        async def upsert_guild_command(self,*args):self.upserts.append(args)
        async def close(self):pass
    fake=FakeHTTP();client.http=fake;client._connection.application_id=123
    repaired=await client._merge_commands(missing_only=True)
    assert repaired==1 and len(fake.upserts)==1 and scanner.discord_command_repairs==1
    await client.close()

    source=Path(__file__).with_name("discord_control.py").read_text(encoding="utf-8")
    assert "upsert_guild_command" in source and "upsert_global_command" in source
    assert "get_guild_commands" in source and "missing_only=True" in source
    assert "mode==\"replace\"" in source
    assert "without deleting existing Discord commands" in source
    print(f"OK: {len(names)} unique byscan_* commands and missing-only shared-bot repair")


asyncio.run(main())
