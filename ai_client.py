"""AI API module: the AI picks, per day and meal, a fitting dish from the household's dish database
based on the weather forecast - it no longer invents recipes freely. Scaling ingredients to the
actual number of participants and aggregating the shopping list happens deterministically in Python,
since the dish data (unlike free-form AI output) is already trustworthy and structured."""
import difflib
import json
import math
import os
import random
import re
import time
from datetime import date, timedelta

from openai import OpenAI, RateLimitError

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
        """Sends a prompt with the shared system instructions and returns the parsed JSON response.

        A plan creation makes several of these calls back to back (dish selection, then shopping-
        list consolidation), which can trip the account's tokens-per-minute rate limit even though
        each call individually is small - retries with a short backoff before giving up, since the
        limit is per rolling minute and usually clears within a couple of seconds."""
        last_error = None
        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                )
                return self._extract_json(response.choices[0].message.content)
            except RateLimitError as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
        raise last_error

    def create_meal_plan(
        self, household: Household, temperatures: dict[str, float], dishes: list[CustomRecipe]
    ) -> MealPlan:
        """Builds the weekly meal plan: for each of the next 7 days and each active meal, narrows
        the dish database down to what's actually eligible (correct meal type, no allergens for
        that day's participants), asks the AI to pick one dish per slot from that narrowed list
        based on the weather forecast (favoring dishes marked as favorites, see _build_prompt), and
        assembles the result into a MealPlan with recipes scaled to the day's headcount and an
        aggregated shopping list. _enforce_favorite_limit() hard-caps every favorite to at most one
        appearance across the whole week regardless of what the AI actually returned.

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

        dishes_by_name = {dish.name.strip().casefold(): dish for dish in dishes}
        weekly_choice = self._enforce_favorite_limit(
            data.get("wochenplan", {}), dates_by_weekday, eligible_per_day, dishes_by_name
        )
        return self._assemble_plan(weekly_choice, participants_per_day, dishes, temperatures)

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
                    f'      - "{dish.name}"{" [FAVORIT]" if dish.favorite else ""} (Zutaten: '
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

Mit "[FAVORIT]" markierte Gerichte werden im Haushalt besonders gern gegessen - bevorzuge sie beim
Auswählen deutlich gegenüber nicht markierten Gerichten, sodass sie über die Woche spürbar häufiger
vorkommen als andere Gerichte. Trotzdem darf JEDES favorisierte Gericht in der gesamten Woche
höchstens EIN Mal vorkommen (über alle Tage und Mahlzeiten hinweg), nicht mehrfach.

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

    @staticmethod
    def _enforce_favorite_limit(
        weekly_choice: dict,
        dates_by_weekday: dict[str, date],
        eligible_per_day: dict[str, dict[str, list]],
        dishes_by_name: dict[str, CustomRecipe],
    ) -> dict:
        """Hard-enforces that a favorited dish appears at most once across the whole week - the
        prompt already asks the AI to prefer favorites, but a plan-wide "only once" count isn't
        something an LLM reliably tracks on its own, so it's re-checked deterministically here
        (same reasoning as the allergen filtering happening in Python rather than trusting the AI).

        Walks the days in chronological order (dates_by_weekday, not weekly_choice's own key order,
        which is whatever the AI returned); the first occurrence of a favorite each week is kept,
        any later one is swapped for a random eligible alternative for that exact slot (preferring
        one that isn't itself an already-used favorite). If a slot's eligible list offers no
        alternative at all (e.g. only that one dish fits the meal/day), the repeat is left in place
        rather than breaking the plan - the same "best effort when the dish database is too small"
        fallback the AI is asked to apply to variety in general.
        """
        used_favorite_names: set[str] = set()
        repaired: dict[str, dict[str, str]] = {}
        for day in dates_by_weekday:
            meals = weekly_choice.get(day)
            if not meals:
                continue
            repaired[day] = {}
            for meal, dish_name in meals.items():
                dish = AIClient._resolve_dish(dish_name, dishes_by_name)
                if dish is not None and dish.favorite and dish.name.casefold() in used_favorite_names:
                    alternatives = [
                        d for d in eligible_per_day.get(day, {}).get(meal, [])
                        if d.name.casefold() != dish.name.casefold()
                        and not (d.favorite and d.name.casefold() in used_favorite_names)
                    ]
                    if alternatives:
                        dish = random.choice(alternatives)
                        dish_name = dish.name
                if dish is not None and dish.favorite:
                    used_favorite_names.add(dish.name.casefold())
                repaired[day][meal] = dish_name
        return repaired

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
        # Die Liste bleibt hier bewusst die reine, deterministisch aufsummierte Rohfassung (kann
        # dieselbe Zutat noch mehrfach mit unterschiedlicher Einheit enthalten, z.B. einmal in g,
        # einmal in ml) - das eigentliche Zusammenfassen zu einer sauberen Einkaufsliste passiert
        # erst auf Knopfdruck des Nutzers, siehe generate_shopping_list().
        shopping_list = self._aggregate_shopping_list(recipes, usage_counts)
        return MealPlan(weekly_plan=weekly_plan, recipes=recipes, shopping_list=shopping_list, temperatures=temperatures)

    def generate_shopping_list(self, items: list[Ingredient]) -> list[Ingredient]:
        """Turns the raw, per-recipe aggregated shopping list into the clean list a person would
        actually take to the store - triggered explicitly by the user (via a button) rather than
        automatically on every plan creation, since it's a dedicated AI call of its own.

        Unlike the deterministic aggregation in _aggregate_shopping_list (which can only safely sum
        entries that already share the exact same name and unit), this asks the AI to both decide
        WHICH entries describe the same food (singular/plural, minor wording differences, "X oder
        Y" alternatives, ...) AND settle on ONE final, realistic amount and sensible unit per food -
        including cases the deterministic merge can't resolve on its own, like the same ingredient
        appearing once as a weight (g/kg) and once as a volume (ml/l) across different recipes
        (e.g. "7 g Pfeffer" and "40 ml Pfeffer"), where combining them requires the kind of
        real-world kitchen judgment (typical density, realistic shopping units) that isn't safe to
        hard-code as a conversion table.

        Falls back to the original, merely name-deduplicated list if the AI call fails outright or
        returns something structurally unusable, so a bad AI response never loses items from the
        list - it just leaves it less tidy than intended.
        """
        items = self._merge_exact_name_duplicates(items)
        if len(items) < 2:
            return items

        lines = "\n".join(
            f"{idx}. " + " ".join(part for part in (item.amount, item.unit, item.name) if part)
            for idx, item in enumerate(items)
        )
        prompt = f"""Das ist eine automatisch aus einem Wochen-Essensplan zusammengestellte Einkaufsliste
(Menge, Einheit, Name je Zeile). Weil sie aus vielen einzelnen Rezepten aufsummiert wurde, können
manche Zeilen dasselbe Lebensmittel meinen, aber getrennt gelandet sein - auch mit unterschiedlicher
Einheit (z.B. "7 g Pfeffer" und "40 ml Pfeffer", weil das eine Rezept es gewogen und das andere in
einem Löffelmaß angegeben hat). Erstelle daraus die fertige Einkaufsliste, die ein Mensch tatsächlich
zum Einkaufen mitnehmen würde: jedes Lebensmittel genau EIN Mal, mit EINER sinnvoll gerundeten
Gesamtmenge in einer für den Einkauf passenden Einheit (g/kg für Gewicht, ml/l für Flüssigkeiten,
Stück/Bund/Dose/Zehe/... für Stückzahlen).

Beachte beim Zusammenfassen:
- Singular/Plural gehören zusammen (z.B. "Zwiebel" und "Zwiebeln").
- Rein beschreibende Zusätze, die nur sagen WIE/WOFÜR die Zutat verwendet wird, ändern nicht WAS es
  ist - ignoriere sie beim Gruppieren (z.B. "Honig" und "Honig zum Servieren" gehören zusammen;
  ebenso "frische Petersilie", "Petersilie, gehackt" und "Petersilie").
- Bei "X oder Y" (eine im Rezept genannte Ersatz-/Alternativzutat): wenn X bereits eine eigene
  Position in der Liste ist, gehört "X oder Y" zu X dazu, da der Einkauf von X den Bedarf schon
  deckt (z.B. "Honig" und "Honig oder Ahornsirup" gehören zusammen - zur Gruppe von "Honig").
- Zusammengesetzte Wörter, die dadurch eine ANDERE, eigenständige Zutat bezeichnen, bleiben GETRENNT
  (z.B. "Honig" und "Honigmelone" sind NICHT dasselbe - eine Honigmelone ist eine Melonensorte,
  kein Honig; ebenso "Kokosmilch" gehört NICHT zu "Milch").
- Unterschiedliche Sorten/Varianten bleiben ebenfalls GETRENNT (z.B. "rote Paprika" und "grüne
  Paprika") - im Zweifel lieber getrennt lassen als falsch zusammenzufassen.
- Mengen ohne Zahl (z.B. "nach Geschmack", "1 Prise") lassen sich nicht sinnvoll aufaddieren - so
  eine Zeile bei ihrer Gruppe als eigener, unveränderter Eintrag stehen lassen statt eine Zahl zu
  erfinden.
- JEDE Zeile von 0 bis {len(items) - 1} muss in der Ausgabe wiederzufinden sein (verrechnet in einer
  Gruppe oder als eigener Eintrag) - keine darf verloren gehen oder erfunden werden.

{lines}

Gib AUSSCHLIESSLICH gültiges JSON in genau diesem Format zurück, ohne weiteren Text:
{{"einkaufsliste": [{{"menge": "500", "einheit": "g", "name": "Zwiebeln"}}, {{"menge": "1", "einheit": "Bund", "name": "Petersilie"}}]}}"""

        data = self._ask_json(prompt)
        raw_list = data.get("einkaufsliste")
        if not isinstance(raw_list, list) or not raw_list:
            return items

        result = []
        for entry in raw_list:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", "")).strip()
            if not name:
                continue
            result.append(Ingredient(
                name=name,
                amount=str(entry.get("menge", "")).strip(),
                unit=str(entry.get("einheit", "")).strip(),
            ))
        if not result:
            return items

        # Die KI kann zwei ursprünglich getrennte Gruppen bilden, die zufällig auf denselben Namen
        # UND dieselbe Einheit hinauslaufen - das wird hier noch einmal exakt (nicht KI-basiert)
        # zusammengefasst, sonst stünde derselbe Name/dieselbe Einheit unnötig zweimal da.
        return self._merge_exact_name_and_unit_duplicates(result)

    @staticmethod
    def _merge_exact_name_and_unit_duplicates(items: list[Ingredient]) -> list[Ingredient]:
        """Sums entries that already share the exact same name AND unit into one - safe to always
        do (no unit-conversion guessing involved), used as a final cleanup after AI-driven grouping
        since two independently-decided groups can each leave behind a same-named, same-unit
        leftover (see generate_shopping_list)."""
        by_key: dict[tuple[str, str], list[Ingredient]] = {}
        order: list[tuple[str, str]] = []
        for item in items:
            key = (item.name.strip().casefold(), item.unit.strip().casefold())
            if key not in by_key:
                order.append(key)
            by_key.setdefault(key, []).append(item)

        result: list[Ingredient] = []
        for key in order:
            group = by_key[key]
            if len(group) == 1:
                result.append(group[0])
                continue
            amount = AIClient._parse_amount(group[0].amount)
            if amount is None or any(AIClient._parse_amount(i.amount) is None for i in group):
                result.extend(group)  # nicht-numerische Anteile (z.B. "nach Geschmack") unangetastet lassen
                continue
            total = sum(AIClient._parse_amount(i.amount) for i in group)
            name = min((i.name for i in group if i.name), key=len)
            amount_str, unit = AIClient._round_for_shopping(total, group[0].unit)
            result.append(Ingredient(name=name, amount=amount_str, unit=unit))
        return result

    @staticmethod
    def _merge_exact_name_duplicates(items: list[Ingredient]) -> list[Ingredient]:
        """Merges entries whose name matches exactly (case-insensitively) before the AI grouping
        pass even runs - e.g. "Salz" with no unit and "Salz" in TL only ended up as two entries
        because _aggregate_shopping_list groups by (name, unit), not name alone. This is deliberately
        done with plain string equality (zero AI involvement, always correct) so the common case of
        the exact same ingredient name recurring across recipes never depends on the AI's grouping
        being consistent - it only has to handle genuinely fuzzy cases (singular/plural, wording)."""
        by_name: dict[str, list[Ingredient]] = {}
        order: list[str] = []
        for item in items:
            key = item.name.strip().casefold()
            if key not in by_name:
                order.append(key)
            by_name.setdefault(key, []).append(item)
        result: list[Ingredient] = []
        for key in order:
            group = by_name[key]
            if len(group) == 1:
                result.append(group[0])
            else:
                result.extend(AIClient._merge_ingredient_group(group))
        return result

    @staticmethod
    def _merge_ingredient_group(group_items: list[Ingredient]) -> list[Ingredient]:
        """Deterministically merges a group of Ingredients already judged (by generate_shopping_list)
        to be the same food. Every item is converted to grams and summed into one running total
        whenever that's safely possible - either because it's already a weight (g/kg), or because
        it's a piece/slice count of an ingredient with a known average weight (e.g. "1 Baguette" or
        "2 Scheiben Baguette", see _PIECE_WEIGHTS_G/_SLICE_WEIGHTS_G) - looked up by EACH ITEM'S OWN
        name, not the group's shared display name, since a fuzzy AI grouping can combine differently-
        named items (e.g. "Baguette" and "Brot") that must not borrow each other's piece weight.

        What's left over (a unit this function doesn't know how to turn into grams for that specific
        ingredient, e.g. "1 Dose" or "1 Bund") is kept as its own separate, individually clean entry
        rather than unsafely summed into the weight total or joined into a "125 g + 1 Stück"-style
        formula string - so the final shopping list may occasionally show a food on two lines with
        two different units, but never a mathematical expression as the amount.

        A teaspoon/tablespoon (after el->TL normalization) is handled in two possible ways: for a
        known spoonable solid (butter, sugar, flour, ... see _SPOON_WEIGHTS_G_PER_TL) it converts to
        grams by that food's typical density; otherwise it's treated as a plain volume measure (1 TL
        = 5 ml is a fixed physical fact, not a food-specific guess) and folded into the running
        volume total instead - e.g. "9,4 EL Olivenöl" and "25 ml Olivenöl" both end up in ml.

        The shortest name in the group is used as the display name, as a simple heuristic for the
        least descriptive/most generic phrasing (e.g. "Zwiebeln" over "kleine rote Zwiebel")."""
        name = min((item.name for item in group_items if item.name), key=len, default=group_items[0].name)

        total_g = 0.0
        total_ml = 0.0
        weight_used = False
        volume_used = False
        by_unit: dict[str, dict] = {}
        texts: list[str] = []

        for item in group_items:
            amount = AIClient._parse_amount(item.amount)
            if amount is None:
                text = " ".join(part for part in (item.amount, item.unit) if part)
                if text and text not in texts:
                    texts.append(text)
                continue

            amount, unit = AIClient._normalize_unit(amount, item.unit.strip())
            unit_cf = unit.casefold()

            if unit_cf == "g":
                total_g += amount
                weight_used = True
                continue
            if unit_cf == "ml":
                total_ml += amount
                volume_used = True
                continue

            piece_g = None
            if unit_cf in ("", "stück", "stk", "stueck"):
                piece_g = AIClient._piece_weight_for(item.name, AIClient._PIECE_WEIGHTS_G)
            elif unit_cf in ("scheibe", "scheiben"):
                piece_g = AIClient._piece_weight_for(item.name, AIClient._SLICE_WEIGHTS_G)
            elif unit_cf == "tl":
                piece_g = AIClient._piece_weight_for(item.name, AIClient._SPOON_WEIGHTS_G_PER_TL)
            if piece_g is not None:
                total_g += amount * piece_g
                weight_used = True
                continue

            if unit_cf == "tl" and AIClient._piece_weight_for(item.name, AIClient._LIQUID_NAMES) is not None:
                # Kein bekanntes Gewicht für diese Zutat pro TL, aber eine bekannte Flüssigkeit - ein
                # Teelöffel ist per Definition ein Volumenmaß (1 TL = 5 ml), unabhängig davon, was
                # darin gemessen wird, also anders als eine Gewichtsumrechnung immer exakt und
                # sicher. Bewusst nur für bekannte Flüssigkeiten, nicht generell für jede unbekannte
                # Zutat - "2 TL Reis" als "10 ml Reis" umzudeuten wäre genauso unüblich wie eine Formel.
                total_ml += amount * 5
                volume_used = True
                continue

            sub = by_unit.setdefault(unit_cf, {"unit": unit, "total": 0.0})
            sub["total"] += amount

        # Erst runden, DANN auf 0 prüfen - _round_for_shopping rundet zusätzlich auf einen "runden"
        # Schritt (z.B. 0,3 g -> 0 g bei kleinen Mengen), das muss in die Prüfung einfließen, nicht
        # nur der unrundierte Rohwert. Wenn Gewicht/Volumen (nach dem Runden) 0 ergeben - z.B. nur
        # eine Spur eines Gewürzs über die ganze Woche - lieber die Zutat weglassen als einen
        # irreführenden "0 g"-Eintrag zu zeigen.
        candidates = []
        if weight_used:
            rounded = AIClient._round_for_shopping(total_g, "g")
            if rounded[0] != "0":
                candidates.append(rounded)
        if volume_used:
            rounded = AIClient._round_for_shopping(total_ml, "ml")
            if rounded[0] != "0":
                candidates.append(rounded)
        candidates += [AIClient._round_for_shopping(sub["total"], sub["unit"]) for sub in by_unit.values()]

        if len(candidates) == 1 and not texts:
            amount, unit = candidates[0]
            return [Ingredient(name=name, amount=amount, unit=unit)]

        entries = [Ingredient(name=name, amount=amount, unit=unit) for amount, unit in candidates]
        entries.extend(Ingredient(name=name, amount=text, unit="") for text in texts)
        return entries

    # Durchschnittsgewichte (Gramm) für "Stück"/keine Einheit gängiger Zutaten, damit z.B. "1
    # Zwiebel" und "125 g Zwiebeln" sicher zu EINER Gewichtsangabe zusammengeführt werden können,
    # statt als "1 + 125 g" aneinandergehängt zu werden. Zugeordnet per Wort-Token (siehe
    # _piece_weight_for), nicht per Teilstring-Suche - "Frühlingszwiebeln" ist dadurch ein eigenes
    # Token und trifft nicht versehentlich auf "zwiebeln". Bewusst keine erschöpfende Liste - eine
    # unbekannte Zutat bleibt unangetastet (siehe Fallback in _merge_ingredient_group) statt mit
    # einem erratenen Gewicht verrechnet zu werden.
    _PIECE_WEIGHTS_G = {
        "zwiebel": 125, "zwiebeln": 125, "karotte": 75, "karotten": 75, "kartoffel": 150,
        "kartoffeln": 150, "tomate": 120, "tomaten": 120, "kirschtomate": 18, "kirschtomaten": 18,
        "cherrytomate": 18, "cherrytomaten": 18, "paprika": 150, "gurke": 300, "gurken": 300,
        "zucchini": 200, "aubergine": 250, "auberginen": 250, "apfel": 150, "äpfel": 150,
        "birne": 150, "birnen": 150, "banane": 120, "bananen": 120, "zitrone": 100, "zitronen": 100,
        "limette": 70, "limetten": 70, "avocado": 200, "avocados": 200, "knoblauchzehe": 5,
        "knoblauchzehen": 5, "ei": 60, "eier": 60, "pfirsich": 150, "pfirsiche": 150, "kiwi": 80,
        "baguette": 250, "baguettes": 250, "baguettebrötchen": 80, "ciabatta": 300, "brot": 500,
        "toastbrot": 500, "vollkornbrot": 500, "röstbrot": 500, "weißbrot": 500, "brötchen": 60,
        "fladenbrot": 80, "fladenbrote": 80, "bagel": 90, "bagels": 90, "chili": 10, "chilischote": 10,
        "chilischoten": 10, "frühlingszwiebel": 15, "frühlingszwiebeln": 15, "würstchen": 60,
    }
    _SLICE_WEIGHTS_G = {
        "baguette": 50, "baguettes": 50, "ciabatta": 50, "brot": 30, "toastbrot": 25,
        "vollkornbrot": 30, "röstbrot": 30, "weißbrot": 25,
    }
    # Durchschnittsgewicht (Gramm) PRO TEELÖFFEL für Zutaten, die manchmal gewogen und manchmal
    # gelöffelt werden (z.B. "30 g Butter" in einem Gericht, "1 TL Butter" in einem anderen) - anders
    # als bei Flüssigkeiten (siehe TL->ml-Fallback in _merge_ingredient_group) braucht das hier eine
    # zutatenspezifische Dichte, ist also nur für die paar unten gelisteten Backzutaten hinterlegt.
    _SPOON_WEIGHTS_G_PER_TL = {
        "butter": 5, "zucker": 4, "honig": 7, "mehl": 3, "salz": 6, "pfeffer": 5, "zimt": 3,
        "kakao": 3, "paprikapulver": 3, "senf": 5, "backpulver": 4, "speisestärke": 3,
        "chili": 2, "chiliflocken": 2, "kreuzkümmel": 3, "currypulver": 3, "oregano": 2,
        "thymian": 2, "muskatnuss": 3, "ingwer": 3, "kurkuma": 3,
    }
    # Zutaten, die eindeutig Flüssigkeiten sind - nur für diese wird ein unbekanntes "TL" als
    # Volumenmaß (5 ml) statt als eigene, unangetastete Einheit behandelt (siehe _merge_ingredient_
    # group). Ohne diese Liste würde z.B. "2 TL Reis" fälschlich zu "10 ml Reis" umgedeutet - eine
    # ebenso unübliche Einheit wie eine Formel, nur eben ohne "+".
    _LIQUID_NAMES = {
        "öl": True, "olivenöl": True, "sonnenblumenöl": True, "wasser": True, "essig": True,
        "balsamico": True, "rotweinessig": True, "sahne": True, "milch": True, "kokosmilch": True,
        "buttermilch": True, "wein": True, "rotwein": True, "weißwein": True, "brühe": True,
        "gemüsebrühe": True, "rinderbrühe": True, "hühnerbrühe": True, "fischbrühe": True,
        "saft": True, "zitronensaft": True, "limettensaft": True, "orangensaft": True,
        "sirup": True, "ahornsirup": True, "kokoswasser": True, "sojasauce": True,
    }
    # Zusammengesetzte Namen, die aus mehreren für sich genommen ebenfalls gültigen Token bestehen
    # (z.B. "Baguette oder Bauernbrot") - werden als GANZER Name nachgeschlagen, bevor überhaupt
    # tokenisiert wird, damit nicht zufällig nur eines der beiden Wörter zählt.
    _PIECE_WEIGHT_NAME_OVERRIDES_G = {
        "baguette oder bauernbrot": 400,
        "baguette-ciabatta": 275,
    }

    @staticmethod
    def _piece_weight_for(name: str, table: dict) -> float | None:
        """Looks up a per-piece/slice weight for an ingredient name: first as an exact known
        compound name, then by whole word-token (so "rote Zwiebel" matches via the "zwiebel" token,
        while "Frühlingszwiebeln" - one compound word, no separator - never accidentally matches the
        "zwiebeln" token, since it IS its own distinct token)."""
        normalized = name.strip().casefold()
        if normalized in AIClient._PIECE_WEIGHT_NAME_OVERRIDES_G:
            return AIClient._PIECE_WEIGHT_NAME_OVERRIDES_G[normalized]
        for token in re.split(r"[^a-zäöüß]+", normalized):
            if token in table:
                return table[token]
        return None


    # Einheiten, die nur ganzzahlig gekauft werden können (man kauft keine 0,7 Dosen oder 0,4
    # Zwiebeln) - eine leere Einheit ist hier absichtlich dabei, da eine Mengenangabe ganz ohne
    # Einheit in dieser App durchgängig eine Stückzahl bedeutet (z.B. "1 Ei", "2 Zwiebeln").
    _DISCRETE_UNITS = {
        "", "stück", "stk", "stueck", "dose", "dosen", "päckchen", "paeckchen", "packung",
        "packungen", "glas", "gläser", "glaeser", "bund", "bündel", "buendel", "würfel", "wuerfel",
        "zehe", "zehen", "blatt", "blätter", "blaetter", "scheibe", "scheiben", "kugel", "kugeln",
        "zweig", "zweige", "knolle", "knollen",
    }

    @staticmethod
    def _round_for_shopping(total: float, unit: str) -> tuple[str, str]:
        """Rounds an already correctly summed amount to a number that would realistically appear on
        a shopping list, without ever changing what unit/dimension it's measured in (no g<->ml-style
        guessing - that needs food-specific density knowledge this function deliberately doesn't
        have). Discrete/package units (or no unit at all, which in this app always means a piece
        count) round UP to the next whole number, since you can't buy 0,7 of a can or 0,4 of an
        onion. Continuous measures (g/ml, after kg->g/l->ml normalization) are rounded to a step size
        that grows with the amount (nobody writes "987,5 ml" on a shopping list, they'd write "1 l")
        and switch to the bigger display unit once that rounds up to 1000, for a natural read - same
        as a person rounding while writing their own shopping list by hand."""
        unit_cf = unit.strip().casefold()
        if unit_cf in AIClient._DISCRETE_UNITS:
            return AIClient._format_amount(math.ceil(total - 1e-9)), unit
        if unit_cf in ("g", "ml"):
            total = AIClient._round_to_nice_step(total)
            if total >= 1000:
                return AIClient._format_amount(total / 1000), ("kg" if unit_cf == "g" else "l")
        return AIClient._format_amount(total), unit

    @staticmethod
    def _round_to_nice_step(total: float) -> float:
        """Rounds a weight/volume amount to a step size that grows with its magnitude, so the result
        looks like something a person would actually write by hand (5 g steps for small amounts, 100
        g/ml steps once we're in the hundreds) instead of carrying over exact scaling artifacts like
        "987,5" from combining several recipes' worth of an ingredient."""
        step = 100 if total >= 1000 else 50 if total >= 200 else 5 if total >= 20 else 1
        return round(total / step) * step

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
        parseable number (e.g. "nach Geschmack") or when scaling would be a no-op (factor 1).

        Discrete/package units (see _DISCRETE_UNITS - Dose, Stück, Bund, or no unit at all, which in
        this app always means a piece count) round UP to the next whole number instead of scaling
        linearly: a recipe needing "1 Dose Bohnen" for 4 servings still needs one whole can for 1
        serving, not "0,25 Dose" - a number that's neither buyable nor something a person would ever
        write on a shopping list. This is the actual source of the "0,2 Dosen"-style entries further
        down the pipeline (shopping-list aggregation/merging), not the dish database itself - the
        seeded recipes only ever store whole, realistic amounts like "1 Dose"."""
        amount = AIClient._parse_amount(ingredient.amount)
        if amount is None or factor == 1:
            return Ingredient(name=ingredient.name, amount=ingredient.amount, unit=ingredient.unit)
        scaled = amount * factor
        if ingredient.unit.strip().casefold() in AIClient._DISCRETE_UNITS:
            scaled = math.ceil(scaled - 1e-9)
        return Ingredient(name=ingredient.name, amount=AIClient._format_amount(scaled), unit=ingredient.unit)

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

    # el->TL ist im Gegensatz zu kg/l->g/ml kein reiner Größenordnungswechsel, sondern eine feste
    # Küchen-Umrechnung (1 EL = 3 TL) - genauso sicher/exakt wie die anderen beiden, deshalb hier
    # mit aufgenommen statt nur für g/ml zu normalisieren.
    _UNIT_CONVERSIONS = {"kg": ("g", 1000), "l": ("ml", 1000), "el": ("TL", 3)}

    @staticmethod
    def _normalize_unit(amount: float, unit: str) -> tuple[float, str]:
        """Converts kg->g, l->ml and EL->TL so e.g. "0,2 l" and "200 ml" Brühe, or "1 EL" and "2 TL"
        Zucker, land in the same shopping-list group instead of being listed as two separate
        entries."""
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
