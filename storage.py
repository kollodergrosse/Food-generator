"""Storage module: persists the household (profiles) and plan history in the database."""
import uuid
from typing import List, Optional

from sqlalchemy import select

import db
import weather
from models import NUTRITION_FIELDS, CustomRecipe, Household, Ingredient, MealPlan, Nutrition, UserProfile, Visitor, _meals_by_day_from_raw

HOUSEHOLD_ID = 1  # there is currently exactly one household


def _nutrition_orm_kwargs(nutrition: Nutrition) -> dict:
    """Converts a Nutrition object into constructor/assignment kwargs for a RecipeORM or
    CustomRecipeORM row (both share the same set of nutrition columns, see db.NutritionColumnsMixin)."""
    return {attr: getattr(nutrition, attr) for attr, _ in NUTRITION_FIELDS}


def _nutrition_dict_from_row(row) -> dict:
    """Reads the nutrition columns off a RecipeORM/CustomRecipeORM row into the serialized dict
    shape expected by Nutrition.from_dict()."""
    return {json_key: getattr(row, attr) for attr, json_key in NUTRITION_FIELDS}


def load_household() -> Household:
    """Returns the household, creating and persisting a fresh default one on first run.

    A brand new install has no household row yet: instead of an empty household, it seeds one with
    an auto-detected location (see weather.detect_location()) and a single default profile, so the
    app is usable right away without a mandatory setup step.
    """
    with db.SessionLocal() as session:
        household_row = session.get(db.HouseholdORM, HOUSEHOLD_ID)
        if household_row is not None:
            return Household(
                location=household_row.location,
                profiles=[
                    UserProfile(
                        id=p.id,
                        name=p.name,
                        preferences=p.preferences or [],
                        dislikes=p.dislikes or [],
                        allergies=p.allergies or [],
                        diet_type=p.diet_type or "keine",
                        meals_by_day=_meals_by_day_from_raw(p.meals),
                    )
                    for p in household_row.profiles
                ],
                visitors=[
                    Visitor(
                        id=v.id,
                        name=v.name,
                        start_date=v.start_date,
                        end_date=v.end_date,
                        intolerances=v.intolerances or [],
                        diet_type=v.diet_type or "keine",
                        meals_by_day=_meals_by_day_from_raw(v.meals),
                    )
                    for v in household_row.visitors
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
    """Persists the household, replacing all its profiles and visitors with the given ones.

    Profiles/visitors without an id (newly added in the form) get one assigned here. Existing
    profile/visitor rows are dropped and reinserted rather than diffed/updated in place, since the
    household is always submitted and saved as a whole from a single form.
    """
    for profile in household.profiles:
        if not profile.id:
            profile.id = uuid.uuid4().hex[:8]
    for visitor in household.visitors:
        if not visitor.id:
            visitor.id = uuid.uuid4().hex[:8]

    with db.SessionLocal() as session:
        household_row = session.get(db.HouseholdORM, HOUSEHOLD_ID)
        if household_row is None:
            household_row = db.HouseholdORM(id=HOUSEHOLD_ID, location=household.location)
            session.add(household_row)
        else:
            household_row.location = household.location
            for old_profile_row in list(household_row.profiles):
                session.delete(old_profile_row)
            for old_visitor_row in list(household_row.visitors):
                session.delete(old_visitor_row)
        session.flush()

        for profile in household.profiles:
            session.add(db.ProfileORM(
                id=profile.id,
                household_id=HOUSEHOLD_ID,
                name=profile.name,
                preferences=profile.preferences,
                dislikes=profile.dislikes,
                allergies=profile.allergies,
                diet_type=profile.diet_type,
                meals=profile.meals_by_day,
            ))
        for visitor in household.visitors:
            session.add(db.VisitorORM(
                id=visitor.id,
                household_id=HOUSEHOLD_ID,
                name=visitor.name,
                start_date=visitor.start_date,
                end_date=visitor.end_date,
                intolerances=visitor.intolerances,
                diet_type=visitor.diet_type,
                meals=visitor.meals_by_day,
            ))
        session.commit()


def _custom_recipe_from_row(row) -> CustomRecipe:
    """Converts a CustomRecipeORM row into a CustomRecipe by routing it through the same
    from_dict() shape used for JSON, instead of duplicating its field mapping here."""
    return CustomRecipe.from_dict({
        "id": row.id,
        "name": row.name,
        "portionen": row.servings,
        "zutaten": row.ingredients or [],
        "zubereitung": row.instructions or [],
        "naehrwerte": _nutrition_dict_from_row(row),
        "mahlzeiten": row.meal_types or [],
        "youtube_link": row.youtube_link or "",
        "tags": row.tags or [],
    })


def load_custom_recipes() -> List[CustomRecipe]:
    """Returns every dish in the household's dish database, sorted alphabetically by name."""
    with db.SessionLocal() as session:
        rows = session.execute(select(db.CustomRecipeORM).order_by(db.CustomRecipeORM.name)).scalars().all()
        return [_custom_recipe_from_row(row) for row in rows]


def get_custom_recipe(recipe_id: str) -> Optional[CustomRecipe]:
    """Looks up a single dish by id without loading the entire dish database - e.g. used as a
    fallback to recover the previous nutrition estimate when a re-estimate fails during an edit."""
    with db.SessionLocal() as session:
        row = session.get(db.CustomRecipeORM, recipe_id)
        return _custom_recipe_from_row(row) if row is not None else None


def save_custom_recipe(recipe: CustomRecipe) -> CustomRecipe:
    """Inserts a new recipe, or overwrites the existing one if recipe.id already exists."""
    if not recipe.id:
        recipe.id = uuid.uuid4().hex[:8]

    with db.SessionLocal() as session:
        row = session.get(db.CustomRecipeORM, recipe.id)
        if row is None:
            row = db.CustomRecipeORM(id=recipe.id)
            session.add(row)
        row.name = recipe.name
        row.servings = recipe.servings
        row.ingredients = [i.to_dict() for i in recipe.ingredients]
        row.instructions = recipe.instructions
        row.meal_types = recipe.meal_types
        row.youtube_link = recipe.youtube_link
        row.tags = recipe.tags
        for attr, value in _nutrition_orm_kwargs(recipe.nutrition).items():
            setattr(row, attr, value)
        session.commit()

    return recipe


def delete_custom_recipe(recipe_id: str) -> bool:
    """Deletes a dish from the dish database by id. Returns False without error if no dish with
    that id exists, so the caller can turn that into a 404 instead of a crash."""
    with db.SessionLocal() as session:
        row = session.get(db.CustomRecipeORM, recipe_id)
        if row is None:
            return False
        session.delete(row)
        session.commit()
        return True


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
                youtube_link=recipe.youtube_link,
                **_nutrition_orm_kwargs(recipe.nutrition),
            ))
        session.add(plan_row)
        session.commit()


def _latest_plan_row(session):
    """Returns the MealPlanORM row of the most recently created plan, or None if there is none -
    the shared basis for "the current plan" used by load_plan() and all shopping-list operations."""
    return session.execute(
        select(db.MealPlanORM).order_by(db.MealPlanORM.created_at.desc(), db.MealPlanORM.id.desc())
    ).scalars().first()


def set_shopping_list_checked(index: int, checked: bool) -> Optional[List[Ingredient]]:
    """Checks/unchecks an item in the shopping list of the current (latest) plan."""
    with db.SessionLocal() as session:
        plan_row = _latest_plan_row(session)
        if plan_row is None or not (0 <= index < len(plan_row.shopping_list)):
            return None

        items = list(plan_row.shopping_list)
        items[index] = {**items[index], "abgehakt": checked}
        plan_row.shopping_list = items  # reassign the column so SQLAlchemy detects the change
        session.commit()
        return [Ingredient.from_dict(i) for i in items]


def add_shopping_list_item(name: str, amount: str = "", unit: str = "") -> List[Ingredient]:
    """Adds a manually entered item to the current (latest) shopping list - unrelated to any
    recipe. Creates a fresh, otherwise-empty plan first if none exists yet, so the shopping list
    is usable even before the first AI-generated weekly plan."""
    with db.SessionLocal() as session:
        plan_row = _latest_plan_row(session)
        if plan_row is None:
            plan_row = db.MealPlanORM(weekly_plan={}, shopping_list=[], temperatures={})
            session.add(plan_row)
            session.flush()

        items = list(plan_row.shopping_list)
        items.append(Ingredient(name=name, amount=amount, unit=unit).to_dict())
        plan_row.shopping_list = items
        session.commit()
        return [Ingredient.from_dict(i) for i in items]


def update_shopping_list_item(index: int, name: str, amount: str, unit: str) -> Optional[List[Ingredient]]:
    """Overwrites name/amount/unit of an existing shopping-list item, keeping its checked state."""
    with db.SessionLocal() as session:
        plan_row = _latest_plan_row(session)
        if plan_row is None or not (0 <= index < len(plan_row.shopping_list)):
            return None

        items = list(plan_row.shopping_list)
        items[index] = {**items[index], "name": name, "menge": amount, "einheit": unit}
        plan_row.shopping_list = items
        session.commit()
        return [Ingredient.from_dict(i) for i in items]


def delete_shopping_list_item(index: int) -> Optional[List[Ingredient]]:
    """Removes a single item from the shopping list of the current (latest) plan by position."""
    with db.SessionLocal() as session:
        plan_row = _latest_plan_row(session)
        if plan_row is None or not (0 <= index < len(plan_row.shopping_list)):
            return None

        items = list(plan_row.shopping_list)
        items.pop(index)
        plan_row.shopping_list = items
        session.commit()
        return [Ingredient.from_dict(i) for i in items]


def load_plan() -> Optional[MealPlan]:
    """Returns the most recently created plan (latest row in history), or None if there is no plan yet."""
    with db.SessionLocal() as session:
        plan_row = _latest_plan_row(session)
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
                    "naehrwerte": _nutrition_dict_from_row(r),
                    "youtube_link": r.youtube_link or "",
                }
                for r in plan_row.recipes
            },
            "einkaufsliste": plan_row.shopping_list,
            "temperaturen": plan_row.temperatures,
        })
