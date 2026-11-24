"""NetKâr kâr motoru (docs/12_kar_motoru.md). Saf, deterministik, I/O yok.

Giriş noktası: `calculate_profit(ProfitInput) -> ProfitResult`.
"""

from app.profit.engine import calculate_profit
from app.profit.inputs import ProfitInput, ProfitInputError
from app.profit.results import ProfitResult
from app.profit.settings import ProfitSettings

__all__ = ["ProfitInput", "ProfitInputError", "ProfitResult", "ProfitSettings", "calculate_profit"]
