"""Legal operator identity.

The operator is an individual developer today and may become a company later.
Every legal surface reads these values instead of hard-coding a name, so that
migration is a configuration change rather than a rewrite of the policy text.

No fictitious company name appears anywhere. Where a value is not yet decided,
the surfaces say so explicitly rather than inventing a placeholder that reads
like a real entity.
"""

from __future__ import annotations

from dataclasses import dataclass

UNRESOLVED = "not yet published"


@dataclass(frozen=True, slots=True)
class OperatorIdentity:
    """Who operates the service, for legal display purposes.

    ``brand_name`` is the product's public identity; ``legal_form`` is the
    seller's. They are deliberately separate fields because they are separate
    concepts, and conflating them is what makes a later company migration
    expensive.
    """

    brand_name: str
    legal_form: str
    contact_email: str
    support_url: str
    jurisdiction: str

    @property
    def is_individual(self) -> bool:
        return self.legal_form == "individual"

    @property
    def display_operator(self) -> str:
        if self.is_individual:
            return "an individual developer"
        return self.legal_form


def operator_from_settings(
    brand_name: str, legal_form: str, contact_email: str, support_url: str, jurisdiction: str
) -> OperatorIdentity:
    return OperatorIdentity(
        brand_name=brand_name or UNRESOLVED,
        legal_form=legal_form,
        contact_email=contact_email or UNRESOLVED,
        support_url=support_url or UNRESOLVED,
        jurisdiction=jurisdiction or UNRESOLVED,
    )
