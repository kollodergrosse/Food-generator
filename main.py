"""Meal plan app: orchestrates the flow from the architecture diagram.

Household (multiple profiles) + weather data -> AI API -> weekly plan -> recipes + shopping list -> storage -> user
"""
from pathlib import Path

from dotenv import load_dotenv

from ai_client import AIClient
from db import init_db
from models import MealPlan
from storage import load_household, save_plan
from weather import get_daily_temperatures


def show_summary(plan: MealPlan) -> None:
    print("\n=== Wochenplan ===")
    for day, meals in plan.weekly_plan.items():
        print(f"{day}: " + " | ".join(f"{meal}: {dish}" for meal, dish in meals.items()))

    print("\n=== Einkaufsliste ===")
    for ingredient in plan.shopping_list:
        print(f"- {ingredient.amount} {ingredient.unit} {ingredient.name}".strip())


def main() -> None:
    load_dotenv(Path(__file__).parent / ".env")
    init_db()

    household = load_household()
    temperatures = get_daily_temperatures(household.location)
    print(f"Temperaturen in {household.location}: " + ", ".join(f"{day} {temp}°C" for day, temp in temperatures.items()))
    print("Haushalt: " + ", ".join(p.name for p in household.profiles))

    ai = AIClient()
    plan = ai.create_meal_plan(household, temperatures)

    save_plan(plan)
    show_summary(plan)


if __name__ == "__main__":
    main()
