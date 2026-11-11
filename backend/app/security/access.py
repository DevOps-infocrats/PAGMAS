"""Data access: which part of the dashboard data a signed-in user may see.

  admin                    everything
  viewer without an area   everything (as before areas also limited the dashboard)
  viewer with areas        only the GPs of their circles / districts / blocks (User Management) – on every
                           dashboard page, list, search, download and Field Team view
  viewer whose areas are no longer in the data   nothing (403) – access is never widened

The same areas decide the viewer's AMC Conversion e-mail (mail/audience.py). Enforced here, on the server, by
handing the analytics endpoints a snapshot cut to those GPs (analytics.store.scoped_store).
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analytics.store import Store, get_store, scoped_store
from ..db import get_db
from ..models import UserScope
from .deps import CurrentUser, get_current_user

NO_ACCESS = "None of your assigned areas is in the current data. Please ask an administrator to update your areas."


def user_areas(db: Session, user: CurrentUser) -> tuple[tuple[str, str], ...]:
    """The viewer's areas as sorted (level, id) pairs; empty for admins and viewers without an area."""
    if user.is_admin:
        return ()
    rows = db.execute(select(UserScope.level, UserScope.scope_id).where(UserScope.user_id == user.id)).all()
    return tuple(sorted({(r.level, r.scope_id) for r in rows}))


def access_summary(db: Session, user: CurrentUser) -> dict:
    """What the user sees, for the header: {"scope": "all"} or {"scope": "areas", "areas": [readable labels]}."""
    areas = user_areas(db, user)
    if not areas:
        return {"scope": "all", "areas": []}
    from ..analytics.store import NoDataError
    from ..mail.audience import locations

    try:
        locs = locations(get_store())
    except NoDataError:
        locs = {}
    labels = [locs[lvl][i] if i in locs.get(lvl, {}) else f"{i} (not in the current data)" for lvl, i in areas]
    return {"scope": "areas", "areas": labels}


def get_user_store(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> Store:
    """The snapshot this user may see (use instead of get_store on every user-facing data endpoint)."""
    base = get_store()
    areas = user_areas(db, user)
    if not areas:
        return base
    scoped = scoped_store(base, areas)
    if scoped is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, NO_ACCESS)
    return scoped
