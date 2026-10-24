#!/usr/bin/env python3
"""Standalone smoke test of the Protegus API client (no Home Assistant needed).

  pip install aiohttp
  python probe.py --email you@example.com --password '...'          # read-only
  python probe.py --token <JWT> --device-id <X-Device-Id>            # Google accounts
  python probe.py --token <JWT> --device-id <ID> --pgm <PGM_ID>      # toggles that PGM!
"""
import argparse, asyncio, importlib.util, pathlib, uuid
import aiohttp

spec = importlib.util.spec_from_file_location(
    "protegus_api", pathlib.Path(__file__).parent.parent / "custom_components/protegus/api.py")
api_mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(api_mod)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default="eu")
    ap.add_argument("--email"); ap.add_argument("--password"); ap.add_argument("--token")
    ap.add_argument("--device-id", help="X-Device-Id the token was issued for (required with --token)")
    ap.add_argument("--pgm", type=int, help="PGM id to toggle (changes real hardware state)")
    a = ap.parse_args()
    async with aiohttp.ClientSession() as s:
        api = api_mod.ProtegusApi(s, a.region, a.device_id or str(uuid.uuid4()), token=a.token)
        if a.email:
            await api.login(a.email, a.password)
            print("login ok")
        await api.load_profile()
        print("socket port:", api.socket_port, "| socket token:", bool(api.socket_token))
        for sysd in await api.get_systems():
            print(f"\nSystem {sysd['id']} '{sysd.get('name')}' online={sysd.get('online')} fw={sysd.get('fw_version')}")
            for ar in sysd.get("areas", []):
                print(f"  area {ar['id']} '{ar['name']}' status={ar['status']} alarm_in_memory={ar['alarm_in_memory']}")
            for p in sysd.get("pgms", []):
                if p.get("hw_assigned"):
                    print(f"  pgm {p['id']} '{p['name']}' type={p['type']} on={p['on']}")
        if a.pgm:
            print("toggle ->", await api.toggle_pgm(a.pgm))

asyncio.run(main())
