"""Database types that preserve financial Decimal values across dialects."""

from decimal import Decimal, localcontext

from sqlalchemy import Numeric, String
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class ExactFinancialDecimal(TypeDecorator[Decimal]):
    """Use exact NUMERIC in production SQL databases and text in SQLite.

    SQLite's NUMERIC affinity may store high-magnitude decimals as binary
    floating-point values. VARCHAR has TEXT affinity, so the local/test path
    stores the canonical decimal string and reconstructs a Decimal exactly.
    """

    impl = Numeric(precision=38, scale=12, asdecimal=True)
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(String(80))
        return dialect.type_descriptor(Numeric(precision=38, scale=12, asdecimal=True))

    def process_bind_param(self, value: Decimal | None, dialect: Dialect) -> str | Decimal | None:
        if value is None:
            return None
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
        with localcontext() as context:
            context.prec = 50
            rounded = decimal_value.quantize(Decimal("0.000000000001"))
        if decimal_value != rounded:
            raise ValueError("financial Decimal exceeds the supported scale of 12")
        integer_digits = max(1, decimal_value.adjusted() + 1) if decimal_value else 1
        if integer_digits > 26:
            raise ValueError("financial Decimal exceeds NUMERIC(38,12) precision")
        if dialect.name == "sqlite":
            return format(decimal_value, "f")
        return decimal_value

    def process_result_value(self, value: object | None, dialect: Dialect) -> Decimal | None:
        if value is None:
            return None
        return value if isinstance(value, Decimal) else Decimal(str(value))
