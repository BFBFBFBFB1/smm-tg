from decimal import Decimal

# Markup by service type: sale = panel_rate * multiplier
MARKUP_MULTIPLIERS: dict[str, Decimal] = {
    # x2 — cheap high-volume
    "views": Decimal("2.0"),
    "video_views": Decimal("2.0"),
    "story_views": Decimal("2.0"),
    "impressions": Decimal("2.0"),
    # x2.5 — mid segment
    "likes": Decimal("2.5"),
    "reactions": Decimal("2.5"),
    "followers": Decimal("2.5"),
    "subscribers": Decimal("2.5"),
    "members": Decimal("2.5"),
    # x3 — complex / expensive
    "comments": Decimal("3.0"),
    "custom_comments": Decimal("3.0"),
    "shares": Decimal("3.0"),
    "reposts": Decimal("3.0"),
    "saves": Decimal("3.0"),
    "watch_time": Decimal("3.0"),
    "premium": Decimal("3.0"),
    "mentions": Decimal("3.0"),
}

DEFAULT_MULTIPLIER = Decimal("2.5")

# Keywords in service name → type (order matters: more specific first)
TYPE_KEYWORDS: list[tuple[str, str]] = [
    ("custom comment", "custom_comments"),
    ("video view", "video_views"),
    ("story view", "story_views"),
    ("watch time", "watch_time"),
    ("impression", "impressions"),
    ("subscriber", "subscribers"),
    ("follower", "followers"),
    ("member", "members"),
    ("reaction", "reactions"),
    ("comment", "comments"),
    ("repost", "reposts"),
    ("share", "shares"),
    ("save", "saves"),
    ("mention", "mentions"),
    ("premium", "premium"),
    ("like", "likes"),
    ("view", "views"),
]


def detect_service_type(name: str, panel_type: str | None = None) -> str:
    """Infer markup type from panel type field or service name."""
    candidates = [panel_type or "", name or ""]
    for text in candidates:
        lowered = text.lower().replace("-", " ").replace("_", " ")
        for keyword, service_type in TYPE_KEYWORDS:
            if keyword in lowered:
                return service_type
    return "other"


def calculate_resale_price(panel_rate: Decimal, service_type: str) -> Decimal:
    """
    panel_rate — price per 1000 units from smmpanelus.com
    returns — user-facing price per 1000 units
    """
    multiplier = MARKUP_MULTIPLIERS.get(service_type, DEFAULT_MULTIPLIER)
    return (panel_rate * multiplier).quantize(Decimal("0.01"))


def calculate_order_price(resale_rate_per_1000: Decimal, quantity: int) -> Decimal:
    """Total sale price for a given quantity."""
    total = (resale_rate_per_1000 * Decimal(quantity)) / Decimal(1000)
    return total.quantize(Decimal("0.01"))


def calculate_purchase_price(panel_rate_per_1000: Decimal, quantity: int) -> Decimal:
    """What we pay the panel for this order."""
    total = (panel_rate_per_1000 * Decimal(quantity)) / Decimal(1000)
    return total.quantize(Decimal("0.0001"))
