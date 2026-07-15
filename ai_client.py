"""AI API module: creates the weekly plan, recipes and shopping list via the OpenAI API."""
import json
import os
import re

from openai import OpenAI

from models import DEFAULT_MEALS, MealPlan, Household

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


class AIClient:
    def __init__(self, api_key: str | None = None, model: str = "gpt-4o-mini"):
        self.client = OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))
        self.model = model

    def create_meal_plan(self, household: Household, temperatures: dict[str, float]) -> MealPlan:
        prompt = self._build_prompt(household, temperatures)
        response = self.client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Du bist ein Ernährungsassistent und antwortest ausschließlich mit gültigem JSON."},
                {"role": "user", "content": prompt},
            ],
        )
        response_text = response.choices[0].message.content
        data = self._extract_json(response_text)
        plan = MealPlan.from_dict(data)
        plan.temperatures = temperatures
        self._clean_shopping_list(plan)
        self._remove_inactive_meals(plan, household)
        return plan

    @staticmethod
    def _participants_per_meal(household: Household) -> dict[str, list]:
        return {
            meal: [p for p in household.profiles if meal in p.meals]
            for meal in DEFAULT_MEALS
        }

    @staticmethod
    def _build_prompt(household: Household, temperatures: dict[str, float]) -> str:
        temperatures_text = "\n".join(
            f"- {day}: {temperatures.get(day, 'unbekannt')} °C" for day in WEEKDAYS
        )
        participants_per_meal = AIClient._participants_per_meal(household)
        active_meals = [m for m in DEFAULT_MEALS if participants_per_meal[m]]
        inactive_meals = [m for m in DEFAULT_MEALS if not participants_per_meal[m]]

        meal_blocks = []
        for meal in active_meals:
            participants = participants_per_meal[meal]
            allergies = sorted({a for p in participants for a in p.allergies})
            dislikes = sorted({a for p in participants for a in p.dislikes})
            diet_types = sorted({p.diet_type for p in participants if p.diet_type and p.diet_type != "keine"})
            names = ", ".join(p.name for p in participants)
            meal_blocks.append(
                f"- {meal} ({len(participants)} Person(en): {names})\n"
                f"  - Allergien HART meiden (Vereinigung aller Teilnehmer dieser Mahlzeit): {', '.join(allergies) or 'keine'}\n"
                f"  - Diätform-Schnittmenge (muss zu ALLEN hier genannten Diätformen gleichzeitig passen): "
                f"{', '.join(diet_types) or 'keine besonderen'}\n"
                f"  - Abneigungen WENN MÖGLICH meiden (weicher als Allergien, Vereinigung aller Teilnehmer): "
                f"{', '.join(dislikes) or 'keine'}"
            )
        meals_text = "\n".join(meal_blocks)

        omit_note = (
            f"Folgende Mahlzeiten NICHT erstellen, da niemand im Haushalt daran teilnimmt - an KEINEM Tag "
            f"einen Eintrag dafür anlegen: {', '.join(inactive_meals)}."
            if inactive_meals
            else "Alle drei Mahlzeiten (Frühstück, Mittag, Abend) werden für diesen Haushalt erstellt."
        )

        return f"""Erstelle einen gemeinsamen Essensplan für eine Woche ({", ".join(WEEKDAYS)}).

Für jeden Tag werden NUR folgende Mahlzeiten erstellt: {", ".join(active_meals)}.
{omit_note}

Jede Mahlzeit hat ihre EIGENEN Teilnehmer und damit eigene Einschränkungen (nicht alle Personen essen
notwendigerweise jede Mahlzeit mit):
{meals_text}

WICHTIG: Es gibt pro Mahlzeit nur EIN gemeinsames Gericht für alle Teilnehmer dieser Mahlzeit, keine
Ersatzgerichte pro Person. Berücksichtige die Abneigungen aller Teilnehmer über die Woche möglichst
ausgeglichen (nicht nur die einer Person).

Vorhergesagte Höchsttemperatur je Tag:
{temperatures_text}

Wähle das Gericht für JEDEN Tag individuell passend zur Temperatur an GENAU DIESEM Tag
(z.B. an einem warmen Tag mit über 20 °C eher leichte, kalte oder erfrischende Gerichte,
an einem kalten Tag unter 10 °C eher wärmende, deftige Gerichte). Die Temperatur kann von
Tag zu Tag stark schwanken – berücksichtige jeden Tag einzeln und nicht den Wochendurchschnitt.

Erstelle für jedes im Wochenplan verwendete Gericht ein ausführliches Rezept: eine vollständige
Zutatenliste mit Menge und Einheit pro Zutat (z.B. "g", "ml", "Stück", "EL", "TL", "Prise"), eine
ungefähre Zubereitungszeit in Minuten, und mehrere klare, nummerierte Zubereitungsschritte (kein
einzelner Fließtext, mindestens 3 Schritte bei einfachen Gerichten, mehr bei aufwändigeren).
WICHTIG: Die Portionenanzahl eines Rezepts muss GENAU der Personenzahl der Mahlzeit entsprechen, für
die es verwendet wird (siehe Personenzahl je Mahlzeit oben) - nicht die Gesamtgröße des Haushalts.
Falls du dasselbe Gericht für zwei Mahlzeiten mit unterschiedlicher Personenzahl verwenden würdest,
nutze stattdessen unterschiedliche Rezeptnamen.

Erstelle außerdem eine Einkaufsliste für die GESAMTE Woche: summiere die benötigten Mengen aller
Rezepte pro Zutat (jede Zutat nur EINMAL mit der bereits korrekt skalierten Gesamtmenge für die ganze
Woche). WICHTIG: Nimm in die Einkaufsliste AUSSCHLIESSLICH Zutaten auf, die auch tatsächlich unter
"zutaten" in mindestens einem der Rezepte vorkommen (gleicher Name) - keine zusätzlichen, nicht
verwendeten Zutaten. Jede Menge muss eine echte Menge größer als 0 sein; trage niemals "0" oder eine
leere Menge ein.

Die Mengenangaben in der Einkaufsliste müssen praktisch im Supermarkt einkaufbar sein, nicht nur
rechnerisch korrekt:
- Runde Gewicht/Volumen auf gängige Einkaufsgrößen (z.B. 100 g, 250 g, 500 g, 1 kg bzw. 100 ml, 250 ml,
  500 ml, 1 l) statt krummer Werte wie "127 g" oder "340 ml".
- Verwende "Stück" nur für Zutaten, die tatsächlich einzeln gekauft werden (z.B. Zwiebeln, Paprika,
  Äpfel, Zitronen), und wähle dafür eine realistische Anzahl für die Haushaltsgröße und Rezeptanzahl
  - keine unrealistisch hohen Stückzahlen.
- Für Gewürze, Kräuter und andere Kleinmengen reicht eine Packungs- oder Bund-Angabe (z.B. "1 Bund
  Petersilie", "1 Packung Chiliflocken") statt einer errechneten Kleinstmenge.
- Ziel: Der Nutzer soll die Liste direkt im Supermarkt abarbeiten können, ohne selbst umzurechnen.

Gib AUSSCHLIESSLICH gültiges JSON in genau diesem Format zurück, ohne weiteren Text:
{{
  "wochenplan": {{"Montag": {{{", ".join(f'"{m}": "..."' for m in active_meals)}}}, ...}},
  "rezepte": {{
    "Gerichtname": {{
      "portionen": 2,
      "zeit_minuten": 30,
      "zutaten": [{{"name": "Zutat 1", "menge": "400", "einheit": "g"}}, ...],
      "zubereitung": ["Schritt 1 ...", "Schritt 2 ...", "Schritt 3 ..."]
    }}, ...
  }},
  "einkaufsliste": [{{"name": "Zutat 1", "menge": "400", "einheit": "g"}}, ...]
}}"""

    @staticmethod
    def _extract_json(text: str) -> dict:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("Keine gültige JSON-Antwort von der KI erhalten.")
        return json.loads(text[start:end + 1])

    @staticmethod
    def _clean_shopping_list(plan: MealPlan) -> None:
        """Removes shopping list entries that don't appear in any recipe or have no real amount.

        The AI doesn't always follow the prompt instructions (e.g. leftover ingredients with amount
        "0"), so this is additionally enforced here rather than relying on the prompt alone.
        """
        used_names = {
            ingredient.name.strip().casefold()
            for recipe in plan.recipes.values()
            for ingredient in recipe.ingredients
            if ingredient.name
        }
        plan.shopping_list = [
            ingredient for ingredient in plan.shopping_list
            if ingredient.name.strip().casefold() in used_names and AIClient._has_real_amount(ingredient.amount)
        ]

    @staticmethod
    def _remove_inactive_meals(plan: MealPlan, household: Household) -> None:
        """Removes meals from the weekly plan that, according to the profiles, nobody participates in.

        Safety net in case the AI ignores the corresponding instruction in the prompt.
        """
        participants_per_meal = AIClient._participants_per_meal(household)
        inactive_meals = {m for m, participants in participants_per_meal.items() if not participants}
        if not inactive_meals:
            return
        for meals_of_day in plan.weekly_plan.values():
            for meal in inactive_meals:
                meals_of_day.pop(meal, None)

    @staticmethod
    def _has_real_amount(amount: str) -> bool:
        match = re.search(r"\d+[.,]?\d*", amount)
        if not match:
            return True  # e.g. "Prise", "etwas", "nach Geschmack" - no number, but still plausible
        return float(match.group().replace(",", ".")) > 0
