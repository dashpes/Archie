"""Congressional Trades Collector for House and Senate stock trading disclosures."""

import html as html_lib
import re
from datetime import date, datetime, timedelta

import httpx
from loguru import logger
from sqlalchemy import select

from .base import BaseCollector, CollectorResult
from .insider import is_junk_ticker
from ..storage import CongressionalTrade

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(cell: str) -> str:
    """Collapse an HTML table cell to clean text."""
    return " ".join(html_lib.unescape(_TAG_RE.sub(" ", cell)).split())


class CongressTradesCollector(BaseCollector):
    """
    Collector for congressional stock trading disclosures.

    Source is the official Senate eFD system (see ``fetch_senate_efd_trades``).
    House PTRs are scanned PDFs and remain unsourced.

    Saves discovered trades as CongressionalTrade records, deduplicating on the
    unique constraint.
    """

    name = "congress_trades"
    rate_limit_calls = 10  # Conservative for public APIs
    rate_limit_period = 60
    max_retries = 3
    retry_delay = 2.0

    # User agent for requests
    USER_AGENT = "InvestmentMonitor/1.0 (Congressional Trade Tracker)"

    # ------------------------------------------------------------------ #
    # Senate eFD — the OFFICIAL live source (the House side has no machine-readable feed).
    # ------------------------------------------------------------------ #
    EFD_BASE = "https://efdsearch.senate.gov"
    EFD_HOME = "https://efdsearch.senate.gov/search/home/"
    EFD_DATA = "https://efdsearch.senate.gov/search/report/data/"

    async def fetch_senate_efd_trades(self, *, days_back: int = 7) -> list[dict]:
        """PTR trades from the official Senate eFD system.

        Handshake: GET the search home for the CSRF form token, POST the
        prohibition agreement to unlock the session, then page the DataTables
        JSON endpoint for PTRs *submitted* in the last ``days_back`` days and
        parse each electronic PTR's HTML transaction table. Paper PTRs (scanned
        images, href ``/search/view/paper/``) cannot be parsed and are skipped.
        Returns raw dicts shaped for :meth:`parse_trade`.
        """
        trades: list[dict] = []
        async with httpx.AsyncClient(
            headers={"User-Agent": self.USER_AGENT}, timeout=30.0
        ) as client:
            await self._rate_limit()
            r = await client.get(self.EFD_HOME)
            r.raise_for_status()
            m = re.search(r'name="csrfmiddlewaretoken"\s+value="([^"]+)"', r.text)
            if not m:
                raise RuntimeError("eFD: could not find CSRF form token")
            await self._rate_limit()
            await client.post(
                self.EFD_HOME,
                data={"prohibition_agreement": "1", "csrfmiddlewaretoken": m.group(1)},
                headers={"Referer": self.EFD_HOME},
            )
            token = client.cookies.get("csrftoken")
            if not token:
                raise RuntimeError("eFD: agreement handshake did not yield a session")

            submitted_start = (
                (date.today() - timedelta(days=max(1, days_back))).strftime("%m/%d/%Y")
                + " 00:00:00"
            )
            start, total = 0, None
            while total is None or start < total:
                await self._rate_limit()
                resp = await client.post(
                    self.EFD_DATA,
                    data={
                        "start": str(start), "length": "100",
                        "report_types": "[11]",  # 11 = Periodic Transaction Report
                        "filer_types": "[]", "submitted_start_date": submitted_start,
                        "submitted_end_date": "", "candidate_state": "",
                        "senator_state": "", "office_id": "",
                        "first_name": "", "last_name": "",
                    },
                    headers={"Referer": f"{self.EFD_BASE}/search/", "X-CSRFToken": token},
                )
                resp.raise_for_status()
                payload = resp.json()
                rows = payload.get("data", [])
                total = int(payload.get("recordsTotal", 0))
                if not rows:
                    break
                for row in rows:
                    try:
                        first, last, _display, link_html, filed = row[:5]
                        lm = re.search(r'href="(/search/view/ptr/[^"]+)"', link_html)
                        if not lm:
                            continue  # paper filing — no parseable table
                        url = self.EFD_BASE + lm.group(1)
                        senator = " ".join(f"{first} {last}".replace(",", " ").split())
                        trades.extend(
                            await self._parse_efd_ptr_page(client, url, senator, filed)
                        )
                    except Exception as e:  # noqa: BLE001 - one bad PTR must not abort the run
                        logger.debug(f"{self.name}: eFD PTR parse failed: {e}")
                start += len(rows)
        logger.info(f"{self.name}: fetched {len(trades)} Senate eFD trades")
        return trades

    async def _parse_efd_ptr_page(
        self, client: httpx.AsyncClient, url: str, senator: str, filed: str
    ) -> list[dict]:
        """Parse one electronic PTR's transaction table into parse_trade-ready dicts.

        Columns: # | Transaction Date | Owner | Ticker | Asset Name | Asset Type |
        Type | Amount | Comment. Non-equity rows keep ticker '--' and are dropped
        later by the shared junk-ticker filter.
        """
        await self._rate_limit()
        r = await client.get(url, headers={"Referer": f"{self.EFD_BASE}/search/"})
        r.raise_for_status()
        out: list[dict] = []
        for row in re.findall(r"<tr>(.*?)</tr>", r.text, re.DOTALL):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
            if len(cells) < 8:
                continue
            txn_date, _owner, ticker, asset, _asset_type, ttype, amount = (
                _strip_html(c) for c in cells[1:8]
            )
            out.append({
                "senator": senator,
                "transaction_date": txn_date,
                "ticker": ticker,
                "asset_description": asset,
                "type": ttype,
                "amount": amount,
                "disclosure_date": filed,
                "source_url": url,
            })
        return out

    def _normalize_trade_type(self, raw_type: str | None) -> str:
        """
        Normalize trade type to standard format (buy/sell/exchange).

        Args:
            raw_type: Raw trade type from API (e.g., "purchase", "Sale", "exchange")

        Returns:
            Normalized trade type: "buy", "sell", or "exchange"
        """
        if not raw_type:
            return "unknown"

        raw_lower = raw_type.strip().lower()

        # Map various forms to standard types
        if raw_lower in ("purchase", "buy", "bought"):
            return "buy"
        elif raw_lower in ("sale", "sell", "sold", "sale (full)", "sale (partial)"):
            return "sell"
        elif raw_lower in ("exchange",):
            return "exchange"
        else:
            # Keep original for unknown types
            return raw_lower

    def _parse_date(self, date_str: str | None) -> date | None:
        """
        Parse a date string into a date object.

        Handles multiple date formats commonly found in the APIs.

        Args:
            date_str: Date string in various formats

        Returns:
            Parsed date object or None if parsing fails
        """
        if not date_str:
            return None

        date_str = date_str.strip()
        if not date_str or date_str.lower() in ("n/a", "none", "--"):
            return None

        # Try multiple formats
        formats = [
            "%Y-%m-%d",
            "%m/%d/%Y",
            "%m-%d-%Y",
            "%Y/%m/%d",
            "%d-%m-%Y",
            "%d/%m/%Y",
        ]

        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue

        logger.debug(f"Could not parse date: {date_str}")
        return None

    def parse_trade(self, raw: dict, chamber: str) -> CongressionalTrade | None:
        """
        Parse raw trade data into a CongressionalTrade object.

        Handles different field names between House and Senate APIs.

        Args:
            raw: Raw trade dictionary from API
            chamber: "House" or "Senate"

        Returns:
            CongressionalTrade object or None if parsing fails or data is invalid
        """
        try:
            # Get politician name (different field names)
            if chamber == "House":
                politician = raw.get("representative", "").strip()
            else:
                politician = raw.get("senator", "").strip()

            if not politician:
                return None

            # Get ticker - required field. Drop placeholders/non-issuer tokens via
            # the shared junk-ticker filter so the set can't diverge across sources.
            ticker = raw.get("ticker", "").strip().upper()
            if is_junk_ticker(ticker):
                return None

            # Get trade type and normalize
            raw_trade_type = raw.get("type", "")
            trade_type = self._normalize_trade_type(raw_trade_type)

            # Get amount range - required field
            amount_range = raw.get("amount", "").strip()
            if not amount_range or amount_range == "--":
                return None

            # Get trade date - required field
            trade_date_str = raw.get("transaction_date", "")
            trade_date = self._parse_date(trade_date_str)
            if not trade_date:
                return None

            # Get disclosure date - optional
            disclosure_date_str = raw.get("disclosure_date", "")
            disclosure_date = self._parse_date(disclosure_date_str)

            # Get party - optional
            party = raw.get("party", "").strip() or None

            # Get description - optional
            description = raw.get("asset_description", "").strip() or None

            # Prefer the source's own URL (eFD provides the PTR link); fall back to
            # the legacy constructed reference for the old S3-shaped dicts.
            source_url = (raw.get("source_url") or "").strip() or None
            if source_url is None:
                if chamber == "House":
                    source_url = (
                        f"https://housestockwatcher.com/summary_by_rep/{politician}"
                    )
                else:
                    source_url = (
                        f"https://senatestockwatcher.com/summary_by_senator/{politician}"
                    )

            return CongressionalTrade(
                ticker=ticker,
                politician=politician,
                party=party,
                chamber=chamber,
                trade_type=trade_type,
                amount_range=amount_range,
                trade_date=trade_date,
                disclosure_date=disclosure_date,
                description=description,
                source_url=source_url,
            )

        except Exception as e:
            logger.debug(f"Failed to parse trade: {e} - raw: {raw}")
            return None

    def _trade_exists(self, trade: CongressionalTrade) -> bool:
        """
        Check if a trade already exists in the database.

        Uses the unique constraint fields: ticker, politician, trade_date,
        trade_type, amount_range.

        Args:
            trade: CongressionalTrade to check

        Returns:
            True if trade exists, False otherwise
        """
        stmt = select(CongressionalTrade.id).where(
            CongressionalTrade.ticker == trade.ticker,
            CongressionalTrade.politician == trade.politician,
            CongressionalTrade.trade_date == trade.trade_date,
            CongressionalTrade.trade_type == trade.trade_type,
            CongressionalTrade.amount_range == trade.amount_range,
        )
        return self.session.scalar(stmt) is not None

    def _trade_key(self, trade: CongressionalTrade) -> tuple:
        """Dedup key matching the table's unique constraint."""
        return (
            trade.ticker, trade.politician, trade.trade_date,
            trade.trade_type, trade.amount_range,
        )

    def _existing_trade_keys(self) -> set[tuple]:
        """One-shot snapshot of existing trade keys for O(1) in-memory dedup.

        Broad ingestion processes the full House+Senate history; a per-row
        ``_trade_exists`` SELECT would be tens of thousands of queries, so we load
        all existing keys once and check membership in memory instead.
        """
        rows = self.session.execute(
            select(
                CongressionalTrade.ticker, CongressionalTrade.politician,
                CongressionalTrade.trade_date, CongressionalTrade.trade_type,
                CongressionalTrade.amount_range,
            )
        ).all()
        return {tuple(r) for r in rows}

    async def collect_all(
        self, *, since: date | None = None, days_back: int = 7
    ) -> CollectorResult:
        """Retain ALL congressional trades market-wide (broad multi-source collection).

        Unlike ``collect(tickers)``, this does NOT filter to a configured universe —
        it is the broad ingestion the insight engine needs (what is Congress quietly
        buying across the WHOLE market, not just names we already hold?). Source is
        the official Senate eFD system (see ``fetch_senate_efd_trades``); House PTRs
        are scanned PDFs and remain unsourced. Dedup uses a single in-memory snapshot
        of existing keys; rows are committed once at the end.

        Args:
            since: if set, only retain trades on/after this date (bounds run volume).
            days_back: how many recent days of PTR *submissions* to sweep. PTRs may
                be filed up to 45 days after the trade, so a periodic short sweep
                (deduped) converges on the full record.
        """
        started_at = datetime.now()
        records = 0
        errors: list[str] = []
        seen = self._existing_trade_keys()

        try:
            raw_trades = await self.fetch_senate_efd_trades(days_back=days_back)
            added = 0
            for raw in raw_trades:
                trade = self.parse_trade(raw, "Senate")
                if trade is None:
                    continue
                if since is not None and trade.trade_date < since:
                    continue
                key = self._trade_key(trade)
                if key in seen:
                    continue
                seen.add(key)
                self.session.add(trade)  # no per-row flush; commit once below
                added += 1
            records += added
            logger.info(f"{self.name}: retained {added} Senate trades (broad, market-wide)")
        except Exception as e:  # noqa: BLE001 - congress must not abort broad collection
            error_msg = f"Senate eFD broad fetch failed: {str(e)}"
            errors.append(error_msg)
            logger.error(f"{self.name}: {error_msg}")

        try:
            self.session.commit()
        except Exception as e:  # noqa: BLE001
            self.session.rollback()
            error_msg = f"Failed to commit broad trades: {str(e)}"
            errors.append(error_msg)
            logger.error(f"{self.name}: {error_msg}")

        return CollectorResult(
            collector_name=self.name,
            success=len(errors) == 0,
            records_collected=records,
            errors=errors,
            started_at=started_at,
            finished_at=datetime.now(),
        )

    async def collect(self, tickers: list[str]) -> CollectorResult:
        """Collect recent Senate trades for the given tickers only.

        Same source and dedup as ``collect_all``, filtered to ``tickers``. Use
        ``collect_all`` for the market-wide ingestion the insight engine needs.
        """
        started_at = datetime.now()
        errors: list[str] = []
        records = 0
        ticker_set = {t.upper() for t in tickers}
        seen = self._existing_trade_keys()
        try:
            raw_trades = await self.fetch_senate_efd_trades(days_back=7)
            for raw in raw_trades:
                trade = self.parse_trade(raw, "Senate")
                if trade is None or trade.ticker not in ticker_set:
                    continue
                key = self._trade_key(trade)
                if key in seen:
                    continue
                seen.add(key)
                self.session.add(trade)
                records += 1
            self.session.commit()
        except Exception as e:  # noqa: BLE001
            self.session.rollback()
            errors.append(f"Senate eFD fetch failed: {e}")
            logger.error(f"{self.name}: {errors[-1]}")
        return CollectorResult(
            collector_name=self.name,
            success=not errors,
            records_collected=records,
            errors=errors,
            started_at=started_at,
            finished_at=datetime.now(),
        )

    async def collect_single(self, ticker: str) -> int:
        """Collect trades for one ticker (same fetch as ``collect``)."""
        result = await self.collect([ticker])
        return result.records_collected
