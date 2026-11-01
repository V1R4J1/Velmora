"""One catalogue-backed campaign pricing authority, shared by every shopping flow.

The bundled campaign is preview-only. Checkout quotes ALWAYS use catalogue prices
until a genuine commerce promotion adapter exists; no config flag can bypass that.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import math
import hashlib
import json

from flask import has_request_context, session


@dataclass(frozen=True)
class Price:
    original_price_gbp: float
    price_gbp: float
    promotional_price_gbp: float | None = None
    discount_percentage: float = 0
    promotion_active: bool = False
    campaign_id: str | None = None
    promotion_label: str | None = None
    preview_only: bool = False

    def payload(self):
        return asdict(self)


class PromotionalPricingService:
    def __init__(self, config, campaign):
        self.config = config  # Read current state, never cache the enabled flag.
        self.campaign = campaign

    @property
    def enabled(self):
        # Signed visitor state previews the shared campaign without changing
        # another customer's demo or the server's default campaign setting.
        if has_request_context() and type(session.get("black_friday_demo")) is bool:
            return session["black_friday_demo"]
        return self.config.get("BLACK_FRIDAY_ENABLED", False) is True

    @property
    def active(self):
        if not self.enabled:
            return False
        now = datetime.now(timezone.utc)
        for key, expired in (("starts_at", False), ("ends_at", True)):
            value = self.campaign.get(key)
            if value:
                try:
                    date = datetime.fromisoformat(value)
                except (ValueError, TypeError):
                    return False
                if date.tzinfo is None:
                    return False
                if (expired and now >= date) or (not expired and now < date):
                    return False
        return True

    @property
    def promotionRankingWeight(self):
        try:
            weight = float(self.config.get("PROMOTION_RANKING_WEIGHT", 0.35))
            return min(0.5, max(0, weight)) if math.isfinite(weight) and self.active else 0
        except (ValueError, TypeError):
            return 0

    @property
    def revision(self):
        state = {"active": self.active, "weight": self.promotionRankingWeight,
                 "campaign": self.campaign if self.active else None}
        return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()[:16]

    def quote(self, product, variant=None, *, purpose="preview"):
        original = Decimal(str(product.price_gbp))
        ordinary = Price(float(original), float(original))
        if purpose != "preview" or not self.active or variant is None or variant.product.id != product.id or not variant.available:
            return ordinary
        # Rules belong to the shared campaign, never to the AI catalogue.
        value = self.campaign.get("discounts", {}).get(variant.id,
                    self.campaign.get("discounts", {}).get(product.id, 0))
        try:
            percent = Decimal(str(value))
            if not percent.is_finite() or not 0 < percent < 100:
                return ordinary
        except Exception:
            return ordinary
        current = (original * (1 - percent / 100)).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
        if current >= original:
            return ordinary
        return Price(float(original), float(current), float(current), float(percent), True,
                     self.campaign["id"], "Black Friday demo · preview only", True)

    def policy(self, preference="any"):
        return {"promotionRankingWeight": self.promotionRankingWeight if preference not in ("exclude", "ignore") else 0,
                "promotion_preference": preference,
                "pricing_mode": "demo_preview" if self.active else "ordinary",
                "pricing_notice": pricing_notice(self.active)}


def price_for(product, variant=None, pricing=None, *, purpose="preview"):
    return pricing.quote(product, variant, purpose=purpose) if pricing else Price(float(product.price_gbp), float(product.price_gbp))


def pricing_notice(active=False):
    return ("Black Friday demo prices are previews only. Your bag uses ordinary catalogue prices; online checkout is unavailable."
            if active else "Prices recalculated from the current catalogue. Earlier previews may have changed; review the total before adding to your bag.")


def total_money(values):
    return float(sum((Decimal(str(value)) for value in values), Decimal(0)).quantize(Decimal(".01")))
