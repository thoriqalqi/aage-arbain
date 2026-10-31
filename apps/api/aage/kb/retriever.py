"""Retriever RAG hibrida: kemiripan embedding (pgvector di Postgres) + kecocokan kata kunci produk."""

import difflib
import re
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


_UNITS = {"mg", "g", "gr", "ml", "iu", "mcg", "cfu", "kg"}
_GENERIC = {"kapsul", "madu", "minyak", "teh", "serbuk", "sirup", "susu", "tablet", "herbal", "anak", "sachet", "botol",
            "instan", "tetes", "kantong", "murni", "plus", "lunak", "isi", "dan",
            "vitamin"}  # "vitamin E" tidak boleh cocok ke "Vitamin D3" hanya karena kata "vitamin"
# Kata sehari-hari di nama produk: tidak cukup sendirian untuk menebak produk ("tempat makan" ≠ "Madu Nafsu Makan",
# "salam kenal" ≠ "Kapsul Daun Salam"). Bila nama disebut lengkap ("daun salam", "nafsu makan") tetap cocok.
_LEMAH = {"makan", "salam", "putih", "merah", "emas", "asam", "kucing", "tunggal", "besi", "ikan", "beras", "lidah",
          "daun", "biji", "extra", "kompleks", "rileks", "stamina", "hutan", "dewasa", "buaya"}


def _name_tokens(text: str) -> list[str]:
    # Huruf tunggal dipertahankan (vitamin "c", "d3"), satuan & angka murni dibuang.
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _UNITS and not t.isdigit()]


def _fix_typos(text: str, products: list[Product]) -> str:
    """Koreksi salah ketik nama khas produk ("habatusauda" → "habbatussauda"); hanya token ≥6 huruf, kemiripan ≥0.8.
    Kata 5 huruf terlalu mudah tertukar dengan kata sehari-hari ("bantu" → "batuk")."""
    vocab = sorted({t for p in products for t in _name_tokens(p.nama) if t not in _GENERIC and len(t) >= 5})
    out = []
    for tok in re.findall(r"[a-z0-9]+", text.lower()):
        if len(tok) >= 6 and tok not in vocab and (m := difflib.get_close_matches(tok, vocab, n=1, cutoff=0.8)):
            tok = m[0]
        out.append(tok)
    return " ".join(out)


def find_products(db: Session, text: str, limit: int = 3, _typo_fixed: bool = False) -> list[Product]:
    """Cari produk yang disebut eksplisit (nama/SKU). Skor = cakupan token khas nama; seri dipecah dengan
    token umum ("kapsul", "teh", "instan") agar "Kapsul Jahe Merah" ≠ "Jahe Merah Instan"."""
    low = text.lower()
    products = list(db.scalars(select(Product).where(Product.aktif.is_(True))))
    if _typo_fixed is False and not _match(low, products):
        fixed = _fix_typos(text, products)
        if fixed != " ".join(re.findall(r"[a-z0-9]+", low)):
            return find_products(db, fixed, limit, _typo_fixed=True)
    return _match(low, products)[:limit]


def _match(low: str, products: list[Product]) -> list[Product]:
    q_all = {stem(t) for t in _name_tokens(low)}
    # Huruf tunggal hanya bermakna bila menempel pada "vitamin" ("vitamin c"); "yang B" bukan Vitamin B Kompleks.
    huruf_vitamin = set(re.findall(r"\bvitamin\s+([a-z])\b", low))
    lemah = {stem(t) for t in _LEMAH}
    scored = []
    for p in products:
        if p.sku.lower() in low:
            scored.append((10.0, 0.0, p))
            continue
        all_terms = {stem(t) for t in _name_tokens(p.nama)}
        name_terms = {t for t in all_terms if t not in _GENERIC}
        if not name_terms:
            continue
        shared = q_all & name_terms
        overlap = len(shared) / len(name_terms)
        kuat = {t for t in shared - lemah if len(t) > 1 or t in huruf_vitamin}
        if overlap >= 0.5 and (overlap == 1 or kuat):
            tie = len(q_all & all_terms) / len(all_terms)
            scored.append((overlap, tie, p))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [p for _, _, p in scored]


def document_by_id(db: Session, doc_id: int) -> Document | None:
    return db.get(Document, doc_id)
