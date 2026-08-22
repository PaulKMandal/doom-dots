from __future__ import annotations

from dataclasses import dataclass
import re


ATOM_MAP = re.compile(r":\d+\]")


@dataclass(frozen=True)
class ReactionRecord:
    reaction_id: str
    source_id: str
    split_id: str
    reactants: tuple[str, ...]
    reagents: tuple[str, ...]
    products: tuple[str, ...]
    patent_number: str | None = None
    publication_year: int | None = None
    patent_family: str | None = None
    normalized_reaction_signature: str | None = None
    normalized_product_key: str | None = None
    overall_mechanism_sequence_id: str | None = None
    license_id: str | None = None
    provenance_uri: str | None = None

    def validate(self) -> None:
        if not self.reaction_id or not self.source_id or not self.split_id:
            raise ValueError("reaction_id, source_id, and split_id are required")
        if not self.products:
            raise ValueError("at least one product is required")


@dataclass(frozen=True)
class Prediction:
    run_id: str
    reaction_id: str
    task: str
    rank: int
    raw_output: str
    canonical_output: str
    valid: bool
    model_calls: int

    def validate(self) -> None:
        if self.rank < 1 or self.model_calls < 1:
            raise ValueError("rank and model_calls must be positive")
        if self.task == "retro_single_step" and ATOM_MAP.search(self.canonical_output):
            raise ValueError("evaluated retrosynthesis output must be map-stripped with no atom maps")
