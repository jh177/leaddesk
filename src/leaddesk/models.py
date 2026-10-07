"""Domain models for leaddesk.

Pydantic models rather than dataclasses: most of these are either parsed from
JSON, produced by an LLM, or crossing an HTTP boundary, so type hints need
runtime enforcement rather than good intentions.

Money convention: all prices are whole US dollars as `int`. Never float —
binary floating point can't represent 0.1 exactly, and rounding drift in
quotes costs real money.
"""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Reusable field types
# ---------------------------------------------------------------------------


def _clean_zip(v: str | None) -> str | None:
    """Strip whitespace and ZIP+4 suffix before pattern validation."""
    if v is None:
        return None
    return str(v).strip().split("-")[0]


ZipCode = Annotated[str, BeforeValidator(_clean_zip), Field(pattern=r"^\d{5}$")]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
UsdPrice = Annotated[int, Field(gt=0)]


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

    Load-bearing for competitor comparison: a delivered quote and a pickup
    price differ by the entire delivery cost, which is exactly where our
    margin advantage lives. Never compare across these without adjusting.
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
    COMPETITOR_A = "competitor_a"
    COMPETITOR_B = "competitor_b"
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

    Stays a dataclass: it's an internal constant constructed in code, never
    parsed from JSON or produced by a model, so there's nothing to validate.

    Radius is per-depot because contractor coverage differs by market.
    """

    name: str
    latitude: float
    longitude: float
    radius_miles: int


class ServiceabilityResult(BaseModel):
    """Whether we can serve a destination, and from where.

    `depot` and `distance_miles` are populated even when not servable, so the
    caller can see how far outside the radius a lead fell — a 20-mile miss is
    a different business decision than a 900-mile one.
    """

    model_config = ConfigDict(frozen=True)

    servable: bool
    depot: str | None = None
    distance_miles: float | None = Field(default=None, ge=0)
    reason: str | None = None  # "unknown_zipcode" | "outside_service_radius"


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------


class Lead(BaseModel):
    """A raw inbound inquiry, exactly as received.

    Never discard `raw_text` — it's the input for every eval we'll run in
    Week 5, and re-extracting with a better model later requires the original.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    raw_text: str = Field(min_length=1)
    source: LeadSource
    received_at: datetime
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None


class ExtractedLead(BaseModel):
    """Structured fields pulled from lead text by an LLM.

    Every extracted field is Optional by design. A model that invents a
    zipcode is worse than one that reports None — downstream code can ask a
    human, but it can't detect a confident fabrication.

    `extraction_model` and `extracted_at` are recorded because we'll swap
    models and need to know which produced a given extraction when results
    shift.

    Field descriptions here are load-bearing: they flow into
    model_json_schema(), which gets pasted into the extraction prompt.
    """

    model_config = ConfigDict(frozen=True)

    lead_id: str
    zipcode: ZipCode | None = Field(
        default=None, description="5-digit destination ZIP for delivery"
    )
    size: Size | None = Field(default=None, description="Requested container size")
    condition: Condition | None = Field(
        default=None, description="Requested condition grade"
    )
    quantity: int | None = Field(
        default=None, gt=0, le=100, description="Number of containers requested"
    )
    urgency: Urgency = Field(
        default=Urgency.UNKNOWN, description="How soon they need it"
    )
    fulfillment_preference: Fulfillment | None = Field(
        default=None, description="Whether they want delivery or will pick up"
    )
    budget_mentioned_usd: int | None = Field(
        default=None, gt=0, description="Budget figure if the lead states one"
    )
    intent: str | None = Field(
        default=None, description="One-line summary of what they want"
    )
    notes: str | None = Field(
        default=None, description="Anything else useful for the call"
    )
    confidence: Confidence = Field(
        default=0.0, description="Extraction certainty, 0.0 to 1.0"
    )
    extraction_model: str | None = None
    extracted_at: datetime = Field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# Inventory and pricing inputs
# ---------------------------------------------------------------------------


class InventoryMatch(BaseModel):
    """A unit at one of our depots matching the requested spec."""

    model_config = ConfigDict(frozen=True)

    depot: str
    size: Size
    condition: Condition
    quantity_available: int = Field(ge=0)  # zero is legitimate: out of stock
    unit_price_usd: UsdPrice


class CompetitorQuote(BaseModel):
    """A price observed at a competitor at a point in time.

    This is an observation, not a fact about the world — container prices move,
    so `observed_at` is mandatory and every consumer must account for staleness.

    Mirrors the tracking sheet columns so the Week 2 import is a CSV load
    rather than a remapping exercise.
    """

    model_config = ConfigDict(frozen=True)

    source: CompetitorSource
    observed_at: date
    dest_zip: ZipCode
    size: Size
    condition: Condition
    price_usd: UsdPrice
    fulfillment: Fulfillment
    condition_raw: str | None = None  # their label, verbatim
    pickup_depot_zip: ZipCode | None = None
    fees_included: str | None = None  # "tax+delivery" | "unclear" | ...
    lead_time_days: int | None = Field(default=None, ge=0)
    notes: str | None = None

    @model_validator(mode="after")
    def check_pickup_depot(self) -> "CompetitorQuote":
        """Pickup quotes need an origin depot; delivered quotes must not have one.

        A cross-field invariant no per-field constraint can express. Without
        it, a mislabeled row silently corrupts every price comparison.
        """
        if self.fulfillment is Fulfillment.PICKUP and self.pickup_depot_zip is None:
            raise ValueError("pickup quotes require pickup_depot_zip")
        if self.fulfillment is Fulfillment.DELIVERED and self.pickup_depot_zip:
            raise ValueError("delivered quotes must not set pickup_depot_zip")
        return self


# ---------------------------------------------------------------------------
# Customer history
# ---------------------------------------------------------------------------


class PriorQuote(BaseModel):
    """A quote we previously gave this customer."""

    model_config = ConfigDict(frozen=True)

    quoted_at: date
    size: Size
    condition: Condition
    quoted_usd: UsdPrice
    outcome: Outcome
    closed_usd: UsdPrice | None = None  # what it actually sold for, if won

    @model_validator(mode="after")
    def check_closed_price(self) -> "PriorQuote":
        if self.outcome is Outcome.WON and self.closed_usd is None:
            raise ValueError("won quotes require closed_usd")
        return self


class CustomerHistory(BaseModel):
    """What we know about a returning customer.

    The negotiation fields are the point: knowing this buyer historically
    closes 8% under ask is worth more on a call than any competitor price.
    """

    model_config = ConfigDict(frozen=True)

    customer_id: str
    prior_quotes: list[PriorQuote] = Field(default_factory=list)
    total_purchases: int = Field(default=0, ge=0)
    lifetime_value_usd: int = Field(default=0, ge=0)
    avg_discount_from_ask_pct: float | None = Field(default=None, ge=0, le=100)
    last_contact: date | None = None
    notes: str | None = None

    @property
    def is_returning(self) -> bool:
        return self.total_purchases > 0

    @property
    def win_rate(self) -> float | None:
        """Share of decided quotes that closed.

        Returns None when nothing has been decided — "never quoted them" and
        "they rejected everything" are very different facts, and collapsing
        both to 0.0 loses that.
        """
        decided = [
            q for q in self.prior_quotes if q.outcome in (Outcome.WON, Outcome.LOST)
        ]
        if not decided:
            return None
        return sum(q.outcome is Outcome.WON for q in decided) / len(decided)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


class MarketContext(BaseModel):
    """Synthesized competitor pricing for a given spec and destination.

    `confidence` should drop as observations age or thin out. `sources` carries
    citations so a number on a call brief can always be traced back.
    """

    model_config = ConfigDict(frozen=True)

    low_usd: int | None = Field(default=None, gt=0)
    high_usd: int | None = Field(default=None, gt=0)
    median_usd: int | None = Field(default=None, gt=0)
    observation_count: int = Field(default=0, ge=0)
    oldest_observation: date | None = None
    confidence: Confidence = 0.0
    sources: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_range(self) -> "MarketContext":
        if (
            self.low_usd is not None
            and self.high_usd is not None
            and self.low_usd > self.high_usd
        ):
            raise ValueError("low_usd cannot exceed high_usd")
        return self


class PriceRecommendation(BaseModel):
    """What to quote, and the least we'd accept."""

    model_config = ConfigDict(frozen=True)

    recommended_usd: UsdPrice
    floor_usd: UsdPrice
    our_cost_usd: UsdPrice
    market: MarketContext | None = None
    rationale: str | None = None

    @property
    def margin_at_recommended_usd(self) -> int:
        return self.recommended_usd - self.our_cost_usd

    @property
    def margin_at_floor_usd(self) -> int:
        return self.floor_usd - self.our_cost_usd

    @model_validator(mode="after")
    def check_floor(self) -> "PriceRecommendation":
        if self.floor_usd > self.recommended_usd:
            raise ValueError("floor_usd cannot exceed recommended_usd")
        return self


class CallBrief(BaseModel):
    """The deliverable: everything needed to pick up the phone and close.

    `warnings` surfaces uncertainty rather than hiding it — stale competitor
    data, low extraction confidence, thin history. A confidently wrong number
    on a sales call is worse than a flagged uncertain one.
    """

    model_config = ConfigDict(frozen=True)

    lead: Lead
    extracted: ExtractedLead
    serviceability: ServiceabilityResult
    generated_at: datetime = Field(default_factory=datetime.now)
    recommendation: PriceRecommendation | None = None
    inventory: list[InventoryMatch] = Field(default_factory=list)
    customer_history: CustomerHistory | None = None
    talking_points: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def is_actionable(self) -> bool:
        """Whether there's enough here to justify a call."""
        return self.serviceability.servable and self.recommendation is not None
