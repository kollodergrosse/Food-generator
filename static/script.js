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

/** Formatiert eine Zutat als "Menge Einheit Name" (fehlende Teile werden ausgelassen). */
function formatiereZutat(zutat) {
  return [zutat.menge, zutat.einheit, zutat.name].filter(Boolean).join(" ");
}

// Rendert die Tags eines Rezepts (z.B. "scharf", "mediterran") als Badge-Liste, oder "" wenn keine vorhanden sind.
function formatiereRezeptTags(tags) {
  if (!tags || !tags.length) return "";
  return `<ul class="rezept-tags">${tags.map((tag) => `<li class="rezept-tag">${tag}</li>`).join("")}</ul>`;
}

// Baut eine <li>-Liste aus Zutaten oder Zubereitungsschritten - identische Logik, nur die
// Formatierungsfunktion je Eintrag unterscheidet sich.
function formatiereListe(eintraege, formatiere) {
  return (eintraege || []).map((eintrag) => `<li>${formatiere(eintrag)}</li>`).join("");
}

// Rendert die Nährwerttabelle eines Rezepts (pro Portion) als HTML, sofern mind. ein Wert > 0 ist.
function formatiereNaehrwerte(naehrwerte) {
  const n = naehrwerte || {};
  const hatWerte = ["kalorien", "eiweiss", "fett", "kohlenhydrate", "salz"].some((k) => Number(n[k]) > 0);
  if (!hatWerte) return "";
  return `<h4>Nährwerte <span class="hint">(ca., pro Portion)</span></h4>
    <ul class="rezept-naehrwerte">
      <li>Kalorien: ${n.kalorien || 0} kcal</li>
      <li>Eiweiß: ${n.eiweiss || 0} g</li>
      <li>Fett: ${n.fett || 0} g<span class="naehrwerte-davon"> (davon gesättigte Fettsäuren: ${n.gesaettigte_fettsaeuren || 0} g)</span></li>
      <li>Kohlenhydrate: ${n.kohlenhydrate || 0} g<span class="naehrwerte-davon"> (davon Zucker: ${n.zucker || 0} g)</span></li>
      <li>Salz: ${n.salz || 0} g</li>
    </ul>`;
}

// Liefert die Mahlzeiten eines Tages in fester Reihenfolge (Frühstück, Mittag, Abend) statt in der
// Reihenfolge, in der die KI sie im JSON zurückgegeben hat.
function mahlzeitenSortiert(mahlzeiten) {
  return MAHLZEITEN_REIHENFOLGE
    .filter((mahlzeit) => mahlzeiten[mahlzeit])
    .map((mahlzeit) => [mahlzeit, mahlzeiten[mahlzeit]]);
}

// Extrahiert die Video-ID aus gängigen YouTube-URL-Formaten (watch?v=, youtu.be/, embed/, shorts/).
// Liefert null, wenn die URL leer ist oder keine erkennbare YouTube-Video-ID enthält.
function extrahiereYoutubeId(url) {
  if (!url) return null;
  const match = url.match(/(?:youtu\.be\/|youtube\.com\/(?:watch\?v=|embed\/|shorts\/))([\w-]{11})/);
  return match ? match[1] : null;
}

// Rendert den Video-Bereich eines Rezepts: eingebettetes YouTube-Video, falls ein gültiger Link
// hinterlegt ist, sonst ein Platzhalter.
function renderRezeptVideo(gericht, youtubeLink) {
  const videoId = extrahiereYoutubeId(youtubeLink);
  if (!videoId) {
    return `<div class="tag-video-platzhalter">🎬 Kein Video hinterlegt</div>`;
  }
  const titel = `Video: ${gericht}`.replace(/"/g, "&quot;");
  return `<div class="tag-video-wrapper">
      <iframe class="tag-video" src="https://www.youtube.com/embed/${videoId}" title="${titel}"
        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
        allowfullscreen loading="lazy"></iframe>
    </div>`;
}

// Rendert das Rezept (Video, Zutaten, Zubereitung, Nährwerte) für eine Mahlzeit eines Tages.
function renderTagRezept(mahlzeit, gericht, rezept) {
  const meta = rezept
    ? [rezept.portionen ? `${rezept.portionen} Portion(en)` : null, rezept.zeit_minuten ? `${rezept.zeit_minuten} Min.` : null]
        .filter(Boolean).join(" · ")
    : "";
  const zutatenHtml = rezept ? formatiereListe(rezept.zutaten, formatiereZutat) : "";
  const schritteHtml = rezept ? formatiereListe(rezept.zubereitung, (schritt) => schritt) : "";
  return `<div class="tag-rezept">
      <h4 class="tag-rezept-titel">${mahlzeit}: ${gericht}</h4>
      ${meta ? `<p class="rezept-meta">${meta}</p>` : ""}
      ${zutatenHtml ? `<h5>Zutaten</h5><ul class="rezept-zutaten">${zutatenHtml}</ul>` : ""}
      ${schritteHtml ? `<h5>Zubereitung</h5><ol class="rezept-schritte">${schritteHtml}</ol>` : ""}
      ${rezept ? formatiereNaehrwerte(rezept.naehrwerte) : ""}
      ${renderRezeptVideo(gericht, rezept && rezept.youtube_link)}
    </div>`;
}

// --- Gemeinsames Detail-Modal (Wochenplan-Tage & Gerichte-Datenbank) ---
const detailModal = document.getElementById("tag-modal");
const detailModalOverlay = document.getElementById("tag-modal-overlay");
const detailModalBody = document.getElementById("tag-modal-body");
const detailModalClose = document.getElementById("tag-modal-close");
let aktiveDetailKarte = null;

/** Schließt das Detail-Modal wieder und entfernt die "aktiv"-Markierung von der auslösenden Karte. */
function schliesseDetailModal() {
  detailModal.classList.remove("visible");
  detailModalOverlay.classList.remove("visible");
  if (aktiveDetailKarte) aktiveDetailKarte.classList.remove("aktiv");
  aktiveDetailKarte = null;
}

/**
 * Öffnet das gemeinsame Detail-Modal mit dem übergebenen HTML-Inhalt und markiert die auslösende
 * Karte als "aktiv", solange das Modal offen ist (für die visuelle Rückmeldung, welche Karte
 * gerade geöffnet ist).
 */
function zeigeDetailModal(inhaltHtml, karte) {
  detailModalBody.innerHTML = inhaltHtml;
  detailModal.classList.add("visible");
  detailModalOverlay.classList.add("visible");
  if (aktiveDetailKarte) aktiveDetailKarte.classList.remove("aktiv");
  aktiveDetailKarte = karte;
  karte.classList.add("aktiv");
  detailModalClose.focus();
}

detailModalClose.addEventListener("click", schliesseDetailModal);
detailModalOverlay.addEventListener("click", schliesseDetailModal);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && detailModal.classList.contains("visible")) schliesseDetailModal();
});

/** Baut die Detailansicht eines Wochenplan-Tages (alle Rezepte des Tages) und zeigt sie im Modal. */
function oeffneTagModal(karte, tag, datum, temperatur, mahlzeitenSort, rezepte) {
  const inhalt =
    `<h3 id="tag-modal-titel" class="tag-modal-titel"><span class="tag-datum">${datum}</span> ${tag}${temperatur !== undefined ? ` <span class="temp">${temperatur}°C</span>` : ""}</h3>
    <div class="tag-rezepte">
      ${mahlzeitenSort.map(([mahlzeit, gericht]) => renderTagRezept(mahlzeit, gericht, (rezepte || {})[gericht])).join("")}
    </div>`;
  zeigeDetailModal(inhalt, karte);
}

/**
 * Rendert den Wochenplan-Grid und die Einkaufsliste neu. Zeigt nur die kommenden 7 Kalendertage
 * (nicht die aktuelle Kalenderwoche) und darin nur die Tage, für die der Plan tatsächlich einen
 * Eintrag hat - Tage ganz ohne Teilnehmer haben keinen Eintrag und werden übersprungen.
 */
function renderPlan(plan) {
  const grid = document.getElementById("wochenplan-grid");

  grid.innerHTML = "";
  schliesseDetailModal();
  renderEinkaufsliste(plan ? plan.einkaufsliste : []);

  if (!plan) {
    grid.innerHTML = '<p class="empty-hint">Noch kein Plan erstellt. Klicke oben auf "Essensplan erstellen".</p>';
    return;
  }

  const kommendeWochentage = ermittleKommendeWochentage();

  kommendeWochentage.forEach(({ tag, datum }) => {
    const mahlzeiten = plan.wochenplan[tag];
    if (!mahlzeiten) return;
    const temperatur = (plan.temperaturen || {})[tag];
    const mahlzeitenSort = mahlzeitenSortiert(mahlzeiten);

    const tagCard = document.createElement("div");
    tagCard.className = "tag-card";
    tagCard.tabIndex = 0;
    tagCard.setAttribute("role", "button");
    tagCard.setAttribute("aria-haspopup", "dialog");
    tagCard.innerHTML =
      `<span class="tag-header"><span class="tag-datum">${datum}</span> ${tag}${temperatur !== undefined ? ` <span class="temp">${temperatur}°C</span>` : ""}</span>
      ${mahlzeitenSort.map(([mahlzeit, gericht]) => `<p><strong>${mahlzeit}:</strong> ${gericht}</p>`).join("")}`;
    const oeffnen = () => oeffneTagModal(tagCard, tag, datum, temperatur, mahlzeitenSort, plan.rezepte);
    tagCard.addEventListener("click", oeffnen);
    tagCard.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      e.preventDefault();
      oeffnen();
    });
    grid.appendChild(tagCard);
  });
}

// --- Einkaufsliste: anzeigen, abhaken, bearbeiten, löschen, frei hinzufügen ---
let aktuelleEinkaufsliste = [];

/** Rendert die Einkaufsliste neu und merkt sie sich in aktuelleEinkaufsliste, damit ein Abbrechen
 * beim Bearbeiten einer Position ohne erneuten Server-Request zur vorherigen Ansicht zurückkann. */
function renderEinkaufsliste(liste) {
  aktuelleEinkaufsliste = liste || [];
  const einkaufsliste = document.getElementById("einkaufsliste");
  einkaufsliste.innerHTML = "";
  aktuelleEinkaufsliste.forEach((zutat, index) => {
    einkaufsliste.appendChild(erzeugeEinkaufslistenEintrag(zutat, index));
  });
}

/** Baut ein einzelnes <li> der Einkaufsliste: Checkbox zum Abhaken, Text, Bearbeiten- und Löschen-Button. */
function erzeugeEinkaufslistenEintrag(zutat, index) {
  const li = document.createElement("li");
  li.className = "einkaufsliste-item" + (zutat.abgehakt ? " abgehakt" : "");

  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = Boolean(zutat.abgehakt);
  checkbox.addEventListener("change", () => haekeEinkaufslistenPosition(index, checkbox.checked, li, checkbox));

  const text = document.createElement("span");
  text.className = "einkaufsliste-text";
  text.textContent = formatiereZutat(zutat);

  const bearbeitenBtn = document.createElement("button");
  bearbeitenBtn.type = "button";
  bearbeitenBtn.className = "einkaufsliste-icon-btn";
  bearbeitenBtn.setAttribute("aria-label", "Artikel bearbeiten");
  bearbeitenBtn.textContent = "✎";
  bearbeitenBtn.addEventListener("click", () => zeigeEinkaufslistenBearbeitenModus(li, zutat, index));

  const loeschenBtn = document.createElement("button");
  loeschenBtn.type = "button";
  loeschenBtn.className = "einkaufsliste-icon-btn";
  loeschenBtn.setAttribute("aria-label", "Artikel löschen");
  loeschenBtn.textContent = "✕";
  loeschenBtn.addEventListener("click", () => loescheEinkaufslistenPosition(index));

  li.appendChild(checkbox);
  li.appendChild(text);
  li.appendChild(bearbeitenBtn);
  li.appendChild(loeschenBtn);
  return li;
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

// --- Einkaufsliste: Artikel bearbeiten ---
function zeigeEinkaufslistenBearbeitenModus(li, zutat, index) {
  const escapeAttr = (wert) => (wert || "").replace(/"/g, "&quot;");
  li.classList.add("bearbeiten-modus");
  li.innerHTML = `
    <input type="text" class="einkaufsliste-bearbeiten-menge" placeholder="Menge" value="${escapeAttr(zutat.menge)}">
    <input type="text" class="einkaufsliste-bearbeiten-einheit" placeholder="Einheit" value="${escapeAttr(zutat.einheit)}">
    <input type="text" class="einkaufsliste-bearbeiten-name" placeholder="Artikel" value="${escapeAttr(zutat.name)}" required>
    <button type="button" class="btn btn-secondary btn-klein einkaufsliste-speichern-btn">Speichern</button>
    <button type="button" class="btn btn-secondary btn-klein einkaufsliste-abbrechen-btn">Abbrechen</button>
  `;
  const nameEingabe = li.querySelector(".einkaufsliste-bearbeiten-name");
  li.querySelector(".einkaufsliste-abbrechen-btn").addEventListener("click", () => renderEinkaufsliste(aktuelleEinkaufsliste));
  li.querySelector(".einkaufsliste-speichern-btn").addEventListener("click", () => speichereEinkaufslistenPosition(index, li));
  nameEingabe.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); speichereEinkaufslistenPosition(index, li); }
    if (e.key === "Escape") renderEinkaufsliste(aktuelleEinkaufsliste);
  });
  nameEingabe.focus();
}

/** Speichert die im Bearbeiten-Modus einer Einkaufslisten-Position eingegebenen Werte per PUT und
 * rendert die Liste bei Erfolg neu; bei einem leeren Namen wird gar nicht erst gespeichert. */
async function speichereEinkaufslistenPosition(index, li) {
  const name = li.querySelector(".einkaufsliste-bearbeiten-name").value.trim();
  if (!name) return;
  const daten = {
    name,
    menge: li.querySelector(".einkaufsliste-bearbeiten-menge").value.trim(),
    einheit: li.querySelector(".einkaufsliste-bearbeiten-einheit").value.trim(),
  };
  try {
    const resp = await fetch(`/api/plan/einkaufsliste/${index}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(daten),
    });
    const data = await resp.json();
    if (resp.ok && data.status === "ok") renderEinkaufsliste(data.einkaufsliste);
  } catch (err) {
    // Bearbeitungszeile bleibt stehen, Nutzer kann es erneut versuchen
  }
}

// --- Einkaufsliste: Artikel löschen ---
async function loescheEinkaufslistenPosition(index) {
  if (!confirm("Diesen Artikel wirklich löschen?")) return;
  try {
    const resp = await fetch(`/api/plan/einkaufsliste/${index}`, { method: "DELETE" });
    const data = await resp.json();
    if (resp.ok && data.status === "ok") renderEinkaufsliste(data.einkaufsliste);
  } catch (err) {
    // Liste bleibt unverändert, Nutzer kann es erneut versuchen
  }
}

// --- Einkaufsliste: neuen, freien Artikel hinzufügen (unabhängig von Gerichten) ---
document.getElementById("einkaufsliste-hinzufuegen-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const name = form.querySelector(".einkaufsliste-neu-name").value.trim();
  if (!name) return;
  const daten = {
    name,
    menge: form.querySelector(".einkaufsliste-neu-menge").value.trim(),
    einheit: form.querySelector(".einkaufsliste-neu-einheit").value.trim(),
  };
  try {
    const resp = await fetch("/api/plan/einkaufsliste", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(daten),
    });
    const data = await resp.json();
    if (resp.ok && data.status === "ok") {
      renderEinkaufsliste(data.einkaufsliste);
      form.reset();
    }
  } catch (err) {
    // Formulareingabe bleibt erhalten, Nutzer kann es erneut versuchen
  }
});

// --- Ansichten wechseln: Start-Kacheln und "Menüauswahl"-Buttons ---
const views = document.querySelectorAll(".view");
const aktionLeiste = document.querySelector(".aktion-leiste");
const ERSTELLEN_BTN_ANSICHTEN = ["nutzerprofil", "wochenplan"];

/** Blendet die Ansicht mit der ID `view-${name}` ein und alle anderen aus; zeigt die
 * "Erstellen"-Aktionsleiste nur in den Ansichten, in denen sie relevant ist. */
function zeigeView(name) {
  views.forEach((view) => {
    view.hidden = view.id !== `view-${name}`;
  });
  aktionLeiste.hidden = !ERSTELLEN_BTN_ANSICHTEN.includes(name);
  // Sprechblasen nur auf der Startseite: beim Verlassen sofort weg (sonst stören sie in anderen
  // Ansichten weiter), beim Betreten sofort wieder mit der ersten Blase nach ca. 1 Sekunde starten.
  if (name === "start") {
    sprechblasenZyklusStarten();
  } else {
    sprechblasenZyklusStoppen();
  }
}

document.querySelectorAll("[data-view]").forEach((el) => {
  el.addEventListener("click", () => zeigeView(el.dataset.view));
});

// --- Haushalt: Profil-Karten verwalten ---
const profilListe = document.getElementById("profil-liste");
const profilKarteVorlage = document.getElementById("profil-karte-vorlage");

/** Deaktiviert den "Entfernen"-Button einer Profil-Karte, solange nur eine einzige Karte übrig ist
 * - ein Haushalt braucht mindestens ein Profil. */
function aktualisiereEntfernenButtons() {
  const karten = profilListe.querySelectorAll(".profil-karte");
  karten.forEach((karte) => {
    karte.querySelector(".profil-entfernen-btn").disabled = karten.length <= 1;
  });
}

// Setzt die Checkboxen einer Mahlzeiten-Tag-Tabelle (Zeile = Mahlzeit, Spalte = Wochentag) anhand
// einer {Wochentag: [Mahlzeit, ...]}-Zuordnung. Ohne Zuordnung (neues Profil) bleiben alle Boxen an.
function setzeMahlzeitenTabelle(karte, selector, mahlzeitenJeTag) {
  karte.querySelectorAll(selector).forEach((checkbox) => {
    checkbox.checked = mahlzeitenJeTag
      ? (mahlzeitenJeTag[checkbox.dataset.tag] || []).includes(checkbox.dataset.mahlzeit)
      : true;
  });
}

// Liest eine Mahlzeiten-Tag-Tabelle wieder aus zu {Wochentag: [Mahlzeit, ...]}, nur mit den
// angehakten Kombinationen (ein Wochentag ohne angehakte Mahlzeit taucht dann gar nicht auf).
function sammleMahlzeitenJeTag(karte, selector) {
  const ergebnis = {};
  karte.querySelectorAll(selector).forEach((checkbox) => {
    if (!checkbox.checked) return;
    const tag = checkbox.dataset.tag;
    (ergebnis[tag] = ergebnis[tag] || []).push(checkbox.dataset.mahlzeit);
  });
  return ergebnis;
}

/** Fügt der Profil-Liste eine neue Karte hinzu, befüllt mit den Werten von `profil` (oder leer/mit
 * Standardwerten, wenn `profil` null ist, also beim Anlegen eines neuen Profils). */
function profilKarteHinzufuegen(profil) {
  const fragment = profilKarteVorlage.content.cloneNode(true);
  const karte = fragment.querySelector(".profil-karte");
  karte.dataset.id = (profil && profil.id) || "";
  karte.querySelector(".profil-name").value = (profil && profil.name) || "";
  karte.querySelector(".profil-vorlieben").value = (profil && profil.vorlieben || []).join(", ");
  karte.querySelector(".profil-abneigungen").value = (profil && profil.abneigungen || []).join(", ");
  karte.querySelector(".profil-allergien").value = (profil && profil.allergien || []).join(", ");
  karte.querySelector(".profil-diaetform").value = (profil && profil.diaetform) || "keine";
  setzeMahlzeitenTabelle(karte, ".profil-mahlzeit-tag", profil && profil.mahlzeiten_je_tag);
  karte.querySelector(".profil-entfernen-btn").addEventListener("click", () => {
    if (profilListe.querySelectorAll(".profil-karte").length <= 1) return;
    karte.remove();
    aktualisiereEntfernenButtons();
  });
  profilListe.appendChild(fragment);
  aktualisiereEntfernenButtons();
}

// --- Haushalt: Besucher-Karten verwalten ---
const besucherListe = document.getElementById("besucher-liste");
const besucherKarteVorlage = document.getElementById("besucher-karte-vorlage");

/** Fügt der Besucher-Liste eine neue Karte hinzu, befüllt mit den Werten von `besucher` (oder
 * leer/mit Standardwerten, wenn `besucher` null ist, also beim Anlegen eines neuen Besuchers). */
function besucherKarteHinzufuegen(besucher) {
  const fragment = besucherKarteVorlage.content.cloneNode(true);
  const karte = fragment.querySelector(".profil-karte");
  karte.dataset.id = (besucher && besucher.id) || "";
  karte.querySelector(".besucher-name").value = (besucher && besucher.name) || "";
  karte.querySelector(".besucher-von").value = (besucher && besucher.von) || "";
  karte.querySelector(".besucher-bis").value = (besucher && besucher.bis) || "";
  karte.querySelector(".besucher-unvertraeglichkeiten").value = (besucher && besucher.unvertraeglichkeiten || []).join(", ");
  karte.querySelector(".besucher-diaetform").value = (besucher && besucher.diaetform) || "keine";
  setzeMahlzeitenTabelle(karte, ".besucher-mahlzeit-tag", besucher && besucher.mahlzeiten_je_tag);
  karte.querySelector(".profil-entfernen-btn").addEventListener("click", () => karte.remove());
  besucherListe.appendChild(fragment);
}

/** Rendert Profil- und Besucherliste komplett neu aus dem Haushalt-Objekt; legt bei einem Haushalt
 * ganz ohne Profile eine leere Profil-Karte an, damit das Formular nie ohne Profil dasteht. */
function renderHaushalt(haushalt) {
  profilListe.innerHTML = "";
  const profile = (haushalt && haushalt.profile) || [];
  if (profile.length === 0) {
    profilKarteHinzufuegen(null);
  } else {
    profile.forEach((profil) => profilKarteHinzufuegen(profil));
  }

  besucherListe.innerHTML = "";
  ((haushalt && haushalt.besucher) || []).forEach((besucher) => besucherKarteHinzufuegen(besucher));
}

document.getElementById("profil-hinzufuegen-btn").addEventListener("click", () => {
  profilKarteHinzufuegen(null);
});

document.getElementById("besucher-hinzufuegen-btn").addEventListener("click", () => {
  besucherKarteHinzufuegen(null);
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
    vorlieben: karte.querySelector(".profil-vorlieben").value.split(",").map((s) => s.trim()).filter(Boolean),
    abneigungen: karte.querySelector(".profil-abneigungen").value.split(",").map((s) => s.trim()).filter(Boolean),
    allergien: karte.querySelector(".profil-allergien").value.split(",").map((s) => s.trim()).filter(Boolean),
    diaetform: karte.querySelector(".profil-diaetform").value,
    mahlzeiten_je_tag: sammleMahlzeitenJeTag(karte, ".profil-mahlzeit-tag"),
  }));
  const besucher = Array.from(besucherListe.querySelectorAll(".profil-karte")).map((karte) => ({
    id: karte.dataset.id || "",
    name: karte.querySelector(".besucher-name").value,
    von: karte.querySelector(".besucher-von").value,
    bis: karte.querySelector(".besucher-bis").value,
    unvertraeglichkeiten: karte.querySelector(".besucher-unvertraeglichkeiten").value.split(",").map((s) => s.trim()).filter(Boolean),
    diaetform: karte.querySelector(".besucher-diaetform").value,
    mahlzeiten_je_tag: sammleMahlzeitenJeTag(karte, ".besucher-mahlzeit-tag"),
  }));
  const daten = { ort: form.ort.value, profile, besucher };
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

// --- Eigene Rezepte: Zutaten-/Schritt-Zeilen verwalten ---
const zutatZeileVorlage = document.getElementById("zutat-zeile-vorlage");
const schrittZeileVorlage = document.getElementById("schritt-zeile-vorlage");
const zutatenContainer = document.getElementById("eigenes-rezept-zutaten");
const schritteContainer = document.getElementById("eigenes-rezept-schritte");

/** Fügt dem Zutaten-Formular des eigenen Rezepts eine neue Zeile hinzu, befüllt mit `zutat` (oder
 * leer, wenn `zutat` null ist). */
function zutatZeileHinzufuegen(zutat) {
  const fragment = zutatZeileVorlage.content.cloneNode(true);
  const zeile = fragment.querySelector(".zutat-zeile");
  zeile.querySelector(".zutat-menge").value = (zutat && zutat.menge) || "";
  zeile.querySelector(".zutat-einheit").value = (zutat && zutat.einheit) || "";
  zeile.querySelector(".zutat-name").value = (zutat && zutat.name) || "";
  zeile.querySelector(".zeile-entfernen-btn").addEventListener("click", () => zeile.remove());
  zutatenContainer.appendChild(fragment);
}

/** Fügt dem Zubereitungs-Formular des eigenen Rezepts eine neue Schritt-Zeile mit `text` hinzu. */
function schrittZeileHinzufuegen(text) {
  const fragment = schrittZeileVorlage.content.cloneNode(true);
  const zeile = fragment.querySelector(".schritt-zeile");
  zeile.querySelector(".schritt-text").value = text || "";
  zeile.querySelector(".zeile-entfernen-btn").addEventListener("click", () => zeile.remove());
  schritteContainer.appendChild(fragment);
}

document.getElementById("zutat-hinzufuegen-btn").addEventListener("click", () => zutatZeileHinzufuegen(null));
document.getElementById("schritt-hinzufuegen-btn").addEventListener("click", () => schrittZeileHinzufuegen(""));

// --- Eigene Rezepte: Formular füllen/zurücksetzen (Anlegen vs. Bearbeiten) ---
const eigenesRezeptForm = document.getElementById("eigenes-rezept-form");
const eigenesRezeptAbbrechenBtn = document.getElementById("eigenes-rezept-abbrechen-btn");
let eigeneRezepte = [];

/** Setzt das Formular für eigene Rezepte auf den Anlegen-Zustand zurück: leere Felder, genau eine
 * leere Zutaten-/Schritt-Zeile, alle Mahlzeiten-Häkchen aus, Abbrechen-Button ausgeblendet. */
function eigenesRezeptFormZuruecksetzen() {
  eigenesRezeptForm.reset();
  eigenesRezeptForm.rezept_id.value = "";
  zutatenContainer.innerHTML = "";
  schritteContainer.innerHTML = "";
  zutatZeileHinzufuegen(null);
  schrittZeileHinzufuegen("");
  eigenesRezeptForm.querySelectorAll(".eigenes-rezept-mahlzeit").forEach((checkbox) => (checkbox.checked = false));
  eigenesRezeptAbbrechenBtn.hidden = true;
}

/** Befüllt das Formular für eigene Rezepte mit einem bestehenden Rezept zum Bearbeiten, wechselt
 * in die Ansicht "Eigene Rezepte" und scrollt zum Formular. */
function eigenesRezeptBearbeiten(rezept) {
  eigenesRezeptForm.rezept_id.value = rezept.id;
  eigenesRezeptForm.rezept_name.value = rezept.name;
  eigenesRezeptForm.portionen.value = rezept.portionen || 1;
  eigenesRezeptForm.youtube_link.value = rezept.youtube_link || "";
  eigenesRezeptForm.tags.value = (rezept.tags || []).join(", ");
  zutatenContainer.innerHTML = "";
  schritteContainer.innerHTML = "";
  (rezept.zutaten && rezept.zutaten.length ? rezept.zutaten : [null]).forEach(zutatZeileHinzufuegen);
  (rezept.zubereitung && rezept.zubereitung.length ? rezept.zubereitung : [""]).forEach(schrittZeileHinzufuegen);
  const mahlzeiten = rezept.mahlzeiten || ["Frühstück", "Mittag", "Abend"];
  eigenesRezeptForm.querySelectorAll(".eigenes-rezept-mahlzeit").forEach((checkbox) => {
    checkbox.checked = mahlzeiten.includes(checkbox.value);
  });
  eigenesRezeptAbbrechenBtn.hidden = false;
  zeigeView("eigene-rezepte");
  eigenesRezeptForm.scrollIntoView({ behavior: "smooth" });
}

eigenesRezeptAbbrechenBtn.addEventListener("click", eigenesRezeptFormZuruecksetzen);

// --- Eigene Rezepte: Detailansicht im selben Modal wie der Wochenplan ---
function oeffneRezeptModal(rezept, karte) {
  const meta = rezept.portionen ? `${rezept.portionen} Portion(en)` : "";
  const mahlzeitenHtml = (rezept.mahlzeiten || []).join(", ");
  const tagsHtml = formatiereRezeptTags(rezept.tags);
  const zutatenHtml = formatiereListe(rezept.zutaten, formatiereZutat);
  const schritteHtml = formatiereListe(rezept.zubereitung, (schritt) => schritt);
  const titel = rezept.name.replace(/"/g, "&quot;");
  const inhalt =
    `<h3 id="tag-modal-titel" class="tag-modal-titel rezept-titel">${titel}</h3>` +
    (meta || mahlzeitenHtml ? `<p class="rezept-meta">${meta}${meta && mahlzeitenHtml ? " · " : ""}${mahlzeitenHtml}</p>` : "") +
    tagsHtml +
    (zutatenHtml ? `<h4>Zutaten</h4><ul class="rezept-zutaten">${zutatenHtml}</ul>` : "") +
    (schritteHtml ? `<h4>Zubereitung</h4><ol class="rezept-schritte">${schritteHtml}</ol>` : "") +
    formatiereNaehrwerte(rezept.naehrwerte) +
    renderRezeptVideo(rezept.name, rezept.youtube_link) +
    `<div class="rezept-aktionen">
       <button type="button" class="btn btn-secondary btn-klein" id="modal-rezept-bearbeiten-btn">Bearbeiten</button>
       <button type="button" class="btn btn-secondary btn-klein" id="modal-rezept-loeschen-btn">Löschen</button>
     </div>`;
  zeigeDetailModal(inhalt, karte);
  document.getElementById("modal-rezept-bearbeiten-btn").addEventListener("click", () => {
    schliesseDetailModal();
    eigenesRezeptBearbeiten(rezept);
  });
  document.getElementById("modal-rezept-loeschen-btn").addEventListener("click", async () => {
    if (!confirm(`"${rezept.name}" wirklich löschen?`)) return;
    const resp = await fetch(`/api/eigene-rezepte/${rezept.id}`, { method: "DELETE" });
    if (resp.ok) {
      schliesseDetailModal();
      renderEigeneRezepte(eigeneRezepte.filter((r) => r.id !== rezept.id));
    }
  });
}

// --- Eigene Rezepte: Liste anzeigen ---
function renderEigeneRezepte(liste) {
  eigeneRezepte = liste || [];
  const container = document.getElementById("eigene-rezepte-liste");
  container.innerHTML = "";

  if (eigeneRezepte.length === 0) {
    container.innerHTML = '<p class="empty-hint">Noch keine eigenen Rezepte hinterlegt.</p>';
    return;
  }

  eigeneRezepte.forEach((rezept) => {
    const karte = document.createElement("div");
    karte.className = "rezept-item";
    karte.tabIndex = 0;
    karte.setAttribute("role", "button");
    karte.setAttribute("aria-haspopup", "dialog");
    const meta = rezept.portionen ? `${rezept.portionen} Portion(en)` : "";
    const mahlzeitenHtml = (rezept.mahlzeiten || []).join(", ");
    karte.innerHTML =
      `<span class="rezept-item-titel">${rezept.name}</span>` +
      (meta || mahlzeitenHtml ? `<p class="rezept-meta">${meta}${meta && mahlzeitenHtml ? " · " : ""}${mahlzeitenHtml}</p>` : "") +
      formatiereRezeptTags(rezept.tags);
    const oeffnen = () => oeffneRezeptModal(rezept, karte);
    karte.addEventListener("click", oeffnen);
    karte.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      e.preventDefault();
      oeffnen();
    });
    container.appendChild(karte);
  });
}

// --- Eigene Rezepte: Speichern ---
eigenesRezeptForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const zutaten = Array.from(zutatenContainer.querySelectorAll(".zutat-zeile"))
    .map((zeile) => ({
      menge: zeile.querySelector(".zutat-menge").value.trim(),
      einheit: zeile.querySelector(".zutat-einheit").value.trim(),
      name: zeile.querySelector(".zutat-name").value.trim(),
    }))
    .filter((z) => z.name);
  const zubereitung = Array.from(schritteContainer.querySelectorAll(".schritt-text"))
    .map((eingabe) => eingabe.value.trim())
    .filter(Boolean);

  const daten = {
    id: form.rezept_id.value,
    name: form.rezept_name.value,
    portionen: Number(form.portionen.value) || 1,
    mahlzeiten: Array.from(form.querySelectorAll(".eigenes-rezept-mahlzeit:checked")).map((cb) => cb.value),
    youtube_link: form.youtube_link.value.trim(),
    tags: form.tags.value.split(",").map((tag) => tag.trim()).filter(Boolean),
    zutaten,
    zubereitung,
  };

  const status = document.getElementById("eigenes-rezept-status");
  status.textContent = "Speichere und schätze Nährwerte...";
  try {
    const resp = await fetch("/api/eigene-rezepte", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(daten),
    });
    const data = await resp.json();
    if (resp.ok && data.status === "ok") {
      status.textContent = "✓ Gespeichert";
      const rest = eigeneRezepte.filter((r) => r.id !== data.rezept.id);
      renderEigeneRezepte([...rest, data.rezept].sort((a, b) => a.name.localeCompare(b.name, "de")));
      eigenesRezeptFormZuruecksetzen();
    } else {
      status.textContent = "Fehler: " + data.meldung;
      status.className = "status error";
    }
  } catch (err) {
    status.textContent = "Fehler: " + err.message;
    status.className = "status error";
  }
  setTimeout(() => { status.textContent = ""; status.className = "status"; }, 2500);
});

eigenesRezeptFormZuruecksetzen();

renderHaushalt(window.INITIAL_HAUSHALT);
renderPlan(window.INITIAL_PLAN);
renderEigeneRezepte(window.INITIAL_EIGENE_REZEPTE);

// --- Hintergrund: Leuchtblasen driften beim Scrollen mit (Parallax, je Blase eigenes Tempo) ---
const leuchtblasen = Array.from(document.querySelectorAll(".blob"));
if (leuchtblasen.length && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
  let scrollTick = false;
  const aktualisierePosition = () => {
    scrollTick = false;
    const y = window.scrollY;
    leuchtblasen.forEach((blase) => {
      const tempo = parseFloat(blase.dataset.speed);
      blase.style.transform = `translateY(${-y * tempo}px)`;
    });
  };
  window.addEventListener("scroll", () => {
    if (scrollTick) return;
    scrollTick = true;
    requestAnimationFrame(aktualisierePosition);
  });
  aktualisierePosition();
}

// --- Startseite: "Was essen wir heute?"-Sprechblasen ---
// Poppen in zufälligen Abständen an einer zufälligen, kollisionsfreien Stelle auf der Startseite
// auf - nie über dem Header oder dem Kachel-Menü, da diese Bereiche als Ausschlusszonen gelten.
const SPRECHBLASEN_TEXTE = [
  "Was essen wir heute?",
  "Hast du dir schon was fürs Abendessen überlegt?",
  "Worauf hast du gerade Hunger?",
  "Schon eine Idee fürs Mittagessen?",
  "Zeit für einen neuen Wochenplan?",
  "Suppe, Salat oder doch was Deftiges?",
  "Was gibt's denn heute Leckeres?",
  "Kochst du heute oder wird bestellt?",
  "Was steht heute auf dem Speiseplan?",
  "Ich hab Hunger... du auch?",
];

const sprechblasenLayer = document.getElementById("sprechblasen-layer");
const sprechblasenReduziert = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Liefert die Bereiche auf der Startseite, in denen keine Sprechblase erscheinen darf: Header und
 * Kachel-Menü (jeweils mit etwas Rand), damit Sprechblasen das Menü nie verdecken, sowie alle
 * gerade schon sichtbaren Sprechblasen, damit sich bei kurzen Abständen mehrere gleichzeitig
 * sichtbare Blasen nicht gegenseitig überlappen. */
function sprechblasenAusschlussbereiche() {
  const rand = 16;
  const fixeBereiche = [document.querySelector(".app-header"), document.querySelector(".start-grid")]
    .filter(Boolean)
    .map((el) => {
      const r = el.getBoundingClientRect();
      return { left: r.left - rand, top: r.top - rand, right: r.right + rand, bottom: r.bottom + rand };
    });
  const bestehendeBlasen = Array.from(document.querySelectorAll(".sprechblase")).map((el) => {
    const r = el.getBoundingClientRect();
    return { left: r.left - 8, top: r.top - 8, right: r.right + 8, bottom: r.bottom + 8 };
  });
  return fixeBereiche.concat(bestehendeBlasen);
}

function sprechblasenUeberschneidetSich(box, bereiche) {
  return bereiche.some(
    (b) => box.left < b.right && box.right > b.left && box.top < b.bottom && box.bottom > b.top
  );
}

/** Sucht eine zufällige Position im sichtbaren Viewport für eine Sprechblase gegebener Größe, die
 * sich mit keinem Ausschlussbereich überschneidet. Gibt null zurück, wenn nach mehreren Versuchen
 * keine passt (z.B. sehr kleines Fenster) - dann wird diese Runde einfach ausgelassen. */
function findeSprechblasenPosition(breite, hoehe) {
  const bereiche = sprechblasenAusschlussbereiche();
  const rand = 12;
  const maxX = window.innerWidth - breite - rand;
  const maxY = window.innerHeight - hoehe - rand;
  if (maxX <= rand || maxY <= rand) return null;

  for (let versuch = 0; versuch < 40; versuch++) {
    const x = rand + Math.random() * (maxX - rand);
    const y = rand + Math.random() * (maxY - rand);
    const box = { left: x, top: y, right: x + breite, bottom: y + hoehe };
    if (!sprechblasenUeberschneidetSich(box, bereiche)) return { x, y };
  }
  return null;
}

/** Zeigt eine Sprechblase mit zufälligem Text an einer zufälligen, kollisionsfreien Position an
 * (nur wenn die Startseite gerade sichtbar ist) und entfernt sie nach ein paar Sekunden wieder. */
function zeigeSprechblase() {
  const startView = document.getElementById("view-start");
  if (!startView || startView.hidden) return;

  const breite = 220;
  const hoehe = 90;
  const position = findeSprechblasenPosition(breite, hoehe);
  if (!position) return;

  const blase = document.createElement("div");
  blase.className = "sprechblase";
  blase.style.left = `${position.x}px`;
  blase.style.top = `${position.y}px`;
  blase.style.maxWidth = `${breite}px`;
  blase.textContent = SPRECHBLASEN_TEXTE[Math.floor(Math.random() * SPRECHBLASEN_TEXTE.length)];
  sprechblasenLayer.appendChild(blase);

  requestAnimationFrame(() => blase.classList.add("sichtbar"));

  setTimeout(() => {
    blase.classList.remove("sichtbar");
    blase.classList.add("verschwindet");
    setTimeout(() => blase.remove(), sprechblasenReduziert ? 0 : 700);
  }, 4500);
}

let sprechblasenTimeoutId = null;

/** Plant die nächste Sprechblase nach `verzoegerung` ms und hängt sich danach selbst mit einem
 * neuen kurzen, zufälligen Abstand (2-4.5 Sekunden) wieder ein - lässt sich per
 * sprechblasenZyklusStoppen() jederzeit abbrechen (z.B. beim Verlassen der Startseite). Da eine
 * Blase länger sichtbar bleibt (~5s) als dieser Abstand, sind dadurch bewusst öfter mehrere Blasen
 * gleichzeitig zu sehen. */
function sprechblasenNaechsteRunde(verzoegerung) {
  sprechblasenTimeoutId = setTimeout(() => {
    zeigeSprechblase();
    sprechblasenNaechsteRunde(2000 + Math.random() * 2500);
  }, verzoegerung);
}

/** Startet den Sprechblasen-Zyklus (neu) - die erste Blase erscheint bewusst schon nach ca. 1
 * Sekunde, statt auf den ersten normalen (längeren) Zufallsabstand zu warten, damit beim Aufrufen
 * der Startseite gleich etwas passiert. Bricht einen eventuell noch laufenden Zyklus vorher ab,
 * damit nicht mehrere Zyklen parallel Blasen erzeugen. */
function sprechblasenZyklusStarten() {
  if (!sprechblasenLayer || sprechblasenTimeoutId !== null) return;
  sprechblasenNaechsteRunde(1000);
}

/** Stoppt den Sprechblasen-Zyklus und entfernt sofort alle gerade sichtbaren Blasen - verhindert,
 * dass eine Blase beim Verlassen der Startseite in einer anderen Ansicht stehen bleibt. */
function sprechblasenZyklusStoppen() {
  if (sprechblasenTimeoutId !== null) {
    clearTimeout(sprechblasenTimeoutId);
    sprechblasenTimeoutId = null;
  }
  document.querySelectorAll(".sprechblase").forEach((blase) => blase.remove());
}

sprechblasenZyklusStarten();
