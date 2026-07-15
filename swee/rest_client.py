import httpx

from swee.config import REST_AUTH, REST_BASE


class PalRestClient:
    def __init__(self):
        self.client = httpx.AsyncClient(auth=REST_AUTH, timeout=5.0)

    async def get(self, path):
        r = await self.client.get(f"{REST_BASE}/{path}")
        r.raise_for_status()
        return r.json()

    async def post(self, path, payload=None):
        r = await self.client.post(f"{REST_BASE}/{path}", json=payload or {})
        r.raise_for_status()
        return r.json() if r.content else {}

    async def info(self):     return await self.get("info")
    async def players(self):  return await self.get("players")
    async def metrics(self):  return await self.get("metrics")
    async def announce(self, message):    return await self.post("announce", {"message": message})
    async def save(self):                 return await self.post("save")
    async def kick(self, uid, message=""): return await self.post("kick", {"userid": uid, "message": message})
    async def ban(self, uid, message=""):  return await self.post("ban", {"userid": uid, "message": message})


rest = PalRestClient()
