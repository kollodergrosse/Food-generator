"""Data models for the meal plan app."""
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any


DEFAULT_MEALS = ["Frühstück", "Mittag", "Abend"]


@dataclass
class UserProfile:
    """A person in the household: dislikes, allergies, diet type, meal participation."""
    id: str
    name: str
    dislikes: List[str] = field(default_factory=list)  # foods the person doesn't like to eat
    allergies: List[str] = field(default_factory=list)
    diet_type: str = "keine"  # e.g. vegetarisch, vegan, keto, keine
    meals: List[str] = field(default_factory=lambda: list(DEFAULT_MEALS))  # which meals the person participates in

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "abneigungen": self.dislikes,
            "allergien": self.allergies,
            "diaetform": self.diet_type,
            "mahlzeiten": self.meals,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserProfile":
        return cls(
            id=data.get("id", ""),
            name=data.get("name", "Unbekannt"),
            dislikes=data.get("abneigungen", []),
            allergies=data.get("allergien", []),
            diet_type=data.get("diaetform", "keine"),
            meals=data.get("mahlzeiten", list(DEFAULT_MEALS)),
        )


@dataclass
class Household:
    """All the people for whom a meal plan is created together."""
    location: str = "Berlin"  # for weather data, shared by the whole household
    profiles: List[UserProfile] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"ort": self.location, "profile": [p.to_dict() for p in self.profiles]}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Household":
        return cls(
            location=data.get("ort", "Berlin"),
            profiles=[UserProfile.from_dict(p) for p in data.get("profile", [])],
        )


@dataclass
class Ingredient:
    """A quantity of an ingredient, e.g. in a recipe or the shopping list."""
    name: str
    amount: str = ""  # deliberately text instead of a number, since the AI may return e.g. "1-2" or "nach Geschmack"
    unit: str = ""
    checked: bool = False  # only relevant in the shopping list (already bought)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "menge": self.amount,
            "einheit": self.unit,
            "abgehakt": self.checked,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "Ingredient":
        if isinstance(data, str):
            return cls(name=data)
        return cls(
            name=data.get("name", ""),
            amount=str(data.get("menge", "")),
            unit=data.get("einheit", ""),
            checked=bool(data.get("abgehakt", False)),
        )


@dataclass
class Recipe:
    """A detailed recipe: ingredients with quantities and numbered preparation steps."""
    name: str
    servings: int = 1
    time_minutes: int = 0
    ingredients: List[Ingredient] = field(default_factory=list)
    instructions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "portionen": self.servings,
            "zeit_minuten": self.time_minutes,
            "zutaten": [i.to_dict() for i in self.ingredients],
            "zubereitung": self.instructions,
        }

    @classmethod
    def from_dict(cls, name: str, data: Any) -> "Recipe":
        if isinstance(data, str):
            # legacy format: dish name -> plain text
            return cls(name=name, instructions=[data] if data else [])
        return cls(
            name=name,
            servings=data.get("portionen", 1),
            time_minutes=data.get("zeit_minuten", 0),
            ingredients=[Ingredient.from_dict(i) for i in data.get("zutaten", [])],
            instructions=data.get("zubereitung", []),
        )


@dataclass
class MealPlan:
    """Result of the AI API: weekly plan, recipes, shopping list."""
    weekly_plan: Dict[str, Dict[str, str]]  # e.g. {"Montag": {"Frühstück": "...", "Mittag": "...", "Abend": "..."}}
    recipes: Dict[str, Recipe]              # dish name -> recipe
    shopping_list: List[Ingredient]
    temperatures: Dict[str, float] = field(default_factory=dict)  # weekday -> max temperature (°C)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wochenplan": self.weekly_plan,
            "rezepte": {name: recipe.to_dict() for name, recipe in self.recipes.items()},
            "einkaufsliste": [i.to_dict() for i in self.shopping_list],
            "temperaturen": self.temperatures,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MealPlan":
        return cls(
            weekly_plan=data.get("wochenplan", {}),
            recipes={
                name: Recipe.from_dict(name, recipe_data)
                for name, recipe_data in data.get("rezepte", {}).items()
            },
            shopping_list=[Ingredient.from_dict(i) for i in data.get("einkaufsliste", [])],
            temperatures=data.get("temperaturen", {}),
        )
