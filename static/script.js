const WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"];
const MAHLZEITEN_REIHENFOLGE = ["Frühstück", "Mittag", "Abend"];

// Liefert die kommenden 7 Tage ab heute (chronologisch, nicht ab Montag), jeweils mit
// Wochentagsname und Datum (dd.mm.) - der Plan deckt immer die nächsten 7 Tage ab, nicht die
// aktuelle Kalenderwoche, damit z.B. an einem Mittwoch nicht Montag/Dienstag (bereits vergangen)
// angezeigt werden.
function ermittleKommendeWochentage() {
  const heute = new Date();
  const tage = [];
  for (let i = 0; i < 7; i++) {
    const datum = new Date(heute);
    datum.setDate(heute.getDate() + i);
    const wochentagIndex = (datum.getDay() + 6) % 7; // 0 = Montag ... 6 = Sonntag
    tage.push({
      tag: WOCHENTAGE[wochentagIndex],
      datum: datum.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" }),
    });
  }
  return tage;
}

function formatiereZutat(zutat) {
  return [zutat.menge, zutat.einheit, zutat.name].filter(Boolean).join(" ");
}

// Liefert die Rezeptnamen in der Reihenfolge, in der die Gerichte im Wochenplan vorkommen
// (erster Tag Frühstück, erster Tag Mittag, ... letzter Tag Abend, chronologisch ab heute),
// statt alphabetisch.
function sortiereRezepteNachWochenplan(plan, kommendeWochentage) {
  const eintraege = [];
  const gesehen = new Set();

  kommendeWochentage.forEach(({ tag }) => {
    const mahlzeiten = plan.wochenplan[tag] || {};
    MAHLZEITEN_REIHENFOLGE.forEach((mahlzeit) => {
      const gericht = mahlzeiten[mahlzeit];
      if (gericht && (plan.rezepte || {})[gericht] && !gesehen.has(gericht)) {
        gesehen.add(gericht);
        eintraege.push({ name: gericht, tag, mahlzeit });
      }
    });
  });

  // Falls ein Rezept im Wochenplan nicht gefunden wird, trotzdem anzeigen statt zu verschlucken.
  Object.keys(plan.rezepte || {}).forEach((name) => {
    if (!gesehen.has(name)) {
      eintraege.push({ name, tag: null, mahlzeit: null });
    }
  });

  return eintraege;
}

function renderPlan(plan) {
  const grid = document.getElementById("wochenplan-grid");
  const rezepteListe = document.getElementById("rezepte-liste");
  const einkaufsliste = document.getElementById("einkaufsliste");

  grid.innerHTML = "";
  rezepteListe.innerHTML = "";
  einkaufsliste.innerHTML = "";

  if (!plan) {
    grid.innerHTML = '<p class="empty-hint">Noch kein Plan erstellt. Klicke oben auf "Essensplan erstellen".</p>';
    return;
  }

  const kommendeWochentage = ermittleKommendeWochentage();

  kommendeWochentage.forEach(({ tag, datum }) => {
    const mahlzeiten = plan.wochenplan[tag];
    if (!mahlzeiten) return;
    const temperatur = (plan.temperaturen || {})[tag];
    const tagCard = document.createElement("div");
    tagCard.className = "tag-card";
    tagCard.innerHTML =
      `<h3><span class="tag-datum">${datum}</span> ${tag}${temperatur !== undefined ? ` <span class="temp">${temperatur}°C</span>` : ""}</h3>` +
      Object.entries(mahlzeiten)
        .map(([mahlzeit, gericht]) => `<p><strong>${mahlzeit}:</strong> ${gericht}</p>`)
        .join("");
    grid.appendChild(tagCard);
  });

  sortiereRezepteNachWochenplan(plan, kommendeWochentage).forEach(({ name, tag, mahlzeit }) => {
    const rezept = plan.rezepte[name];
    const details = document.createElement("details");
    details.className = "rezept-item";
    const meta = [
      rezept.portionen ? `${rezept.portionen} Portion(en)` : null,
      rezept.zeit_minuten ? `${rezept.zeit_minuten} Min.` : null,
    ].filter(Boolean).join(" · ");
    const zutatenHtml = (rezept.zutaten || [])
      .map((z) => `<li>${formatiereZutat(z)}</li>`)
      .join("");
    const schritteHtml = (rezept.zubereitung || [])
      .map((schritt) => `<li>${schritt}</li>`)
      .join("");
    const tagLabel = tag ? `<span class="rezept-tag">${tag} · ${mahlzeit}</span> ` : "";
    details.innerHTML =
      `<summary>${tagLabel}${name}</summary>` +
      (meta ? `<p class="rezept-meta">${meta}</p>` : "") +
      (zutatenHtml ? `<h4>Zutaten</h4><ul class="rezept-zutaten">${zutatenHtml}</ul>` : "") +
      (schritteHtml ? `<h4>Zubereitung</h4><ol class="rezept-schritte">${schritteHtml}</ol>` : "");
    details.addEventListener("toggle", () => {
      if (!details.open) return;
      rezepteListe.querySelectorAll("details[open]").forEach((offenesDetails) => {
        if (offenesDetails !== details) offenesDetails.open = false;
      });
    });
    rezepteListe.appendChild(details);
  });

  (plan.einkaufsliste || []).forEach((zutat, index) => {
    const li = document.createElement("li");
    li.className = "einkaufsliste-item" + (zutat.abgehakt ? " abgehakt" : "");

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = Boolean(zutat.abgehakt);
    checkbox.addEventListener("change", () => haekeEinkaufslistenPosition(index, checkbox.checked, li, checkbox));

    const text = document.createElement("span");
    text.textContent = formatiereZutat(zutat);

    li.appendChild(checkbox);
    li.appendChild(text);
    einkaufsliste.appendChild(li);
  });
}

// --- Einkaufsliste: Artikel abhaken ---
async function haekeEinkaufslistenPosition(index, abgehakt, li, checkbox) {
  li.classList.toggle("abgehakt", abgehakt);
  try {
    const resp = await fetch(`/api/plan/einkaufsliste/${index}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ abgehakt }),
    });
    if (!resp.ok) throw new Error("Speichern fehlgeschlagen");
  } catch (err) {
    // bei Fehler den vorherigen Zustand wiederherstellen
    li.classList.toggle("abgehakt", !abgehakt);
    checkbox.checked = !abgehakt;
  }
}

// --- Ausklappbares Hamburger-Menü ---
const seitenNav = document.getElementById("side-nav");
const navOverlay = document.getElementById("nav-overlay");
const menuToggle = document.getElementById("menu-toggle");
const navClose = document.getElementById("nav-close");
const navLinks = document.querySelectorAll(".nav-link");
const views = document.querySelectorAll(".view");

function zeigeView(name) {
  views.forEach((view) => {
    view.hidden = view.id !== `view-${name}`;
  });
  navLinks.forEach((link) => {
    link.classList.toggle("active", link.dataset.view === name);
  });
}

function oeffneMenu() {
  seitenNav.classList.add("open");
  navOverlay.classList.add("visible");
  menuToggle.setAttribute("aria-expanded", "true");
}

function schliesseMenu() {
  seitenNav.classList.remove("open");
  navOverlay.classList.remove("visible");
  menuToggle.setAttribute("aria-expanded", "false");
}

menuToggle.addEventListener("click", oeffneMenu);
navClose.addEventListener("click", schliesseMenu);
navOverlay.addEventListener("click", schliesseMenu);

navLinks.forEach((link) => {
  link.addEventListener("click", () => {
    zeigeView(link.dataset.view);
    schliesseMenu();
  });
});

// --- Haushalt: Profil-Karten verwalten ---
const profilListe = document.getElementById("profil-liste");
const profilKarteVorlage = document.getElementById("profil-karte-vorlage");

function aktualisiereEntfernenButtons() {
  const karten = profilListe.querySelectorAll(".profil-karte");
  karten.forEach((karte) => {
    karte.querySelector(".profil-entfernen-btn").disabled = karten.length <= 1;
  });
}

function profilKarteHinzufuegen(profil) {
  const fragment = profilKarteVorlage.content.cloneNode(true);
  const karte = fragment.querySelector(".profil-karte");
  karte.dataset.id = (profil && profil.id) || "";
  karte.querySelector(".profil-name").value = (profil && profil.name) || "";
  karte.querySelector(".profil-abneigungen").value = (profil && profil.abneigungen || []).join(", ");
  karte.querySelector(".profil-allergien").value = (profil && profil.allergien || []).join(", ");
  karte.querySelector(".profil-diaetform").value = (profil && profil.diaetform) || "keine";
  const aktiveMahlzeiten = (profil && profil.mahlzeiten) || ["Frühstück", "Mittag", "Abend"];
  karte.querySelectorAll(".profil-mahlzeit").forEach((checkbox) => {
    checkbox.checked = aktiveMahlzeiten.includes(checkbox.value);
  });
  karte.querySelector(".profil-entfernen-btn").addEventListener("click", () => {
    if (profilListe.querySelectorAll(".profil-karte").length <= 1) return;
    karte.remove();
    aktualisiereEntfernenButtons();
  });
  profilListe.appendChild(fragment);
  aktualisiereEntfernenButtons();
}

function renderHaushalt(haushalt) {
  profilListe.innerHTML = "";
  const profile = (haushalt && haushalt.profile) || [];
  if (profile.length === 0) {
    profilKarteHinzufuegen(null);
  } else {
    profile.forEach((profil) => profilKarteHinzufuegen(profil));
  }
}

document.getElementById("profil-hinzufuegen-btn").addEventListener("click", () => {
  profilKarteHinzufuegen(null);
});

// Fragt die GPS-/WLAN-Position des Geräts über die Browser-Geolocation-API ab. Liefert null statt
// eines Fehlers, wenn der Nutzer die Freigabe ablehnt, die API fehlt, oder die Seite nicht über
// HTTPS/localhost läuft (Browser verlangen dafür einen "sicheren Kontext").
function holeGeraeteStandort() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) {
      resolve(null);
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (position) => resolve({ lat: position.coords.latitude, lon: position.coords.longitude }),
      () => resolve(null),
      { timeout: 8000, maximumAge: 300000 }
    );
  });
}

document.getElementById("ort-erkennen-btn").addEventListener("click", async () => {
  const btn = document.getElementById("ort-erkennen-btn");
  const status = document.getElementById("ort-status");
  btn.disabled = true;
  status.className = "status";
  status.textContent = "Ermittle Standort...";
  try {
    const position = await holeGeraeteStandort();
    const url = position
      ? `/api/standort-erkennen?lat=${position.lat}&lon=${position.lon}`
      : "/api/standort-erkennen";
    const resp = await fetch(url);
    const data = await resp.json();
    if (resp.ok && data.status === "ok") {
      document.getElementById("haushalt-form").ort.value = data.ort;
      status.textContent = `✓ Standort erkannt: ${data.ort}`;
    } else {
      status.textContent = "Fehler: " + data.meldung;
      status.className = "status error";
    }
  } catch (err) {
    status.textContent = "Fehler: " + err.message;
    status.className = "status error";
  } finally {
    btn.disabled = false;
  }
});

document.getElementById("haushalt-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const profile = Array.from(profilListe.querySelectorAll(".profil-karte")).map((karte) => ({
    id: karte.dataset.id || "",
    name: karte.querySelector(".profil-name").value,
    abneigungen: karte.querySelector(".profil-abneigungen").value.split(",").map((s) => s.trim()).filter(Boolean),
    allergien: karte.querySelector(".profil-allergien").value.split(",").map((s) => s.trim()).filter(Boolean),
    diaetform: karte.querySelector(".profil-diaetform").value,
    mahlzeiten: Array.from(karte.querySelectorAll(".profil-mahlzeit:checked")).map((cb) => cb.value),
  }));
  const daten = { ort: form.ort.value, profile };
  const status = document.getElementById("profil-status");
  status.textContent = "Speichere...";
  try {
    const resp = await fetch("/api/haushalt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(daten),
    });
    const data = await resp.json();
    if (resp.ok) {
      status.textContent = "✓ Gespeichert";
      renderHaushalt(data.haushalt);
    } else {
      status.textContent = "Fehler: " + data.meldung;
    }
  } catch (err) {
    status.textContent = "Fehler: " + err.message;
  }
  setTimeout(() => (status.textContent = ""), 2500);
});

// --- Essensplan erstellen ---
document.getElementById("erstellen-btn").addEventListener("click", async () => {
  const btn = document.getElementById("erstellen-btn");
  const status = document.getElementById("erstellen-status");
  btn.disabled = true;
  btn.textContent = "⏳ Erstelle Plan...";
  status.textContent = "Hole Wetterdaten und frage die KI – das kann bis zu 30 Sekunden dauern.";
  status.className = "status";

  try {
    const resp = await fetch("/api/plan/erstellen", { method: "POST" });
    const data = await resp.json();
    if (data.status === "ok") {
      renderPlan(data.plan);
      status.textContent = "✓ Plan erstellt – Gerichte je Tag an die Temperatur angepasst";
      zeigeView("wochenplan");
    } else {
      status.textContent = "Fehler: " + data.meldung;
      status.className = "status error";
    }
  } catch (err) {
    status.textContent = "Fehler: " + err.message;
    status.className = "status error";
  } finally {
    btn.disabled = false;
    btn.textContent = "✨ Essensplan erstellen";
  }
});

renderHaushalt(window.INITIAL_HAUSHALT);
renderPlan(window.INITIAL_PLAN);
