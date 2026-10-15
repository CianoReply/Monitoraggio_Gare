"""Schemi Pydantic del modulo domain.

`TenderCreate` è il contratto tra `ingestion` (che lo produce, T1.3) e `domain`
(che lo salva, ADR-006): stessi campi di `tenders`, esclusi quelli calcolati
(`id`, `relevance_score`, `is_relevant`, `discard_reason`, `created_at`, `updated_at`).
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

_CPV_RE = re.compile(r"^\d{8}$")


class TenderCreate(BaseModel):
    """Gara normalizzata, pronta per essere salvata con `repository.upsert_tender`."""

    model_config = ConfigDict(str_strip_whitespace=True)

    publication_number: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1)
    description: str | None = None
    buyer_name: str = Field(min_length=1, max_length=500)
    buyer_city: str | None = Field(default=None, max_length=200)
    cpv_codes: list[str] = Field(default_factory=list)
    notice_type: str = Field(min_length=1, max_length=100)
    estimated_value: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    publication_date: date
    submission_deadline: datetime | None = None
    ted_url: str = Field(min_length=1, max_length=1000)
    documents_url: str | None = Field(default=None, max_length=1000)
    parent_publication_number: str | None = Field(default=None, max_length=50)
    raw_data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("cpv_codes")
    @classmethod
    def _normalize_cpv(cls, value: list[str]) -> list[str]:
        """Ogni CPV deve avere 8 cifre; elimina i duplicati mantenendo l'ordine."""
        seen: dict[str, None] = {}
        for code in value:
            code = code.strip()
            if not _CPV_RE.match(code):
                raise ValueError(f"CPV non valido (servono 8 cifre): {code!r}")
            seen.setdefault(code, None)
        return list(seen)

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else value
