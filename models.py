"""Data models for the meal plan app."""
from dataclasses import dataclass, field
from typing import List, Dict, Any


DEFAULT_MEALS = ["Frühstück", "Mittag", "Abend"]
WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def _default_meals_by_day() -> Dict[str, List[str]]:
    """Returns a fresh mapping of every weekday to all default meals - the participation of a
    brand new profile/visitor before the user restricts it in the household form."""
    return {day: list(DEFAULT_MEALS) for day in WEEKDAYS}


def _meals_by_day_from_raw(raw: Any) -> Dict[str, List[str]]:
    """Normalizes the stored meal participation into a per-weekday mapping. Accepts either the
    current per-weekday dict (missing days mean no meal participation that day), the legacy flat
    list of meals (applied to every day, from before per-weekday selection existed), or nothing
    (brand new profile, defaults to all meals every day)."""
    if isinstance(raw, dict):
        return {day: list(raw.get(day, [])) for day in WEEKDAYS}
    if isinstance(raw, list) and raw:
        return {day: list(raw) for day in WEEKDAYS}
    return _default_meals_by_day()


def _raw_meals_from_data(data: Dict[str, Any]) -> Any:
    """Reads the meal-participation field from a serialized profile/visitor - the current
    per-weekday key if present, otherwise the legacy flat-list key."""
    return data["mahlzeiten_je_tag"] if data.get("mahlzeiten_je_tag") is not None else data.get("mahlzeiten")


@dataclass
class UserProfile:
    """A person in the household: preferences, dislikes, allergies, diet type, meal participation."""
    id: str
    name: str
    preferences: List[str] = field(default_factory=list)  # things the person especially likes, e.g. "scharf"
    dislikes: List[str] = field(default_factory=list)  # foods the person doesn't like to eat
    allergies: List[str] = field(default_factory=list)
    diet_type: str = "keine"  # e.g. vegetarisch, vegan, keto, keine
    meals_by_day: Dict[str, List[str]] = field(default_factory=_default_meals_by_day)  # weekday -> participated meals

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the profile to the German-keyed JSON shape used by the API and frontend."""
        return {
            "id": self.id,
            "name": self.name,
            "vorlieben": self.preferences,
            "abneigungen": self.dislikes,
            "allergien": self.allergies,
            "diaetform": self.diet_type,
            "mahlzeiten_je_tag": self.meals_by_day,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserProfile":
        """Builds a profile from the JSON shape sent by the frontend/API, tolerating the legacy
        flat-list meal-participation format via _raw_meals_from_data()/_meals_by_day_from_raw()."""
        raw_meals = _raw_meals_from_data(data)
        return cls(
            id=data.get("id", ""),
            name=data.get("name", "Unbekannt"),
            preferences=data.get("vorlieben", []),
            dislikes=data.get("abneigungen", []),
            allergies=data.get("allergien", []),
            diet_type=data.get("diaetform", "keine"),
            meals_by_day=_meals_by_day_from_raw(raw_meals),
        )


@dataclass
class Visitor:
    """A temporary guest staying with the household for a limited date range, e.g. over a weekend."""
    id: str
    name: str
    start_date: str  # ISO format YYYY-MM-DD
    end_date: str  # ISO format YYYY-MM-DD
    intolerances: List[str] = field(default_factory=list)
    diet_type: str = "keine"
    meals_by_day: Dict[str, List[str]] = field(default_factory=_default_meals_by_day)  # weekday -> participated meals

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the visitor to the German-keyed JSON shape used by the API and frontend."""
        return {
            "id": self.id,
            "name": self.name,
            "von": self.start_date,
            "bis": self.end_date,
            "unvertraeglichkeiten": self.intolerances,
            "diaetform": self.diet_type,
            "mahlzeiten_je_tag": self.meals_by_day,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Visitor":
        """Builds a visitor from the JSON shape sent by the frontend/API, tolerating the legacy
        flat-list meal-participation format via _raw_meals_from_data()/_meals_by_day_from_raw()."""
        raw_meals = _raw_meals_from_data(data)
        return cls(
            id=data.get("id", ""),
            name=data.get("name", "Unbekannt"),
            start_date=data.get("von", ""),
            end_date=data.get("bis", ""),
            intolerances=data.get("unvertraeglichkeiten", []),
            diet_type=data.get("diaetform", "keine"),
            meals_by_day=_meals_by_day_from_raw(raw_meals),
        )


@dataclass
class Household:
    """All the people for whom a meal plan is created together."""
    location: str = "Berlin"  # for weather data, shared by the whole household
    profiles: List[UserProfile] = field(default_factory=list)
    visitors: List[Visitor] = field(default_factory=list)  # temporary guests with a limited date range

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the household, including all profiles and visitors, to the German-keyed JSON
        shape used by the API and frontend."""
        return {
            "ort": self.location,
            "profile": [p.to_dict() for p in self.profiles],
            "besucher": [v.to_dict() for v in self.visitors],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Household":
        """Builds a household, including all profiles and visitors, from the JSON shape sent by the
        frontend/API."""
        return cls(
            location=data.get("ort", "Berlin"),
            profiles=[UserProfile.from_dict(p) for p in data.get("profile", [])],
            visitors=[Visitor.from_dict(v) for v in data.get("besucher", [])],
        )


@dataclass
class Ingredient:
    """A quantity of an ingredient, e.g. in a recipe or the shopping list."""
    name: str
    amount: str = ""  # deliberately text instead of a number, since the AI may return e.g. "1-2" or "nach Geschmack"
    unit: str = ""
    checked: bool = False  # only relevant in the shopping list (already bought)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the ingredient to the German-keyed JSON shape used by the API and frontend."""
        return {
            "name": self.name,
            "menge": self.amount,
            "einheit": self.unit,
            "abgehakt": self.checked,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "Ingredient":
        """Builds an ingredient from its JSON shape, or from a plain name string (legacy format:
        older shopping-list entries stored before quantities were tracked)."""
        if isinstance(data, str):
            return cls(name=data)
        return cls(
            name=data.get("name", ""),
            amount=str(data.get("menge", "")),
            unit=data.get("einheit", ""),
            checked=bool(data.get("abgehakt", False)),
        )


# Canonical (Python attribute name, German JSON key) pairs for every nutrition value - the single
# source of truth Nutrition.to_dict()/from_dict() are built from below. db.py and storage.py build
# their own field mappings (ALTER-TABLE column list, ORM<->dict conversion) from this same tuple
# instead of repeating the field list by hand, so a new nutrition field only needs to be added here
# plus as a Column in db.NutritionColumnsMixin.
NUTRITION_FIELDS = (
    ("calories", "kalorien"),
    ("protein", "eiweiss"),
    ("fat", "fett"),
    ("saturated_fat", "gesaettigte_fettsaeuren"),
    ("carbs", "kohlenhydrate"),
    ("sugar", "zucker"),
    ("salt", "salz"),
)


@dataclass
class Nutrition:
    """Nutritional values per portion (Nährwerttabelle, wie auf einer Lebensmittelverpackung)."""
    calories: float = 0  # kcal
    protein: float = 0  # g
    fat: float = 0  # g
    saturated_fat: float = 0  # g, "davon gesättigte Fettsäuren"
    carbs: float = 0  # g
    sugar: float = 0  # g, "davon Zucker"
    salt: float = 0  # g

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the nutrition values to the German-keyed JSON shape used by the API and frontend."""
        return {json_key: getattr(self, attr) for attr, json_key in NUTRITION_FIELDS}

    @classmethod
    def from_dict(cls, data: Any) -> "Nutrition":
        """Builds nutrition values from their JSON shape, defaulting missing/null fields to 0 (e.g.
        for a dish that has never had its nutrition estimated yet)."""
        data = data or {}
        return cls(**{attr: data.get(json_key, 0) or 0 for attr, json_key in NUTRITION_FIELDS})


@dataclass
class Recipe:
    """A detailed recipe: ingredients with quantities and numbered preparation steps."""
    name: str
    servings: int = 1
    time_minutes: int = 0
    ingredients: List[Ingredient] = field(default_factory=list)
    instructions: List[str] = field(default_factory=list)
    nutrition: Nutrition = field(default_factory=Nutrition)  # per portion
    youtube_link: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the recipe to the German-keyed JSON shape used by the API and frontend."""
        return {
            "name": self.name,
            "portionen": self.servings,
            "zeit_minuten": self.time_minutes,
            "zutaten": [i.to_dict() for i in self.ingredients],
            "zubereitung": self.instructions,
            "naehrwerte": self.nutrition.to_dict(),
            "youtube_link": self.youtube_link,
        }

    @classmethod
    def from_dict(cls, name: str, data: Any) -> "Recipe":
        """Builds a recipe from its JSON shape, or from a plain instruction string (legacy format:
        recipes stored before structured ingredients/nutrition existed)."""
        if isinstance(data, str):
            # legacy format: dish name -> plain text
            return cls(name=name, instructions=[data] if data else [])
        return cls(
            name=name,
            servings=data.get("portionen", 1),
            time_minutes=data.get("zeit_minuten", 0),
            ingredients=[Ingredient.from_dict(i) for i in data.get("zutaten", [])],
            instructions=data.get("zubereitung", []),
            nutrition=Nutrition.from_dict(data.get("naehrwerte")),
            youtube_link=data.get("youtube_link", ""),
        )


@dataclass
class CustomRecipe:
    """A pre-made dish in the household's dish database - the basis the AI selects from when
    building the weekly plan, and also browsable as a personal recipe collection."""
    id: str
    name: str
    servings: int = 1
    ingredients: List[Ingredient] = field(default_factory=list)
    instructions: List[str] = field(default_factory=list)
    nutrition: Nutrition = field(default_factory=Nutrition)  # per portion
    meal_types: List[str] = field(default_factory=list)  # suitable for which meals
    youtube_link: str = ""
    tags: List[str] = field(default_factory=list)  # free-form characteristics, e.g. "scharf", "mediterran"

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the dish to the German-keyed JSON shape used by the API and frontend."""
        return {
            "id": self.id,
            "name": self.name,
            "portionen": self.servings,
            "zutaten": [i.to_dict() for i in self.ingredients],
            "zubereitung": self.instructions,
            "naehrwerte": self.nutrition.to_dict(),
            "mahlzeiten": self.meal_types,
            "youtube_link": self.youtube_link,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CustomRecipe":
        """Builds a dish from the JSON shape sent by the frontend/API."""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", "Unbekannt"),
            servings=data.get("portionen", 1),
            ingredients=[Ingredient.from_dict(i) for i in data.get("zutaten", [])],
            instructions=data.get("zubereitung", []),
            nutrition=Nutrition.from_dict(data.get("naehrwerte")),
            meal_types=data.get("mahlzeiten") or [],
            youtube_link=data.get("youtube_link", ""),
            tags=data.get("tags") or [],
        )


@dataclass
class MealPlan:
    """Result of the AI API: weekly plan, recipes, shopping list."""
    weekly_plan: Dict[str, Dict[str, str]]  # e.g. {"Montag": {"Frühstück": "...", "Mittag": "...", "Abend": "..."}}
    recipes: Dict[str, Recipe]              # dish name -> recipe
    shopping_list: List[Ingredient]
    temperatures: Dict[str, float] = field(default_factory=dict)  # weekday -> max temperature (°C)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the plan, including all its recipes and the shopping list, to the
        German-keyed JSON shape used by the API and frontend."""
        return {
            "wochenplan": self.weekly_plan,
            "rezepte": {name: recipe.to_dict() for name, recipe in self.recipes.items()},
            "einkaufsliste": [i.to_dict() for i in self.shopping_list],
            "temperaturen": self.temperatures,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MealPlan":
        """Builds a plan, including all its recipes and the shopping list, from the JSON shape
        produced by to_dict() (as read back from storage)."""
        return cls(
            weekly_plan=data.get("wochenplan", {}),
            recipes={
                name: Recipe.from_dict(name, recipe_data)
                for name, recipe_data in data.get("rezepte", {}).items()
            },
            shopping_list=[Ingredient.from_dict(i) for i in data.get("einkaufsliste", [])],
            temperatures=data.get("temperaturen", {}),
        )
