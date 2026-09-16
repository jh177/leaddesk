"""Domain models for leaddesk.

Plain dataclasses for now. On Day 2 these become Pydantic BaseModels with
runtime validation — anything crossing an API boundary or produced by an LLM
needs enforcement, not just type hints.

Money convention: all prices are whole US dollars as `int`. Never float —
binary floating point can't represent 0.1 exactly, and rounding drift in
quotes costs real money.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Size(StrEnum):
    """Container sizes. Values match the labels used in the Solidbox DB."""

    ST20 = "20st"
    HC20 = "20hc"
    ST40 = "40st"
    HC40 = "40hc"
    HCDD40 = "40hcdd"


class Condition(StrEnum):
    """Normalized condition grades.

    Vendors use inconsistent labels ("one-trip", "premium", "wind and water
    tight"). CompetitorQuote keeps the raw label alongside this normalized one
    so we don't destroy information at ingest.
    """

    NEW = "new"  # one-trip
    CARGO_WORTHY = "cargo_worthy"
    WWT = "wwt"  # wind and water tight
    AS_IS = "as_is"


class Fulfillment(StrEnum):
    """Whether a price includes delivery.

    Load-bearing for competitor comparison: a usacontainer.co delivered quote
    and a Boxhub pickup price differ by the entire delivery cost, which is
    exactly where our margin advantage lives.
    """

    DELIVERED = "delivered"
    PICKUP = "pickup"


class Urgency(StrEnum):
    IMMEDIATE = "immediate"  # needs it this week
    SOON = "soon"  # this month
    EXPLORING = "exploring"  # gathering prices
    UNKNOWN = "unknown"


class LeadSource(StrEnum):
    WEB_FORM = "web_form"
    PHONE = "phone"
    EMAIL = "email"
    REFERRAL = "referral"
    OTHER = "other"


class CompetitorSource(StrEnum):
    USACONTAINER = "usacontainer"
    BOXHUB = "boxhub"
    OTHER = "other"


class Outcome(StrEnum):
    WON = "won"
    LOST = "lost"
    NO_QUOTE = "no_quote"
    PENDING = "pending"


# ---------------------------------------------------------------------------
# Serviceability
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Depot:
    """A depot we can fulfill from.

    Radius is per-depot because contractor coverage differs by market —
    Houston's denser surroundings support a wider viable radius than El Paso's.
    """

    name: str
    latitude: float
    longitude: float
    radius_miles: int


@dataclass(frozen=True)
class ServiceabilityResult:
    """Whether we can serve a destination, and from where.

    `depot` and `distance_miles` are populated even when not servable, so the
    caller can see how far outside the radius a lead fell — a 20-mile miss is
    a different business decision than a 900-mile one.
    """

    servable: bool
    depot: str | None = None
    distance_miles: float | None = None
    reason: str | None = None  # "unknown_zipcode" | "outside_service_radius"


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Lead:
    """A raw inbound inquiry, exactly as received.

    Never discard `raw_text` — it's the input for every eval we'll run in
    Week 5, and re-extracting with a better model later requires the original.
    """

    id: str
    raw_text: str
    source: LeadSource
    received_at: datetime
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None


@dataclass(frozen=True)
class ExtractedLead:
    """Structured fields pulled from lead text by an LLM.

    Every field is Optional by design. A model that invents a zipcode is worse
    than one that reports None — downstream code can ask a human, but it can't
    detect a confident fabrication.

    `model` and `extracted_at` are recorded because we'll swap models and need
    to know which produced a given extraction when results shift.
    """

    lead_id: str
    zipcode: str | None = None
    size: Size | None = None
    condition: Condition | None = None
    quantity: int | None = None
    urgency: Urgency = Urgency.UNKNOWN
    fulfillment_preference: Fulfillment | None = None
    budget_mentioned_usd: int | None = None
    intent: str | None = None  # free-text summary of what they want
    notes: str | None = None
    confidence: float = 0.0  # 0.0-1.0, model's self-reported certainty
    model: str | None = None
    extracted_at: datetime | None = None


# ---------------------------------------------------------------------------
# Inventory and pricing inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InventoryMatch:
    """A unit at one of our depots matching the requested spec."""

    depot: str
    size: Size
    condition: Condition
    quantity_available: int
    unit_price_usd: int


@dataclass(frozen=True)
class CompetitorQuote:
    """A price observed at a competitor at a point in time.

    This is an observation, not a fact about the world — container prices move,
    so `observed_at` is mandatory and every consumer must account for staleness.

    Mirrors the Google Sheet columns so the Week 2 import is a CSV load rather
    than a remapping exercise.
    """

    source: CompetitorSource
    observed_at: date
    dest_zip: str
    size: Size
    condition: Condition
    price_usd: int
    fulfillment: Fulfillment
    condition_raw: str | None = None  # their label, verbatim
    pickup_depot_zip: str | None = None  # pickup quotes only
    fees_included: str | None = None  # "tax+delivery" | "unclear" | ...
    lead_time_days: int | None = None
    notes: str | None = None


# ---------------------------------------------------------------------------
# Customer history
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PriorQuote:
    """A quote we previously gave this customer."""

    quoted_at: date
    size: Size
    condition: Condition
    quoted_usd: int
    outcome: Outcome
    closed_usd: int | None = None  # what it actually sold for, if won


@dataclass(frozen=True)
class CustomerHistory:
    """What we know about a returning customer.

    The negotiation fields are the point: knowing this buyer historically
    closes 8% under ask is worth more on a call than any competitor price.
    """

    customer_id: str
    prior_quotes: list[PriorQuote] = field(default_factory=list)
    total_purchases: int = 0
    lifetime_value_usd: int = 0
    avg_discount_from_ask_pct: float | None = None
    last_contact: date | None = None
    notes: str | None = None

    @property
    def is_returning(self) -> bool:
        return self.total_purchases > 0

    @property
    def win_rate(self) -> float | None:
        """Share of prior quotes that closed. None if none have been decided."""
        decided = [
            q for q in self.prior_quotes if q.outcome in (Outcome.WON, Outcome.LOST)
        ]
        if not decided:
            return None
        return sum(q.outcome == Outcome.WON for q in decided) / len(decided)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MarketContext:
    """Synthesized competitor pricing for a given spec and destination.

    `confidence` should drop as observations age or thin out. `sources` carries
    citations so a number on a call brief can always be traced back.
    """

    low_usd: int | None = None
    high_usd: int | None = None
    median_usd: int | None = None
    observation_count: int = 0
    oldest_observation: date | None = None
    confidence: float = 0.0
    sources: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PriceRecommendation:
    """What to quote, and the least we'd accept."""

    recommended_usd: int
    floor_usd: int
    our_cost_usd: int
    market: MarketContext | None = None
    rationale: str | None = None

    @property
    def margin_at_recommended_usd(self) -> int:
        return self.recommended_usd - self.our_cost_usd

    @property
    def margin_at_floor_usd(self) -> int:
        return self.floor_usd - self.our_cost_usd


@dataclass(frozen=True)
class CallBrief:
    """The deliverable: everything needed to pick up the phone and close.

    `warnings` surfaces uncertainty rather than hiding it — stale competitor
    data, low extraction confidence, thin history. A confidently wrong number
    on a sales call is worse than a flagged uncertain one.
    """

    lead: Lead
    extracted: ExtractedLead
    serviceability: ServiceabilityResult
    generated_at: datetime
    recommendation: PriceRecommendation | None = None
    inventory: list[InventoryMatch] = field(default_factory=list)
    customer_history: CustomerHistory | None = None
    talking_points: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_actionable(self) -> bool:
        """Whether there's enough here to justify a call."""
        return self.serviceability.servable and self.recommendation is not None
