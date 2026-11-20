"""Roles & Access (admin): access roles – which dashboard pages a role shows on a laptop / a phone and the page each opens
after sign-in (app.security.roles). Built-in roles are edited, not deleted; a role with users cannot be deleted."""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Role, User
from ..security.deps import CurrentUser, audit, require_admin
from ..security.roles import LABEL, PAGE_KEYS, PAGES, ensure_system_roles, parse_pages, users_per_role

router = APIRouter(prefix="/roles", tags=["roles"], dependencies=[Depends(require_admin)])
RoleId = Annotated[int, Path(ge=1)]


class PageAccess(BaseModel):
    laptop: bool = False
    phone: bool = False


class RoleIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    description: str | None = Field(default=None, max_length=300)
    pages: dict[str, PageAccess]
    laptop_home: str | None = Field(default=None, alias="laptopHome", max_length=40)
    phone_home: str | None = Field(default=None, alias="phoneHome", max_length=40)


class RolePatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=60)
    description: str | None = Field(default=None, max_length=300)
    pages: dict[str, PageAccess] | None = None
    laptop_home: str | None = Field(default=None, alias="laptopHome", max_length=40)
    phone_home: str | None = Field(default=None, alias="phoneHome", max_length=40)


def _role_json(r: Role, users: int) -> dict:
    return {
        "id": r.id, "key": r.key, "name": r.name, "description": r.description, "system": r.key is not None,
        "pages": parse_pages(r.pages), "laptopHome": r.laptop_home, "phoneHome": r.phone_home, "users": users,
        "updatedAt": r.updated_at.isoformat() if r.updated_at else None, "updatedBy": r.updated_by,
    }


def _clean_pages(pages: dict[str, PageAccess]) -> dict[str, dict[str, bool]]:
    unknown = [k for k in pages if k not in PAGE_KEYS]
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown page(s): {', '.join(unknown[:5])}")
    out = {k: {"laptop": bool(pages[k].laptop) if k in pages else False, "phone": bool(pages[k].phone) if k in pages else False} for k in PAGE_KEYS}
    if not any(v["laptop"] or v["phone"] for v in out.values()):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose at least one page for the role")
    return out


def _home(value: str | None, pages: dict[str, dict[str, bool]], device: str) -> str | None:
    """The page opened after sign-in on that device: one the role shows there (default: its first such page)."""
    shown = [k for k in PAGE_KEYS if pages[k][device]]
    if value:
        if value not in PAGE_KEYS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown start page '{value}'")
        if value not in shown:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"The {device} start page '{LABEL[value]}' is not shown on the {device} for this role")
        return value
    return shown[0] if shown else None


def _unique_name(db: Session, name: str, own: int | None = None) -> str:
    name = " ".join(name.split())
    other = db.scalars(select(Role).where(func.lower(Role.name) == name.lower())).first()
    if other is not None and other.id != own:
        raise HTTPException(status.HTTP_409_CONFLICT, f"A role named '{name}' already exists")
    if name.lower() == "admin":
        raise HTTPException(status.HTTP_409_CONFLICT, "'Admin' is the built-in administrator access – choose another name")
    return name


@router.get("")
def list_roles(db: Session = Depends(get_db)) -> dict:
    ensure_system_roles(db)
    counts = users_per_role(db)
    viewer = db.scalars(select(Role).where(Role.key == "viewer")).first()
    roles = list(db.scalars(select(Role).order_by(Role.key.is_(None), Role.id)))
    out = []
    for r in roles:
        n = counts.get(r.id, 0) + (counts.get(None, 0) if viewer is not None and r.id == viewer.id else 0)
        out.append(_role_json(r, n))
    admins = int(db.scalar(select(func.count()).select_from(User).where(User.role == "admin")) or 0)
    return {"pages": [{"key": k, "label": lbl, "group": g} for k, lbl, g in PAGES], "roles": out, "admins": admins}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_role(body: RoleIn, request: Request, admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    name = _unique_name(db, body.name)
    pages = _clean_pages(body.pages)
    r = Role(
        key=None, name=name, description=(body.description or "").strip() or None, pages=json.dumps(pages),
        laptop_home=_home(body.laptop_home, pages, "laptop"), phone_home=_home(body.phone_home, pages, "phone"), updated_by=admin.name,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    audit(db, "role_created", request, admin.id, f"{r.name}: {', '.join(k for k in PAGE_KEYS if pages[k]['laptop'] or pages[k]['phone'])}")
    return _role_json(r, 0)


@router.patch("/{role_id}")
def update_role(role_id: RoleId, body: RolePatch, request: Request, admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    r = db.get(Role, role_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")
    sent = body.model_fields_set
    if body.name is not None:
        r.name = _unique_name(db, body.name, r.id)
    if "description" in sent:
        r.description = (body.description or "").strip() or None
    pages = _clean_pages(body.pages) if body.pages is not None else parse_pages(r.pages)
    if body.pages is not None:
        r.pages = json.dumps(pages)
    # the start pages always follow the pages (re-checked whenever pages or a start page change)
    r.laptop_home = _home(body.laptop_home if "laptop_home" in sent else (r.laptop_home if r.laptop_home and pages.get(r.laptop_home, {}).get("laptop") else None), pages, "laptop")
    r.phone_home = _home(body.phone_home if "phone_home" in sent else (r.phone_home if r.phone_home and pages.get(r.phone_home, {}).get("phone") else None), pages, "phone")
    r.updated_by = admin.name
    db.commit()
    db.refresh(r)
    audit(db, "role_updated", request, admin.id, f"{r.name}: {', '.join(k for k in PAGE_KEYS if pages[k]['laptop'] or pages[k]['phone'])}")
    counts = users_per_role(db)
    return _role_json(r, counts.get(r.id, 0) + (counts.get(None, 0) if r.key == "viewer" else 0))


@router.delete("/{role_id}")
def delete_role(role_id: RoleId, request: Request, admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    r = db.get(Role, role_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")
    if r.key is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"'{r.name}' is a built-in role – it can be edited, not deleted")
    n = int(db.scalar(select(func.count()).select_from(User).where(User.role_id == r.id)) or 0)
    if n:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{n} user{'s' if n != 1 else ''} still ha{'ve' if n != 1 else 's'} the role '{r.name}' – give them another role first")
    name = r.name
    db.delete(r)
    db.commit()
    audit(db, "role_deleted", request, admin.id, name)
    return {"ok": True}
