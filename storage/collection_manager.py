class CollectionManager:
    """
    Unified collection name management.

    All collection names flow through this class,
    so future changes (prefixes, naming conventions)
    never touch the rest of the system.
    """

    DEFAULT_COLLECTION = "financial_reports"

    @staticmethod
    def company_collection(company: str) -> str:
        return company.lower().replace(" ", "_")
