"""MongoDB: system of record for raw HTML, parsed judgments and pipeline state.

Collections
-----------
judgments   one document per judgment; `status` drives the resumable pipeline
raw_html    gzip-compressed source HTML, so parser fixes can be re-applied offline
link_cache  resolved Indian Kanoon link targets (statute titles etc.)
"""

from __future__ import annotations

import gzip
from datetime import UTC, datetime
from typing import Any

from bson import Binary
from pymongo import ASCENDING, DESCENDING, AsyncMongoClient, UpdateOne

from insaaf.domain import CaseInsights, Judgment, ProcessingStatus, StatuteRef
from insaaf.scraper.parser import SearchHit


def _now() -> datetime:
    return datetime.now(UTC)


class MongoRepo:
    def __init__(self, uri: str, db: str) -> None:
        self._client: AsyncMongoClient = AsyncMongoClient(uri, tz_aware=True)
        self.db = self._client[db]
        self.judgments = self.db["judgments"]
        self.raw_html = self.db["raw_html"]
        self.link_cache = self.db["link_cache"]

    async def close(self) -> None:
        await self._client.close()

    async def ping(self) -> bool:
        await self.db.command("ping")
        return True

    async def ensure_indexes(self) -> None:
        await self.judgments.create_index([("status", ASCENDING), ("updated_at", ASCENDING)])
        await self.judgments.create_index([("court", ASCENDING), ("year", DESCENDING)])
        await self.judgments.create_index([("statutes.key", ASCENDING)])

    # ------------------------------------------------------------- discovery

    async def upsert_discovered(self, hits: list[SearchHit], source_query: str) -> int:
        if not hits:
            return 0
        ops = [
            UpdateOne(
                {"_id": h.doc_id},
                {
                    "$setOnInsert": {
                        "status": ProcessingStatus.DISCOVERED.value,
                        "discovered_at": _now(),
                        "attempts": 0,
                    },
                    "$set": {
                        "listing": {
                            "title": h.title,
                            "court": h.court,
                            "cites": h.cites,
                            "cited_by": h.cited_by,
                            "author": h.author,
                            "query": source_query,
                        },
                        "updated_at": _now(),
                    },
                },
                upsert=True,
            )
            for h in hits
        ]
        res = await self.judgments.bulk_write(ops, ordered=False)
        return res.upserted_count

    async def ids_with_status(
        self, status: ProcessingStatus | list[ProcessingStatus], limit: int, max_attempts: int = 3
    ) -> list[str]:
        statuses = [status] if isinstance(status, ProcessingStatus) else status
        cursor = self.judgments.find(
            {"status": {"$in": [s.value for s in statuses]}, "attempts": {"$lt": max_attempts}},
            {"_id": 1},
        ).sort("updated_at", ASCENDING).limit(limit)
        return [d["_id"] async for d in cursor]

    # ------------------------------------------------------------- raw html

    async def save_raw_html(self, doc_id: str, html: str) -> None:
        await self.raw_html.replace_one(
            {"_id": doc_id},
            {"_id": doc_id, "html": Binary(gzip.compress(html.encode("utf-8"))), "fetched_at": _now()},
            upsert=True,
        )
        await self.judgments.update_one(
            {"_id": doc_id},
            {"$set": {"status": ProcessingStatus.FETCHED.value, "updated_at": _now()}},
            upsert=True,
        )

    async def get_raw_html(self, doc_id: str) -> str | None:
        doc = await self.raw_html.find_one({"_id": doc_id})
        return gzip.decompress(doc["html"]).decode("utf-8") if doc else None

    # ------------------------------------------------------------- parsed

    async def save_parsed(
        self,
        j: Judgment,
        statutes: list[tuple[StatuteRef, int]],
        citations: list[dict[str, Any]],
    ) -> None:
        data = j.model_dump(mode="json", exclude={"doc_id"})
        data.update(
            year=j.year,
            statutes=[{**ref.model_dump(), "key": ref.key, "label": ref.label, "mentions": n} for ref, n in statutes],
            citations=citations,
            status=ProcessingStatus.PARSED.value,
            parsed_at=_now(),
            updated_at=_now(),
            attempts=0,
            error=None,
        )
        await self.judgments.update_one({"_id": j.doc_id}, {"$set": data}, upsert=True)

    async def save_insights(self, doc_id: str, insights: CaseInsights) -> None:
        await self.judgments.update_one(
            {"_id": doc_id},
            {
                "$set": {
                    "insights": insights.model_dump(mode="json"),
                    "status": ProcessingStatus.ENRICHED.value,
                    "enriched_at": _now(),
                    "updated_at": _now(),
                    "attempts": 0,
                    "error": None,
                }
            },
        )

    async def mark(self, doc_id: str, status: ProcessingStatus, **extra: Any) -> None:
        await self.judgments.update_one(
            {"_id": doc_id}, {"$set": {"status": status.value, "updated_at": _now(), **extra}}
        )

    async def mark_failed(self, doc_id: str, stage: str, error: str) -> None:
        """Record an error and bump attempts; the doc stays in its current stage
        so it is retried until max_attempts is reached."""
        await self.judgments.update_one(
            {"_id": doc_id},
            {
                "$set": {"error": {"stage": stage, "message": error[:2000], "at": _now()}, "updated_at": _now()},
                "$inc": {"attempts": 1},
            },
        )

    async def get(self, doc_id: str, projection: dict[str, int] | None = None) -> dict[str, Any] | None:
        return await self.judgments.find_one({"_id": doc_id}, projection)

    async def get_many(self, doc_ids: list[str], projection: dict[str, int] | None = None) -> dict[str, dict[str, Any]]:
        cursor = self.judgments.find({"_id": {"$in": doc_ids}}, projection)
        return {d["_id"]: d async for d in cursor}

    async def status_counts(self) -> dict[str, int]:
        pipeline = [{"$group": {"_id": "$status", "n": {"$sum": 1}}}]
        cursor = await self.judgments.aggregate(pipeline)
        return {d["_id"]: d["n"] async for d in cursor}

    # ------------------------------------------------------------- link cache

    async def cached_links(self, doc_ids: list[str]) -> dict[str, dict[str, Any]]:
        cursor = self.link_cache.find({"_id": {"$in": doc_ids}})
        return {d["_id"]: d async for d in cursor}

    async def cache_link(self, doc_id: str, title: str | None, source: str | None, kind: str, statute: StatuteRef | None) -> None:
        await self.link_cache.replace_one(
            {"_id": doc_id},
            {
                "_id": doc_id,
                "title": title,
                "source": source,
                "kind": kind,
                "statute": statute.model_dump() if statute else None,
                "resolved_at": _now(),
            },
            upsert=True,
        )
