"""Partner role normalization — ORM enum vs API enum."""

from __future__ import annotations

from types import SimpleNamespace

from db.column_types import PartnerRoleEnum
from modules.employee.access_control import is_organization_manager_partner, org_manager_contact_id
from modules.partners.models import PartnerRole
from modules.partners.role_utils import partner_role_value


def test_partner_role_value_from_orm_enum():
    assert partner_role_value(PartnerRoleEnum.organization_manager) == "organization_manager"
    # str(PartnerRoleEnum) is not the canonical value — that was the production bug.
    assert str(PartnerRoleEnum.organization_manager) != "organization_manager"


def test_partner_role_value_from_api_enum_and_string():
    assert partner_role_value(PartnerRole.organization_manager) == "organization_manager"
    assert partner_role_value("phlebo") == "phlebo"
    assert partner_role_value(None) == ""


def test_is_organization_manager_partner_accepts_orm_role_enum():
    partner = SimpleNamespace(
        partner_id=113,
        role=PartnerRoleEnum.organization_manager,
        status="active",
    )
    assert is_organization_manager_partner(partner) is True
    assert org_manager_contact_id(partner=partner) == 113


def test_is_organization_manager_partner_rejects_wrong_role():
    partner = SimpleNamespace(
        partner_id=64,
        role=PartnerRoleEnum.phlebo,
        status="active",
    )
    assert is_organization_manager_partner(partner) is False
    assert org_manager_contact_id(partner=partner) is None
