"""Retriever RAG hibrida: kemiripan embedding (pgvector di Postgres) + kecocokan kata kunci produk."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .. import llm
from ..db import IS_POSTGRES
from ..models import Chunk, Document, Product
from ..textutil import content_tokens, cosine, expand, stem


@dataclass
class Hit:
    chunk: Chunk
    score: float

    def source(self) -> dict:
        d = self.chunk.document
        return {
            "chunk_id": self.chunk.id,
            "document_id": d.id,
            "judul": d.judul,
            "versi": self.chunk.versi,
            "halaman": self.chunk.halaman,
            "product_id": self.chunk.product_id,
            "skor": round(self.score, 3),
            "kutipan": self.chunk.teks[:220],
        }


def _keyword_score(query_terms: set[str], text: str) -> float:
    terms = {stem(t) for t in content_tokens(text)}
    if not query_terms or not terms:
        return 0.0
    return len(query_terms & terms) / len(query_terms)


def retrieve(db: Session, query: str, *, k: int = 4, product_ids: list[int] | None = None,
             min_score: float = 0.18) -> list[Hit]:
    qvec = llm.embed(query)
    stmt = select(Chunk).options(joinedload(Chunk.document)).where(Chunk.aktif.is_(True))
    if product_ids:
        stmt = stmt.where(Chunk.product_id.in_(product_ids))
    if IS_POSTGRES:
        from pgvector.sqlalchemy import Vector
        from sqlalchemy import bindparam

        q = bindparam("qvec", qvec, type_=Vector(len(qvec)))
        stmt = stmt.order_by(Chunk.embedding.op("<=>")(q)).limit(40)
    candidates = list(db.scalars(stmt).unique())

    q_terms = {stem(t) for t in expand(content_tokens(query))}
    hits = []
    for ch in candidates:
        score = 0.6 * cosine(qvec, ch.embedding) + 0.4 * _keyword_score(q_terms, ch.teks)
        hits.append(Hit(ch, score))
    hits.sort(key=lambda h: h.score, reverse=True)
    return [h for h in hits[:k] if h.score >= min_score]


def find_products(db: Session, text: str, limit: int = 3) -> list[Product]:
    """Cari produk yang disebut eksplisit (nama/SKU/kata kunci unik)."""
    low = text.lower()
    products = list(db.scalars(select(Product).where(Product.aktif.is_(True))))
    scored = []
    q_terms = {stem(t) for t in content_tokens(text)}
    generic = {"kapsul", "madu", "minyak", "teh", "serbuk", "sirup", "susu", "tablet", "herbal", "anak",
               "sachet", "botol", "ml", "instan", "tetes", "kantong", "murni", "plus"}
    for p in products:
        if p.sku.lower() in low:
            scored.append((10.0, p))
            continue
        name_terms = {stem(t) for t in content_tokens(p.nama) if t not in generic and not t.isdigit()}
        if not name_terms:
            continue
        overlap = len(q_terms & name_terms) / len(name_terms)
        if overlap >= 0.5:
            scored.append((overlap, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored[:limit]]


def document_by_id(db: Session, doc_id: int) -> Document | None:
    return db.get(Document, doc_id)
