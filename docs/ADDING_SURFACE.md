# Nieuwe A2UI surface toevoegen (voorbeeld)

In deze MVP bestaan de surfaces:
- `home`
- `toeslagen`
- `bezwaar`

Een nieuwe surface toevoegen betekent altijd wijzigingen op 2 plekken:
1) **Web-shell**: tegel + renderfunctie + (optioneel) client-event
2) **Orchestrator**: `nav/open` + (optioneel) flow handler

Onderstaand voorbeeld voegt een nieuwe assistent toe: **“Betaalregeling Assistent”** met surfaceId `betaalregeling`.

---

## Stap A — Web-shell: nieuwe tegel op Home

Bestand: `apps/web-shell/src/shell/bd-app.js`

Zoek in `_renderHome()` de plek waar de twee tegels staan (Toeslagen/Bezwaar) en voeg een derde tegel toe (zelfde card-stijl):

```js
<div class="card tile">
  <div class="card-title">Betaalregeling Assistent</div>
  <div class="tile-icon">€</div>
  <div class="card-sub">Maak een demo-overzicht van opties<br/>voor een betaalregeling.</div>
  <div style="padding-bottom:22px;">
    <button class="btn" @click=${() => this._nav('betaalregeling')}>Start</button>
  </div>
</div>
```

Tip: hou het simpel; je hoeft hier geen nieuw SVG-icoon te introduceren.

---

## Stap B — Web-shell: renderfunctie voor de nieuwe surface

In hetzelfde bestand (`bd-app.js`) voeg je een renderfunctie toe:

```js
_renderBetaalregeling() {
  const loading = !!getByPointer(this.model, '/status/loading');
  const results = (getByPointer(this.model, '/results') || []);

  return html`
    <div class="container">
      <div class="topbar">
        <button class="link" @click=${() => this._nav('home')}>← Terug</button>
        <div class="small-muted">${this.connected ? 'Verbonden' : 'Niet verbonden'}</div>
      </div>

      <div class="card">
        <div class="header" style="height:64px;border-radius:14px 14px 0 0;">
          <div class="header-left">
            <div class="logo">${logoSvg}</div>
            <div style="font-size:26px;font-weight:650;">Betaalregeling Assistent</div>
          </div>
          <div class="hamburger">${menuSvg}</div>
        </div>

        <div class="card-body">
          <div class="form-grid">
            <div>Openstaand bedrag (€):</div>
            <input class="input" id="bedrag" value="1500" />

            <div>Gewenste looptijd (maanden):</div>
            <select class="input" id="looptijd">
              <option>6</option>
              <option>12</option>
              <option>24</option>
            </select>

            <div></div>
            <div style="display:flex;justify-content:flex-end;">
              <button class="btn" style="min-width:160px;" ?disabled=${loading} @click=${this._betaalregelingStart}>
                Bereken
              </button>
            </div>
          </div>

          ${this._renderStatus()}

          <div class="card" style="margin-top:14px;">
            <div class="card-body">
              <div class="section-title">Resultaten</div>
              ${Array.isArray(results) && results.length
                ? html`<ul class="list">${results.map(r => html`<li>${JSON.stringify(r)}</li>`)}</ul>`
                : html`<div class="small-muted">Nog geen resultaten. Klik op “Bereken”.</div>`
              }
            </div>
          </div>
        </div>
      </div>
    </div>
  `;
}
```

En voeg in `render()` de condition toe:

```js
${this.surfaceId === 'betaalregeling' ? this._renderBetaalregeling() : ''}
```

---

## Stap C — Web-shell: client-event sturen

Voeg een handler toe in `bd-app.js`:

```js
_betaalregelingStart() {
  const loading = !!getByPointer(this.model, '/status/loading');
  if (loading) return;

  const bedrag = this.renderRoot.querySelector('#bedrag')?.value || '1500';
  const looptijd = parseInt(this.renderRoot.querySelector('#looptijd')?.value || '12', 10);

  this._sendClientEvent('betaalregeling', 'betaalregeling/bereken', { bedrag, looptijd });
}
```

---

## Stap D — Orchestrator: surface openen via nav/open

Bestand: `apps/orchestrator/main.py`

In `client_event()` bij `if name == "nav/open":` voeg je toe:

```py
elif target == "betaalregeling":
    await _send_open_surface(
        sid,
        "betaalregeling",
        "Betaalregeling Assistent",
        _empty_surface_model("A2UI: Vul bedrag en looptijd in en klik op Bereken."),
    )
```

---

## Stap E — Orchestrator: event handler + demo-flow

In `client_event()` voeg je toe:

```py
if name == "betaalregeling/bereken":
    asyncio.create_task(run_betaalregeling_flow(sid, data))
    return {"ok": True}
```

En implementeer de flow:

```py
async def run_betaalregeling_flow(sid: str, inputs: Json) -> None:
    surface_id = "betaalregeling"

    # Reset surface per run (consistent met de andere flows)
    await _send_open_surface(
        sid,
        surface_id,
        "Betaalregeling Assistent",
        _empty_surface_model("A2UI: Nieuwe berekening gestart…"),
    )
    await _sleep_tick()

    await _set_status(sid, surface_id, loading=True, message="A2UI: Invoer valideren…", step="validate")
    await _sleep_tick()

    bedrag = float(str(inputs.get("bedrag", "1500")).replace(",", "."))
    looptijd = int(inputs.get("looptijd", 12))

    await _set_status(sid, surface_id, loading=True, message="A2UI: Termijnen berekenen…", step="compute")
    await _sleep_tick()

    termijn = round(bedrag / max(looptijd, 1), 2)
    results = [
        {"label": "Bedrag", "value": bedrag},
        {"label": "Looptijd (mnd)", "value": looptijd},
        {"label": "Termijn per maand", "value": termijn},
        {"label": "Opmerking", "value": "Demo-uitkomst (geen besluit)."},
    ]
    await _set_results(sid, surface_id, results)

    await _set_status(sid, surface_id, loading=False, message="A2UI: Klaar. Demo-uitkomst (geen besluit).", step="done")
```

---

## Checklist (zodat je niets vergeet)

- [ ] Web: home tegel toegevoegd met `this._nav('betaalregeling')`
- [ ] Web: `_renderBetaalregeling()` toegevoegd
- [ ] Web: `render()` route voor `surfaceId === 'betaalregeling'`
- [ ] Web: `_betaalregelingStart()` stuurt client-event `betaalregeling/bereken`
- [ ] Orchestrator: `nav/open` ondersteunt `betaalregeling`
- [ ] Orchestrator: `betaalregeling/bereken` handler + flow
- [ ] Progressive updates (minimaal 4 updates met 0.6s delay)
- [ ] Geen persoonsgegevens

---

## Tip: A2UI datamodel-velden die je altijd moet vullen

De UI verwacht deze paden (contract):
- `/status/loading` (bool)
- `/status/message` (string)
- `/status/step` (string)
- `/status/lastRefresh` (string)
- `/results` (list)

---

## Demo talk track (30 sec)

1) Open home → kies “Betaalregeling Assistent”
2) Vul bedrag/looptijd → “Bereken”
3) Laat de status-log zien met prefixes:
   - `A2UI:` stappen
4) Resultaten verschijnen als cards/list
