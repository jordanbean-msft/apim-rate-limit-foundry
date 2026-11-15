from pydantic import Field

from apim_rate_limit_foundry.models.contract import Contract
from apim_rate_limit_foundry.models.types import Identifier, Money


class Price(Contract):
    """Versioned USD-per-million-token rates supplied as exact decimal strings.

    Input, cached input and output are priced independently. These rates are USD,
    while finalized costs and budgets are integer micro-USD. Admission captures a
    price snapshot so configuration edits cannot change an in-flight call's rate.
    """

    id: Identifier
    model: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    input_per_million: Money
    cached_input_per_million: Money
    output_per_million: Money
