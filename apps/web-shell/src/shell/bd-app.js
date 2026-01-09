import { LitElement, html } from 'lit';
import { applyPatches, getByPointer } from './jsonpatch.js';
import { clipboardIconSvg, pencilIconSvg, logoSvg, listIconSvg, menuSvg } from './icons.js';

const ORCH_BASE = 'http://localhost:10002';

export class BdApp extends LitElement {
  static properties = {
    sessionId: { type: String },
    surfaceId: { type: String },
    title: { type: String },
    model: { type: Object },
    connected: { type: Boolean },
  };

  constructor() {
    super();
    this.sessionId = '';
    this.surfaceId = 'home';
    this.title = 'Belastingdienst Assistants';
    this.model = { status: { loading: false, message: '', step: '', lastRefresh: '' }, results: [] };
    this.connected = false;
    this._es = null;
  }

  createRenderRoot() { return this; } // use global CSS

  connectedCallback() {
    super.connectedCallback();
    this._connectSSE();
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    if (this._es) this._es.close();
  }

  _connectSSE() {
    this._es = new EventSource(`${ORCH_BASE}/events`);
    this._es.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        this._handleA2UI(msg);
      } catch (e) {
        console.warn('Bad message', e);
      }
    };
    this._es.onerror = () => {
      this.connected = false;
      this.requestUpdate();
    };
    this._es.onopen = () => {
      this.connected = true;
      this.requestUpdate();
    };
  }

  _handleA2UI(msg) {
    if (msg.kind === 'session/created') {
      this.sessionId = msg.sessionId;
      return;
    }
    if (msg.kind === 'surface/open') {
      this.surfaceId = msg.surfaceId;
      this.title = msg.title || this.title;
      this.model = msg.dataModel || this.model;
      this.requestUpdate();
      return;
    }
    if (msg.kind === 'dataModelUpdate') {
      if (msg.surfaceId !== this.surfaceId) {
        // We keep it simple: only apply to active surface
        return;
      }
      this.model = applyPatches(structuredClone(this.model), msg.patches || []);
      this.requestUpdate();
      return;
    }
  }

  async _sendClientEvent(surfaceId, name, payload) {
    if (!this.sessionId) return;
    await fetch(`${ORCH_BASE}/api/client-event`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sessionId: this.sessionId, surfaceId, name, payload }),
    });
  }

  _nav(surfaceId) {
    this._sendClientEvent(this.surfaceId, 'nav/open', { surfaceId });
  }

  _renderHeader() {
    return html`
      <div class="header">
        <div class="header-left">
          <div class="logo" aria-hidden="true">${logoSvg}</div>
          <div class="brand">Belastingdienst</div>
        </div>
        <div class="hamburger" title="Menu" aria-hidden="true">${menuSvg}</div>
      </div>
    `;
  }

  _renderHome() {
    return html`
      <div class="container">
        <div class="h1">Welkom! Kies een assistent:</div>
        <div class="grid-2">
          <div class="card tile">
            <div class="card-title">Toeslagen Check</div>
            <div class="tile-icon">${clipboardIconSvg}</div>
            <div class="card-sub">Controleer voorwaarden en benodigde<br/>documenten voor uw toeslagaanvraag.</div>
            <div style="padding-bottom:22px;">
              <button class="btn" @click=${() => this._nav('toeslagen')}>Start</button>
            </div>
          </div>

          <div class="card tile">
            <div class="card-title">Bezwaar Assistent</div>
            <div class="tile-icon">${pencilIconSvg}</div>
            <div class="card-sub">Verwerk een bezwaarbrief en genereer een<br/>concept reactie.</div>
            <div style="padding-bottom:22px;">
              <button class="btn" @click=${() => this._nav('bezwaar')}>Start</button>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _renderStatus() {
    const loading = !!getByPointer(this.model, '/status/loading');
    const message = getByPointer(this.model, '/status/message') || '';
    const step = getByPointer(this.model, '/status/step') || '';
    const last = getByPointer(this.model, '/status/lastRefresh') || '';
    return html`
      <div class="status">
        <div class="status-dot" style=${loading ? '' : 'background:#9ca3af; box-shadow:0 0 0 3px rgba(156,163,175,0.2);'}></div>
        <div>
          <div><span class="pill">${loading ? 'Bezig' : 'Status'}</span> ${message}</div>
          <div class="small-muted">Step: ${step} · ${last}</div>
        </div>
      </div>
    `;
  }

  _renderToeslagen() {
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
              <div style="font-size:26px;font-weight:650;">Toeslagen Check</div>
            </div>
            <div class="hamburger">${menuSvg}</div>
          </div>

          <div class="card-body">
            <div class="form-grid">
              <div>Regeling:</div>
              <select class="input" id="regeling">
                <option>Huurtoeslag</option>
                <option>Zorgtoeslag</option>
              </select>

              <div>Jaar:</div>
              <select class="input" id="jaar">
                <option>2024</option>
                <option>2023</option>
              </select>

              <div>Gezinssituatie:</div>
              <select class="input" id="situatie">
                <option>Alleenstaand</option>
                <option>Samenwonend</option>
              </select>

              <div style="display:flex;align-items:center;gap:10px;">
                <input type="checkbox" id="lov" checked />
                <div>Loon of vermogen:</div>
              </div>
              <div style="display:flex;justify-content:flex-end;">
                <button class="btn" style="min-width:140px;" ?disabled=${loading} @click=${this._toeslagenCheck}>Check</button>
              </div>
            </div>

            ${this._renderStatus()}

            <div class="row" style="gap:18px;">
              <div style="flex:1;">
                ${this._renderToeslagenResults(results)}
              </div>
            </div>

            <div class="status" style="margin-top:18px;">
              <div class="status-dot"></div>
              <div><b>Tip:</b> Zorg dat u al uw documenten op tijd aanlevert!</div>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _renderToeslagenResults(results) {
    const sections = Array.isArray(results) ? results : [];
    const byKind = (k) => sections.filter(s => s.kind === k).slice(-1)[0];
    const docs = byKind('documenten');
    const risks = byKind('aandachtspunten');
    const enrich = byKind('verrijking');

    return html`
      ${docs ? html`
        <div class="card" style="margin-top:10px;">
          <div class="card-body">
            <div class="section-title">Benodigde Documenten</div>
            <ul class="list">
              ${(docs.items || []).map(x => html`<li>${x}</li>`)}
            </ul>
          </div>
        </div>
      `: ''}

      ${risks ? html`
        <div class="card" style="margin-top:14px;">
          <div class="card-body">
            <div class="section-title">Aandachtspunten</div>
            <ul class="list">
              ${(risks.items || []).map(x => html`<li>${x}</li>`)}
            </ul>
          </div>
        </div>
      `: ''}

      ${enrich ? html`
        <div class="card" style="margin-top:14px;">
          <div class="card-body">
            <div class="section-title">Verrijking (B1 + prioriteit)</div>
            <div class="small-muted" style="margin-bottom:8px;">Deze verrijking komt van de A2A toeslagen-agent (demo).</div>
            <div style="display:grid;gap:10px;">
              ${(enrich.items || []).slice(0, 8).map(it => html`
                <div class="quote">
                  <div style="display:flex;justify-content:space-between;gap:10px;">
                    <div><b>${it.category}</b>: ${it.text}</div>
                    <div class="pill">${it.priority}</div>
                  </div>
                  <div class="small-muted" style="margin-top:6px;">${it.b1_explanation}</div>
                </div>
              `)}
            </div>
          </div>
        </div>
      `: ''}
    `;
  }

  _toeslagenCheck() {
    const regeling = this.renderRoot.querySelector('#regeling')?.value || 'Huurtoeslag';
    const jaar = parseInt(this.renderRoot.querySelector('#jaar')?.value || '2024', 10);
    const situatie = this.renderRoot.querySelector('#situatie')?.value || 'Alleenstaand';
    const lov = this.renderRoot.querySelector('#lov')?.checked ?? true;

    this._sendClientEvent('toeslagen', 'toeslagen/check', {
      regeling, jaar, situatie, loonOfVermogen: lov
    });
  }

  _renderBezwaar() {
    const loading = !!getByPointer(this.model, '/status/loading');
    const results = (getByPointer(this.model, '/results') || []);
    const r0 = Array.isArray(results) && results.length ? results[0] : null;
    const overview = r0?.overview || {};
    const keyPoints = r0?.key_points || [];
    const actions = r0?.actions || [];
    const draft = r0?.draft_response || '';

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
              <div style="font-size:26px;font-weight:650;">Bezwaar Assistent</div>
            </div>
            <div class="hamburger">${menuSvg}</div>
          </div>

          <div class="card-body">
            <div class="card" style="border-radius:10px;">
              <div class="card-body">
                <div class="section-title" style="margin-top:0;">Ingekomen Bezwaarbrief:</div>
                <div class="form-grid" style="margin-top:6px;">
                  <div><b>Datum:</b></div>
                  <div>${overview.datum || '-'}</div>
                  <div><b>Onderwerp:</b></div>
                  <div>${overview.onderwerp || '-'}</div>
                </div>

                <div class="quote" style="margin-top:12px;">
                  <div class="small-muted" style="margin-bottom:6px;">“</div>
                  <textarea class="input" id="bezwaarText" .value=${this._defaultBezwaarText()} ?disabled=${loading}></textarea>
                </div>

                <div style="display:flex;justify-content:flex-end;margin-top:12px;">
                  <button class="btn" style="min-width:170px;" ?disabled=${loading} @click=${this._bezwaarAnalyse}>Analyseer</button>
                </div>
              </div>
            </div>

            ${this._renderStatus()}

            <div class="tabs">
              <div class="tab">
                <h3>Zaakoverzicht</h3>
                <div><b>Type:</b> ${overview.type || '-'}</div>
                <div style="margin-top:6px;"><b>Reden:</b> ${overview.reden || '-'}</div>
                <div style="margin-top:10px;"><b>Belangstelling:</b> ${overview.bedrag ? 'Bedrag ' + overview.bedrag : 'Inkomensdaling'}</div>
              </div>

              <div class="tab">
                <h3>Belangrijke Punten</h3>
                <ul class="list">
                  ${(keyPoints || []).map(x => html`<li>${x}</li>`)}
                </ul>
              </div>

              <div class="tab">
                <h3>Aanbevolen Acties</h3>
                <ul class="list">
                  ${(actions || []).map(x => html`<li>${x}</li>`)}
                </ul>
              </div>

              <div class="tab">
                <h3>Concept Reactie</h3>
                <div style="white-space:pre-wrap;">${draft || '—'}</div>
                <div class="small-muted" style="margin-top:10px;">Dit is een voorlopige reactie (demo).</div>
              </div>
            </div>

            <div class="status" style="margin-top:14px;">
              <div class="status-dot"></div>
              <div>${loading ? 'Drafting response…' : 'Gereed.'}</div>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _defaultBezwaarText() {
    return "Ik ben het niet eens met de naheffing van €750. Mijn inkomen is te laag voor deze aanslag. Ik vraag om herziening.";
  }

  _bezwaarAnalyse() {
    const text = this.renderRoot.querySelector('#bezwaarText')?.value || this._defaultBezwaarText();
    this._sendClientEvent('bezwaar', 'bezwaar/analyse', { text });
  }

  render() {
    return html`
      <div class="shell">
        ${this._renderHeader()}
        <div class="main">
          ${this.surfaceId === 'home' ? this._renderHome() : ''}
          ${this.surfaceId === 'toeslagen' ? this._renderToeslagen() : ''}
          ${this.surfaceId === 'bezwaar' ? this._renderBezwaar() : ''}
        </div>
      </div>
    `;
  }
}

customElements.define('bd-app', BdApp);
