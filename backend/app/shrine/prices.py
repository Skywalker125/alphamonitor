"""USD value of the quote assets Shrine reports amounts in (mostly SOL)."""

import asyncio
import logging
import time

import httpx

log = logging.getLogger("alphamonitor.prices")

SOL = "So11111111111111111111111111111111111111112"
STABLES = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
    "USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB",  # USD1
}
JUPITER_URL = f"https://lite-api.jup.ag/price/v3?ids={SOL}"
COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"


class QuotePrices:
    def __init__(self, refresh_seconds: float = 30) -> None:
        self.refresh_seconds = refresh_seconds
        self.sol_usd: float | None = None
        self.updated_at: float | None = None
        self.source: str | None = None
        self._task: asyncio.Task | None = None

    def usd(self, quote_mint: str | None) -> float | None:
        """USD per 1 unit of the quote asset, or None if unknown."""
        if quote_mint in (None, SOL):
            return self.sol_usd
        if quote_mint in STABLES:
            return 1.0
        return None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _run(self) -> None:
        async with httpx.AsyncClient(timeout=10) as http:
            while True:
                await self.refresh(http)
                await asyncio.sleep(self.refresh_seconds)

    async def refresh(self, http: httpx.AsyncClient) -> None:
        for name, fetch in (("jupiter", self._jupiter), ("coingecko", self._coingecko)):
            try:
                price = await fetch(http)
            except Exception as e:
                log.debug("%s price failed: %s", name, e)
                continue
            if price and price > 0:
                self.sol_usd, self.updated_at, self.source = price, time.time(), name
                return
        log.warning("Could not refresh SOL/USD (keeping %s)", self.sol_usd)

    @staticmethod
    async def _jupiter(http: httpx.AsyncClient) -> float | None:
        data = (await http.get(JUPITER_URL)).raise_for_status().json()
        entry = data.get(SOL) or (data.get("data") or {}).get(SOL) or {}
        return float(entry.get("usdPrice") or entry.get("price") or 0) or None

    @staticmethod
    async def _coingecko(http: httpx.AsyncClient) -> float | None:
        data = (await http.get(COINGECKO_URL)).raise_for_status().json()
        return float(data["solana"]["usd"])
