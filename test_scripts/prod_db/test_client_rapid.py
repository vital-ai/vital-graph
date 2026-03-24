#!/usr/bin/env python3
"""Rapid: hit list_spaces + list_graphs 10x with separate connections to spread across LB targets."""
import httpx
import asyncio

BASE = "https://vitalgraph.cardiffbank.co"


async def one_round(i: int):
    """Each round uses a fresh client to force new LB connection."""
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        login = await c.post(
            f"{BASE}/api/login",
            data={"username": "admin", "password": "admin"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        token = login.json().get("access_token")
        h = {"Authorization": "Bearer " + token}

        sr = await c.get(f"{BASE}/api/spaces", headers=h)
        spaces = sr.json().get("spaces", [])
        space_names = [s.get("space") for s in spaces]

        graphs_status = "-"
        graphs_body = ""
        if spaces:
            sid = spaces[0]["space"]
            gr = await c.get(f"{BASE}/api/graphs/{sid}/graphs", headers=h)
            graphs_status = gr.status_code
            graphs_body = gr.text[:120]

        print(f"Run {i+1:2d}: spaces={sr.status_code} ({len(spaces)}: {space_names})  graphs={graphs_status} {graphs_body}")


async def main():
    for i in range(10):
        await one_round(i)

asyncio.run(main())
