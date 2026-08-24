from decimal import Decimal, ROUND_UP

# Approximate conversion: 1 Telegram Star ≈ $0.013 (adjust as needed)
STAR_USD_RATE = Decimal("0.013")


def stars_amount_from_usd(usd_amount: Decimal) -> int:
    if usd_amount <= 0:
        return 1
    stars = (usd_amount / STAR_USD_RATE).quantize(Decimal("1"), rounding=ROUND_UP)
    return max(int(stars), 1)


def usd_from_stars(stars: int) -> Decimal:
    return (Decimal(stars) * STAR_USD_RATE).quantize(Decimal("0.01"))
