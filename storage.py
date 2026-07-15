"""Storage module: persists the household (profiles) and plan history in the database."""
import uuid
from typing import Optional

from sqlalchemy import select

import db
import weather
from models import DEFAULT_MEALS, Household, MealPlan, UserProfile

HOUSEHOLD_ID = 1  # there is currently exactly one household


def load_household() -> Household:
    with db.SessionLocal() as session:
        household_row = session.get(db.HouseholdORM, HOUSEHOLD_ID)
        if household_row is not None:
            return Household(
                location=household_row.location,
                profiles=[
                    UserProfile(
                        id=p.id,
                        name=p.name,
                        dislikes=p.dislikes or [],
                        allergies=p.allergies or [],
                        diet_type=p.diet_type or "keine",
                        meals=p.meals or list(DEFAULT_MEALS),
                    )
                    for p in household_row.profiles
                ],
            )

    # Brand new install with no existing data: detect the location automatically instead of manually.
    detected_location = weather.detect_location()
    new_household = Household(
        location=detected_location or "Berlin",
        profiles=[UserProfile(id=uuid.uuid4().hex[:8], name="Familie")],
    )
    save_household(new_household)
    return new_household


def save_household(household: Household) -> None:
    for profile in household.profiles:
        if not profile.id:
            profile.id = uuid.uuid4().hex[:8]

    with db.SessionLocal() as session:
        household_row = session.get(db.HouseholdORM, HOUSEHOLD_ID)
        if household_row is None:
            household_row = db.HouseholdORM(id=HOUSEHOLD_ID, location=household.location)
            session.add(household_row)
        else:
            household_row.location = household.location
            for old_profile_row in list(household_row.profiles):
                session.delete(old_profile_row)
        session.flush()

        for profile in household.profiles:
            session.add(db.ProfileORM(
                id=profile.id,
                household_id=HOUSEHOLD_ID,
                name=profile.name,
                dislikes=profile.dislikes,
                allergies=profile.allergies,
                diet_type=profile.diet_type,
                meals=profile.meals,
            ))
        session.commit()


def save_plan(plan: MealPlan) -> None:
    """Adds a new row (plan history) instead of overwriting the previous plan."""
    with db.SessionLocal() as session:
        plan_row = db.MealPlanORM(
            weekly_plan=plan.weekly_plan,
            shopping_list=[i.to_dict() for i in plan.shopping_list],
            temperatures=plan.temperatures,
        )
        for name, recipe in plan.recipes.items():
            plan_row.recipes.append(db.RecipeORM(
                name=name,
                servings=recipe.servings,
                time_minutes=recipe.time_minutes,
                ingredients=[i.to_dict() for i in recipe.ingredients],
                instructions=recipe.instructions,
            ))
        session.add(plan_row)
        session.commit()


def set_shopping_list_checked(index: int, checked: bool) -> Optional[MealPlan]:
    """Checks/unchecks an item in the shopping list of the current (latest) plan."""
    with db.SessionLocal() as session:
        plan_row = session.execute(
            select(db.MealPlanORM).order_by(db.MealPlanORM.created_at.desc(), db.MealPlanORM.id.desc())
        ).scalars().first()
        if plan_row is None or not (0 <= index < len(plan_row.shopping_list)):
            return None

        items = list(plan_row.shopping_list)
        items[index] = {**items[index], "abgehakt": checked}
        plan_row.shopping_list = items  # reassign the column so SQLAlchemy detects the change
        session.commit()

    return load_plan()


def load_plan() -> Optional[MealPlan]:
    """Returns the most recently created plan (latest row in history), or None if there is no plan yet."""
    with db.SessionLocal() as session:
        plan_row = session.execute(
            select(db.MealPlanORM).order_by(db.MealPlanORM.created_at.desc(), db.MealPlanORM.id.desc())
        ).scalars().first()
        if plan_row is None:
            return None
        return MealPlan.from_dict({
            "wochenplan": plan_row.weekly_plan,
            "rezepte": {
                r.name: {
                    "portionen": r.servings,
                    "zeit_minuten": r.time_minutes,
                    "zutaten": r.ingredients,
                    "zubereitung": r.instructions,
                }
                for r in plan_row.recipes
            },
            "einkaufsliste": plan_row.shopping_list,
            "temperaturen": plan_row.temperatures,
        })
