"""AI API module: the AI picks, per day and meal, a fitting dish from the household's dish database
based on the weather forecast - it no longer invents recipes freely. Scaling ingredients to the
actual number of participants and aggregating the shopping list happens deterministically in Python,
since the dish data (unlike free-form AI output) is already trustworthy and structured."""
import difflib
import json
import os
import re
from datetime import date, timedelta

from openai import OpenAI

from models import (
    DEFAULT_MEALS,
    WEEKDAYS,
    CustomRecipe,
    Household,
    Ingredient,
    MealPlan,
    Nutrition,
    Recipe,
    UserProfile,
    Visitor,
)

_AMOUNT_RE = re.compile(r"\d+[.,]?\d*")
_SYSTEM_PROMPT = "Du bist ein Ernährungsassistent und antwortest ausschließlich mit gültigem JSON."


class AIClient:
    """Wraps the OpenAI chat API for the two AI-backed features of the app: picking a weekly meal
    plan from the dish database (create_meal_plan) and estimating a dish's nutrition from its
    ingredients (estimate_nutrition)."""

    def __init__(self, api_key: str | None = None, model: str = "gpt-4o-mini"):
        """Creates the OpenAI client used for all requests. Falls back to the OPENAI_API_KEY
        environment variable when no key is passed explicitly."""
        self.client = OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))
        self.model = model

    def _ask_json(self, prompt: str) -> dict:
        """Sends a prompt with the shared system instructions and returns the parsed JSON response."""
        response = self.client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        return self._extract_json(response.choices[0].message.content)

    def create_meal_plan(
        self, household: Household, temperatures: dict[str, float], dishes: list[CustomRecipe]
    ) -> MealPlan:
        """Builds the weekly meal plan: for each of the next 7 days and each active meal, narrows
        the dish database down to what's actually eligible (correct meal type, no allergens for
        that day's participants), asks the AI to pick one dish per slot from that narrowed list
        based on the weather forecast, and assembles the result into a MealPlan with recipes scaled
        to the day's headcount and an aggregated shopping list.

        Raises ValueError with a user-facing German message when the dish database is empty, when
        nobody in the household participates in any meal, or when a day/meal has no eligible dish
        left after filtering out allergens.
        """
        if not dishes:
            raise ValueError(
                "Es sind noch keine Gerichte in der Gerichte-Datenbank hinterlegt. Bitte zuerst unter "
                "'Gerichte-Datenbank' einige Gerichte anlegen."
            )

        dates_by_weekday = self._upcoming_dates()
        participants_per_day = self._participants_per_day(household, dates_by_weekday)

        if not any(participants_per_day[day][meal] for day in dates_by_weekday for meal in DEFAULT_MEALS):
            raise ValueError(
                "Im Haushalt nimmt niemand an einer Mahlzeit teil. Bitte mindestens eine Person mit "
                "mindestens einer Mahlzeit im Haushalt hinterlegen."
            )

        eligible_per_day: dict[str, dict[str, list]] = {}
        for day in dates_by_weekday:
            eligible_per_day[day] = {}
            for meal in DEFAULT_MEALS:
                participants = participants_per_day[day][meal]
                if not participants:
                    continue
                allergies = {a for p in participants for a in self._participant_allergies(p)}
                eligible = [
                    dish for dish in dishes
                    if meal in dish.meal_types and not self._dish_contains_allergen(dish, allergies)
                ]
                if not eligible:
                    raise ValueError(
                        f"Keine passenden Gerichte für '{meal}' am {day} in der Gerichte-Datenbank (nach "
                        f"Ausschluss der Allergien/Unverträglichkeiten der Teilnehmer an diesem Tag). Bitte "
                        f"weitere Gerichte hinzufügen oder deren Mahlzeiten-Zuordnung prüfen."
                    )
                eligible_per_day[day][meal] = eligible

        prompt = self._build_prompt(temperatures, dates_by_weekday, participants_per_day, eligible_per_day)
        data = self._ask_json(prompt)
        return self._assemble_plan(data.get("wochenplan", {}), participants_per_day, dishes, temperatures)

    def estimate_nutrition(self, ingredients: list[Ingredient], servings: int) -> Nutrition:
        """Estimates approximate per-portion nutrition values from a list of ingredients with
        quantities - a rough reference value, not an exact calculation, so the user no longer has
        to look up and enter nutrition data by hand for every dish."""
        ingredient_lines = "\n".join(
            f"- {' '.join(part for part in (ingredient.amount, ingredient.unit, ingredient.name) if part)}"
            for ingredient in ingredients
            if ingredient.name
        )
        if not ingredient_lines:
            return Nutrition()

        prompt = f"""Schätze die ungefähren Nährwerte PRO PORTION für ein Gericht mit {max(servings, 1)}
Portion(en) insgesamt. Die folgenden Mengenangaben gelten für das GESAMTE Gericht (alle Portionen
zusammen), nicht pro Portion:

{ingredient_lines}

Das sind bewusst nur grobe Richtwerte, keine exakte Nährwertberechnung - schätze auf Basis
typischer Nährwerttabellen und runde großzügig.

Gib AUSSCHLIESSLICH gültiges JSON in genau diesem Format zurück, ohne weiteren Text (alle Werte pro
Portion, als Zahlen ohne Einheiten):
{{"kalorien": 0, "eiweiss": 0, "fett": 0, "gesaettigte_fettsaeuren": 0, "kohlenhydrate": 0, "zucker": 0, "salz": 0}}"""

        data = self._ask_json(prompt)
        return Nutrition.from_dict(data)

    @staticmethod
    def _upcoming_dates() -> dict[str, date]:
        """Maps each weekday name to its actual calendar date for the coming 7 days, e.g.
        {"Dienstag": date(2026, 7, 22), ...} - matches how weather.get_daily_temperatures() keys
        its result, so a visitor's date range can be checked against the day being planned."""
        today = date.today()
        return {WEEKDAYS[(today + timedelta(days=i)).weekday()]: today + timedelta(days=i) for i in range(7)}

    @staticmethod
    def _visitor_active_on(visitor: Visitor, day: date) -> bool:
        """Returns whether a visitor's date range covers the given calendar day. Treats an
        unparseable/empty date range as "not active" instead of raising, since it's user-entered
        text."""
        try:
            start = date.fromisoformat(visitor.start_date)
            end = date.fromisoformat(visitor.end_date)
        except ValueError:
            return False
        return start <= day <= end

    @classmethod
    def _participants_per_day(
        cls, household: Household, dates_by_weekday: dict[str, date]
    ) -> dict[str, dict[str, list]]:
        """Resolves, for every day and meal, exactly who is eating (permanent profiles plus any
        visitors whose date range covers that day) - the basis for headcounts, allergen filtering,
        and preference aggregation, since participation can differ from day to day."""
        result = {}
        for day, day_date in dates_by_weekday.items():
            active_visitors = [v for v in household.visitors if cls._visitor_active_on(v, day_date)]
            result[day] = {
                meal: [p for p in household.profiles if meal in p.meals_by_day.get(day, [])]
                + [v for v in active_visitors if meal in v.meals_by_day.get(day, [])]
                for meal in DEFAULT_MEALS
            }
        return result

    @staticmethod
    def _participant_allergies(participant) -> list[str]:
        """Returns the allergens to avoid for a participant, which may be a UserProfile
        (`allergies`) or a Visitor (`intolerances` - the equivalent field under a different name)."""
        return participant.allergies if isinstance(participant, UserProfile) else participant.intolerances

    @staticmethod
    def _participant_preferences(participant) -> list[str]:
        """Returns a participant's liked foods, or an empty list for a Visitor, which has no
        preferences field (only dietary intolerances are tracked for temporary guests)."""
        return participant.preferences if isinstance(participant, UserProfile) else []

    @staticmethod
    def _participant_dislikes(participant) -> list[str]:
        """Returns a participant's disliked foods, or an empty list for a Visitor, which has no
        dislikes field (only dietary intolerances are tracked for temporary guests)."""
        return participant.dislikes if isinstance(participant, UserProfile) else []

    @staticmethod
    def _dish_contains_allergen(dish: CustomRecipe, allergens: set[str]) -> bool:
        """Checks whether a dish's name or any of its ingredient names mentions one of the given
        allergens (case-insensitive substring match) - used to exclude dishes from the AI's choices
        rather than relying on the AI itself to respect allergies."""
        if not allergens:
            return False
        haystack = dish.name.casefold() + " " + " ".join(i.name.casefold() for i in dish.ingredients)
        return any(allergen.strip() and allergen.strip().casefold() in haystack for allergen in allergens)

    @classmethod
    def _build_prompt(
        cls,
        temperatures: dict[str, float],
        dates_by_weekday: dict[str, date],
        participants_per_day: dict[str, dict[str, list]],
        eligible_per_day: dict[str, dict[str, list]],
    ) -> str:
        """Builds the German prompt text: one block per day (or a "no meals" note when nobody
        participates that day) listing, per active meal, the participants, their combined dietary
        needs/preferences and the eligible dishes to choose from, plus a JSON skeleton the AI must
        fill in - so the AI only ever has to return dish names, never invent new dishes or scale
        quantities itself."""
        day_blocks = []
        skeleton_days = []
        for day, day_date in dates_by_weekday.items():
            active_meals_today = [m for m in DEFAULT_MEALS if participants_per_day[day][m]]
            temp = temperatures.get(day, "unbekannt")
            if not active_meals_today:
                day_blocks.append(
                    f"## {day} ({day_date.isoformat()}) - Höchsttemperatur ca. {temp} °C\n"
                    f"  Keine Mahlzeiten an diesem Tag - niemand nimmt teil, KEINEN Eintrag dafür anlegen."
                )
                continue
            meal_fields = ", ".join(f'"{m}": "..."' for m in active_meals_today)
            skeleton_days.append(f'"{day}": {{{meal_fields}}}')

            meal_blocks = []
            for meal in active_meals_today:
                participants = participants_per_day[day][meal]
                preferences = sorted({a for p in participants for a in cls._participant_preferences(p)})
                dislikes = sorted({a for p in participants for a in cls._participant_dislikes(p)})
                diet_types = sorted({p.diet_type for p in participants if p.diet_type and p.diet_type != "keine"})
                names = ", ".join(p.name for p in participants)
                dish_lines = "\n".join(
                    f'      - "{dish.name}" (Zutaten: '
                    f'{", ".join(i.name for i in dish.ingredients) or "keine Angabe"})'
                    for dish in eligible_per_day[day][meal]
                )
                meal_blocks.append(
                    f"  - {meal} ({len(participants)} Person(en): {names})\n"
                    f"    - Diätform-Schnittmenge (muss zu ALLEN hier genannten Diätformen gleichzeitig passen): "
                    f"{', '.join(diet_types) or 'keine besonderen'}\n"
                    f"    - Abneigungen WENN MÖGLICH meiden (weicher, Vereinigung aller Teilnehmer): "
                    f"{', '.join(dislikes) or 'keine'}\n"
                    f"    - Vorlieben WENN MÖGLICH berücksichtigen (Vereinigung aller Teilnehmer): "
                    f"{', '.join(preferences) or 'keine besonderen'}\n"
                    f"    - Zur Auswahl stehende Gerichte für diese Mahlzeit (Allergien/Unverträglichkeiten sind "
                    f"hier bereits herausgefiltert):\n{dish_lines}"
                )
            day_blocks.append(
                f"## {day} ({day_date.isoformat()}) - Höchsttemperatur ca. {temp} °C\n" + "\n".join(meal_blocks)
            )

        days_text = "\n\n".join(day_blocks)
        skeleton = "{\n  \"wochenplan\": {" + ", ".join(skeleton_days) + "}\n}"

        return f"""Wähle für einen Essensplan für die kommenden 7 Tage für jeden Tag und jede dort aktive
Mahlzeit GENAU EIN Gericht AUSSCHLIESSLICH aus der jeweils aufgelisteten Auswahl - erfinde keine neuen
Gerichte und übernimm den Namen exakt so, wie er dort steht.

Jeder Tag kann eine unterschiedliche Zusammensetzung an Teilnehmern haben (z.B. durch zeitlich
begrenzte Besucher, die nur an einem Teil der Woche dabei sind) und dadurch auch unterschiedliche
aktive Mahlzeiten, Einschränkungen und Gerichteauswahlen. Erstelle NUR für die pro Tag unten explizit
aufgeführten Mahlzeiten einen Eintrag - für Tage bzw. Mahlzeiten ohne Teilnehmer keinen Eintrag anlegen:

{days_text}

WICHTIG: Es gibt pro Mahlzeit nur EIN gemeinsames Gericht für alle Teilnehmer dieser Mahlzeit an diesem
Tag, keine Ersatzgerichte pro Person. Berücksichtige die Abneigungen aller Teilnehmer über die Woche
möglichst ausgeglichen (nicht nur die einer Person).

Wähle das Gericht für JEDEN Tag individuell passend zur Temperatur an GENAU DIESEM Tag aus der
jeweiligen Auswahl (z.B. an einem warmen Tag über 20 °C eher leichte/kalte Gerichte, an einem kalten
Tag unter 10 °C eher wärmende/deftige Gerichte, soweit die Auswahl das zulässt). Die Temperatur kann
von Tag zu Tag stark schwanken - berücksichtige jeden Tag einzeln und nicht den Wochendurchschnitt.

Sorge außerdem für Abwechslung über die Woche: verwende ein Gericht für dieselbe Mahlzeit nur mehrfach,
wenn die Auswahl nicht genügend unterschiedliche, passende Alternativen bietet.

Gib AUSSCHLIESSLICH gültiges JSON in genau diesem Format zurück, ohne weiteren Text:
{skeleton}"""

    @staticmethod
    def _extract_json(text: str) -> dict:
        """Parses the JSON object embedded in the AI's response text, tolerating any surrounding
        text (e.g. stray commentary) by slicing from the first '{' to the last '}'."""
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("Keine gültige JSON-Antwort von der KI erhalten.")
        return json.loads(text[start:end + 1])

    def _assemble_plan(
        self,
        weekly_choice: dict,
        participants_per_day: dict[str, dict[str, list]],
        dishes: list[CustomRecipe],
        temperatures: dict[str, float],
    ) -> MealPlan:
        """Turns the AI's raw day/meal -> dish-name choices into a full MealPlan: resolves each
        name back to a dish, scales its recipe to that slot's headcount (reusing an already-scaled
        recipe when the same dish/headcount combination recurs), and aggregates the shopping list
        across every use."""
        dishes_by_name = {dish.name.strip().casefold(): dish for dish in dishes}
        weekly_plan: dict[str, dict[str, str]] = {}
        recipes: dict[str, Recipe] = {}
        recipe_keys_by_dish: dict[str, dict[int, str]] = {}

        usage_counts: dict[str, int] = {}
        for day, meals in weekly_choice.items():
            weekly_plan[day] = {}
            for meal, dish_name in meals.items():
                dish = self._resolve_dish(dish_name, dishes_by_name)
                if dish is None:
                    raise ValueError(
                        f"Die KI hat ein unbekanntes Gericht vorgeschlagen: '{dish_name}'. Bitte den "
                        f"Essensplan erneut erstellen."
                    )
                servings = max(len(participants_per_day.get(day, {}).get(meal, [])), 1)
                key = self._recipe_key_for(dish, servings, recipe_keys_by_dish)
                if key not in recipes:
                    recipes[key] = self._scale_recipe(dish, servings)
                weekly_plan[day][meal] = key
                usage_counts[key] = usage_counts.get(key, 0) + 1

        # Ein Gericht, das mehrmals in der Woche vorkommt, wird auch mehrmals gekocht - die
        # Einkaufsliste braucht daher die Zutaten je Verwendung, nicht nur einmal pro Rezeptname.
        shopping_list = self._aggregate_shopping_list(recipes, usage_counts)
        return MealPlan(weekly_plan=weekly_plan, recipes=recipes, shopping_list=shopping_list, temperatures=temperatures)

    @staticmethod
    def _resolve_dish(dish_name: str, dishes_by_name: dict[str, CustomRecipe]) -> CustomRecipe | None:
        """Looks up a dish the AI returned by name. Falls back to a fuzzy match so a minor typo in
        the AI's response (e.g. a missing letter) doesn't fail the whole plan creation."""
        key = str(dish_name).strip().casefold()
        dish = dishes_by_name.get(key)
        if dish is not None:
            return dish
        close_matches = difflib.get_close_matches(key, dishes_by_name.keys(), n=1, cutoff=0.75)
        return dishes_by_name[close_matches[0]] if close_matches else None

    @staticmethod
    def _recipe_key_for(dish: CustomRecipe, servings: int, seen: dict[str, dict[int, str]]) -> str:
        """Same dish, same servings -> same recipe key. Same dish but a different headcount (used for
        two meals with a different number of participants) gets its own key so both scalings coexist."""
        entry = seen.setdefault(dish.name, {})
        if servings in entry:
            return entry[servings]
        key = dish.name if not entry else f"{dish.name} ({servings} Port.)"
        entry[servings] = key
        return key

    @staticmethod
    def _scale_recipe(dish: CustomRecipe, servings: int) -> Recipe:
        """Turns a dish-database entry into a Recipe scaled to the given number of servings, by
        scaling every ingredient amount by the same factor. Nutrition values are left untouched
        since they're already tracked per portion."""
        factor = servings / dish.servings if dish.servings else 1
        return Recipe(
            name=dish.name,
            servings=servings,
            ingredients=[AIClient._scale_ingredient(i, factor) for i in dish.ingredients],
            instructions=list(dish.instructions),
            nutrition=dish.nutrition,  # values are per portion, so they don't change when scaling servings
            youtube_link=dish.youtube_link,
        )

    @staticmethod
    def _scale_ingredient(ingredient: Ingredient, factor: float) -> Ingredient:
        """Scales a single ingredient's amount by `factor`, left unchanged when the amount has no
        parseable number (e.g. "nach Geschmack") or when scaling would be a no-op (factor 1)."""
        amount = AIClient._parse_amount(ingredient.amount)
        if amount is None or factor == 1:
            return Ingredient(name=ingredient.name, amount=ingredient.amount, unit=ingredient.unit)
        return Ingredient(name=ingredient.name, amount=AIClient._format_amount(amount * factor), unit=ingredient.unit)

    @staticmethod
    def _parse_amount(text: str) -> float | None:
        """Extracts the first number from a free-text amount (accepting both '.' and ',' as the
        decimal separator), or None when the text has no parseable number at all (e.g. "1 Prise",
        "nach Geschmack") - such texts can't be scaled or summed and are kept as-is."""
        match = _AMOUNT_RE.search(text or "")
        if not match:
            return None
        return float(match.group().replace(",", "."))

    @staticmethod
    def _format_amount(value: float) -> str:
        """Formats a scaled/summed amount back to text: rounded to one decimal, without a trailing
        ".0" when the result is a whole number."""
        rounded = round(value, 1)
        return str(int(rounded)) if rounded == int(rounded) else str(rounded)

    _UNIT_CONVERSIONS = {"kg": ("g", 1000), "l": ("ml", 1000)}

    @staticmethod
    def _normalize_unit(amount: float, unit: str) -> tuple[float, str]:
        """Converts kg->g and l->ml so e.g. "0,2 l" and "200 ml" Brühe land in the same shopping-list
        group instead of being listed as two separate entries."""
        conversion = AIClient._UNIT_CONVERSIONS.get(unit.strip().casefold())
        if conversion is None:
            return amount, unit
        new_unit, factor = conversion
        return amount * factor, new_unit

    @staticmethod
    def _aggregate_shopping_list(recipes: dict[str, Recipe], usage_counts: dict[str, int]) -> list[Ingredient]:
        """Sums ingredient amounts across all uses of all recipes in the week (a recipe cooked on
        three different days needs its ingredients three times), grouped by name + unit. Amounts
        without a parseable number (e.g. "1 Prise", "nach Geschmack") are kept as distinct texts
        instead of merged, since they can't be added up meaningfully."""
        groups: dict[tuple[str, str], dict] = {}
        for key, recipe in recipes.items():
            count = usage_counts.get(key, 1)
            for ingredient in recipe.ingredients:
                if not ingredient.name:
                    continue
                amount = AIClient._parse_amount(ingredient.amount)
                unit = ingredient.unit.strip()
                if amount is not None:
                    amount, unit = AIClient._normalize_unit(amount, unit)
                group_key = (ingredient.name.strip().casefold(), unit.casefold())
                group = groups.setdefault(group_key, {
                    "name": ingredient.name, "unit": unit, "total": 0.0, "numeric": True, "texts": [],
                })
                if amount is None:
                    group["numeric"] = False
                    text = f"{count}x {ingredient.amount}".strip() if count > 1 and ingredient.amount else ingredient.amount
                    if text and text not in group["texts"]:
                        group["texts"].append(text)
                else:
                    group["total"] += amount * count

        shopping_list = [
            Ingredient(
                name=group["name"],
                unit=group["unit"],
                amount=AIClient._format_amount(group["total"]) if group["numeric"] else " + ".join(group["texts"]),
            )
            for group in groups.values()
        ]
        return sorted(shopping_list, key=lambda i: i.name.casefold())
