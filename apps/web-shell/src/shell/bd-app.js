import { LitElement, html } from 'lit';
import { applyPatches, getByPointer } from './jsonpatch.js';
import { clipboardIconSvg, pencilIconSvg, logoSvg, menuSvg } from './icons.js';

const ORCH_BASE = 'http://localhost:10002';

export class BdApp extends LitElement {
  static properties = {
    sessionId: { type: String },
    surfaceId: { type: String },
    title: { type: String },
    model: { type: Object },
    connected: { type: Boolean },
    statusHistory: { type: Array },
    statusCollapsed: { type: Boolean },
  };

  constructor() {
    super();
    this.sessionId = '';
    this.surfaceId = 'home';
    this.title = 'Belastingdienst Assistants';
    this.model = { status: { loading: false, message: '', step: '', lastRefresh: '', source: '', sourceReason: '' }, results: [] };
    this.connected = false;
    this._es = null;

    this.statusHistory = [];
    this.statusCollapsed = false;
  }

  createRenderRoot() { return this; }

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

  _pushStatusHistory(nextModel) {
    const msg = getByPointer(nextModel, '/status/message') || '';
    const step = getByPointer(nextModel, '/status/step') || '';
    const lastRaw = getByPointer(nextModel, '/status/lastRefresh') || '';

    const message = String(msg || '').trim();
    const stepNorm = String(step || '').trim();
    if (!message && !stepNorm) return;

    const ts = this._formatTimestamp(lastRaw) !== '—'
      ? this._formatTimestamp(lastRaw)
      : this._formatTimestamp(new Date().toISOString());

    const lastEntry = this.statusHistory.length ? this.statusHistory[this.statusHistory.length - 1] : null;
    if (lastEntry && lastEntry.message === message && lastEntry.step === stepNorm) return;

    const next = [...this.statusHistory, { ts, message, step: stepNorm }];
    this.statusHistory = next.slice(-6);
  }

  _handleA2UI(msg) {
    if (msg.kind === 'session/created') {
      this.sessionId = msg.sessionId;
      this.statusHistory = [];
      return;
    }
    if (msg.kind === 'surface/open') {
      this.surfaceId = msg.surfaceId;
      this.title = msg.title || this.title;
      this.model = msg.dataModel || this.model;

      // Backward compatible: ensure GenUI source fields exist
      if (!this.model.status) this.model.status = {};
      if (this.model.status.source === undefined) this.model.status.source = '';
      if (this.model.status.sourceReason === undefined) this.model.status.sourceReason = '';

      this.statusHistory = [];
      this._pushStatusHistory(this.model);

      this.requestUpdate();
      return;
    }
    if (msg.kind === 'dataModelUpdate') {
      if (msg.surfaceId !== this.surfaceId) return;

      const nextModel = applyPatches(structuredClone(this.model), msg.patches || []);

      // Backward compatible: ensure GenUI source fields exist
      if (!nextModel.status) nextModel.status = {};
      if (nextModel.status.source === undefined) nextModel.status.source = '';
      if (nextModel.status.sourceReason === undefined) nextModel.status.sourceReason = '';
      this.model = nextModel;
      this._pushStatusHistory(nextModel);

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

  _toggleStatusCollapse() {
    this.statusCollapsed = !this.statusCollapsed;
    this.requestUpdate();
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

          <!-- Idee 1: GenUI Search -->
          <div class="card tile">
            <div class="card-title">Generatieve UI — Zoeken</div>
            <div class="tile-icon">🔎</div>
            <div class="card-sub">Zoek (demo) op onderwerpen en laat<br/>de UI-blokken dynamisch verschijnen.</div>
            <div style="padding-bottom:22px;">
              <button class="btn" @click=${() => this._nav('genui_search')}>Start</button>
            </div>
          </div>


          <!-- Idee 3: Decision Tree Wizard -->
          <div class="card tile">
            <div class="card-title">Generatieve UI — Wizard</div>
            <div class="tile-icon">🧭</div>
            <div class="card-sub">Doorloop een korte beslisboom (demo)<br/>met klikbare keuzes en vervolgstappen.</div>
            <div style="padding-bottom:22px;">
              <button class="btn" @click=${() => this._nav('genui_tree')}>Start</button>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _formatTimestamp(value) {
    if (!value) return '—';
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return String(value);
    const s = d.toLocaleString('nl-NL', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
    return s.replace(',', '');
  }

  _priorityIcon(priority) {
    const p = String(priority || '').toLowerCase();
    if (p.includes('hoog') || p.includes('high')) return '▲';
    if (p.includes('midden') || p.includes('medium')) return '●';
    if (p.includes('laag') || p.includes('low')) return '▼';
    return '•';
  }

  _normalizeText(maybeObjectOrString) {
    if (typeof maybeObjectOrString === 'string') {
      const s = maybeObjectOrString.trim();
      const mText = s.match(/'text'\s*:\s*'([^']+)'/);
      const mCode = s.match(/'code'\s*:\s*'([^']+)'/);
      if (mText) {
        const code = mCode ? mCode[1] : '';
        return code ? `${code} — ${mText[1]}` : mText[1];
      }
      if ((s.startsWith('{') && s.endsWith('}')) && (s.includes('"text"') || s.includes('"code"'))) {
        try {
          const obj = JSON.parse(s);
          if (obj && typeof obj === 'object') {
            const code = obj.code ? String(obj.code) : '';
            const text = obj.text ? String(obj.text) : s;
            return code ? `${code} — ${text}` : text;
          }
        } catch { /* ignore */ }
      }
      return s;
    }

    if (maybeObjectOrString && typeof maybeObjectOrString === 'object') {
      const code = maybeObjectOrString.code ? String(maybeObjectOrString.code) : '';
      const text = maybeObjectOrString.text ? String(maybeObjectOrString.text) : JSON.stringify(maybeObjectOrString);
      return code ? `${code} — ${text}` : text;
    }

    return String(maybeObjectOrString ?? '');
  }

  _draftSourceFromText(draft) {
    const s = String(draft || '');
    if (s.startsWith('[Bron: Gemini]')) return 'gemini';
    if (s.startsWith('[Bron: Fallback]')) return 'fallback';
    return '';
  }

  _stripDraftSourcePrefix(draft) {
    const s = String(draft || '');
    if (s.startsWith('[Bron: Gemini]')) return s.replace('[Bron: Gemini]\n', '').replace('[Bron: Gemini]', '').trim();
    if (s.startsWith('[Bron: Fallback]')) return s.replace('[Bron: Fallback]\n', '').replace('[Bron: Fallback]', '').trim();
    return s;
  }

  _renderStatus() {
    const loading = !!getByPointer(this.model, '/status/loading');
    const message = getByPointer(this.model, '/status/message') || '—';
    const stepRaw = getByPointer(this.model, '/status/step') || '';
    const lastRaw = getByPointer(this.model, '/status/lastRefresh') || '';
    const step = stepRaw || (loading ? 'Bezig…' : '—');
    const last = this._formatTimestamp(lastRaw);

    const toggleLabel = this.statusCollapsed ? 'Uitklappen' : 'Inklappen';
    const toggleIcon = this.statusCollapsed ? '▸' : '▾';

    return html`
      <div class="status">
        <div class="status-dot" style=${loading ? '' : 'background:#9ca3af; box-shadow:0 0 0 3px rgba(156,163,175,0.2);'}></div>
        <div style="width:100%;">
          <div style="display:flex; align-items:center; justify-content:space-between; gap:12px;">
            <div><span class="pill">${loading ? 'Bezig' : 'Status'}</span> ${message}</div>
            <button class="link" style="padding:0; white-space:nowrap;" @click=${this._toggleStatusCollapse} title="${toggleLabel}">
              ${toggleIcon} ${toggleLabel}
            </button>
          </div>

          ${this.statusCollapsed
            ? html`<div class="small-muted" style="margin-top:6px;">${last}</div>`
            : html`
              <div class="small-muted">Step: ${step} · ${last}</div>
              ${this.statusHistory && this.statusHistory.length
                ? html`
                  <div class="small-muted" style="margin-top:8px; display:grid; gap:4px;">
                    ${this.statusHistory.map(h => html`<div>• ${h.ts} — ${h.message}${h.step ? ` (${h.step})` : ''}</div>`)}
                  </div>`
                : ''}
            `}
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
                <option>2025</option>
                <option>2024</option>
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

              <div style="display:flex;justify-content:flex-end; gap:10px;">
                <button class="link" style="padding:0;" ?disabled=${loading} @click=${this._toeslagenReset}>Reset</button>
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
            <ul class="list">${(docs.items || []).map(x => html`<li>${this._normalizeText(x)}</li>`)}</ul>
          </div>
        </div>` : ''}

      ${risks ? html`
        <div class="card" style="margin-top:14px;">
          <div class="card-body">
            <div class="section-title">Aandachtspunten</div>
            <ul class="list">${(risks.items || []).map(x => html`<li>${this._normalizeText(x)}</li>`)}</ul>
          </div>
        </div>` : ''}

      ${enrich ? html`
        <div class="card" style="margin-top:14px;">
          <div class="card-body">
            <div class="section-title">Verrijking (B1 + prioriteit)</div>
            <div class="small-muted" style="margin-bottom:8px;">Deze verrijking komt van de A2A toeslagen-agent (demo).</div>
            <div style="display:grid;gap:10px;">
              ${(enrich.items || []).slice(0, 8).map(it => html`
                <div class="quote">
                  <div style="display:flex;justify-content:space-between;gap:10px;">
                    <div><b>${it.category}</b>: ${this._normalizeText(it.text)}</div>
                    <div class="pill">${this._priorityIcon(it.priority)} ${it.priority}</div>
                  </div>
                  <div class="small-muted" style="margin-top:6px;">${it.b1_explanation}</div>
                </div>
              `)}
            </div>
          </div>
        </div>` : ''}
    `;
  }

  _toeslagenReset() {
    const loading = !!getByPointer(this.model, '/status/loading');
    if (loading) return;

    const regelingEl = this.renderRoot.querySelector('#regeling');
    const jaarEl = this.renderRoot.querySelector('#jaar');
    const situatieEl = this.renderRoot.querySelector('#situatie');
    const lovEl = this.renderRoot.querySelector('#lov');

    if (regelingEl) regelingEl.value = 'Huurtoeslag';
    if (jaarEl) jaarEl.value = '2025';
    if (situatieEl) situatieEl.value = 'Alleenstaand';
    if (lovEl) lovEl.checked = true;
  }

  _toeslagenCheck() {
    const loading = !!getByPointer(this.model, '/status/loading');
    if (loading) return;

    const regeling = this.renderRoot.querySelector('#regeling')?.value || 'Huurtoeslag';
    const jaar = parseInt(this.renderRoot.querySelector('#jaar')?.value || '2025', 10);
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
    const draftRaw = r0?.draft_response || '';

    const draft_source = (r0?.draft_source) || this._draftSourceFromText(draftRaw);
    const draft = this._stripDraftSourcePrefix(draftRaw);

    const badgeLabel = draft_source === 'gemini' ? 'Gemini' : (draft_source === 'fallback' ? 'Fallback' : '');
    const badgeTitle = draft_source === 'gemini'
      ? 'Concepttekst is opgesteld met Gemini'
      : (draft_source === 'fallback' ? 'Concepttekst is opgesteld met fallback' : '');

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

            <div
              class="tabs"
              style="display:grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; align-items: stretch; margin-top: 14px;"
            >
              <div class="tab" style="display:flex; flex-direction:column; height:100%; min-height:240px;">
                <h3 style="margin-top:0;">Zaakoverzicht</h3>
                <div><b>Type:</b> ${overview.type || '-'}</div>
                <div style="margin-top:6px;"><b>Reden:</b> ${overview.reden || '-'}</div>
                <div style="margin-top:10px;"><b>Belangstelling:</b> ${overview.bedrag ? 'Bedrag ' + overview.bedrag : 'Inkomensdaling'}</div>
                <div style="flex:1;"></div>
              </div>

              <div class="tab" style="display:flex; flex-direction:column; height:100%; min-height:240px;">
                <h3 style="margin-top:0;">Belangrijke Punten</h3>
                <ul class="list" style="margin-top:10px; flex:1;">
                  ${(keyPoints || []).map(x => html`<li>${x}</li>`)}
                </ul>
              </div>

              <div class="tab" style="display:flex; flex-direction:column; height:100%; min-height:240px;">
                <h3 style="margin-top:0;">Aanbevolen Acties</h3>
                <ul class="list" style="margin-top:10px; flex:1;">
                  ${(actions || []).map(x => html`<li>${x}</li>`)}
                </ul>
              </div>
            </div>

            <div class="card" style="margin-top:14px;">
              <div class="card-body">
                <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;">
                  <div class="section-title" style="margin-top:0;">Concept Reactie</div>
                  ${badgeLabel ? html`<div class="pill" title="${badgeTitle}">${badgeLabel}</div>` : ''}
                </div>

                <div style="white-space:pre-wrap; margin-top:10px;">${draft || '—'}</div>
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
    const loading = !!getByPointer(this.model, '/status/loading');
    if (loading) return;

    const text = this.renderRoot.querySelector('#bezwaarText')?.value || this._defaultBezwaarText();
    this._sendClientEvent('bezwaar', 'bezwaar/analyse', { text });
  }

  // --- Idee 1: GenUI Search (UI blocks renderer) ---

  _renderBlocks(blocks) {
    const arr = Array.isArray(blocks) ? blocks : [];
    if (!arr.length) {
      return html`<div class="small-muted">Nog geen output. Stel een vraag en klik op “Zoek”.</div>`;
    }

    const renderOne = (b) => {
      if (!b || typeof b !== 'object') return '';
      const kind = b.kind || '';
      if (kind === 'callout') {
        return html`
          <div class="card" style="margin-top:14px;">
            <div class="card-body">
              <div class="section-title" style="margin-top:0;">${b.title || 'Kern'}</div>
              <div style="white-space:pre-wrap;">${b.body || ''}</div>
            </div>
          </div>
        `;
      }
      if (kind === 'citations') {
        const items = Array.isArray(b.items) ? b.items : [];
        return html`
          <div class="card" style="margin-top:14px;">
            <div class="card-body">
              <div class="section-title" style="margin-top:0;">${b.title || 'Bronnen'}</div>
              <div class="small-muted" style="margin-bottom:8px;">Bronnen uit MCP (demo-dataset).</div>
              <ul class="list">
                ${items.map(it => html`
                  <li>
                    <div><a href=${it.url || '#'} target="_blank" rel="noreferrer">${it.title || it.url}</a></div>
                    <div class="small-muted" style="margin-top:4px;">${it.snippet || ''}</div>
                  </li>
                `)}
              </ul>
            </div>
          </div>
        `;
      }
      if (kind === 'accordion') {
        const items = Array.isArray(b.items) ? b.items : [];
        return html`
          <div class="card" style="margin-top:14px;">
            <div class="card-body">
              <div class="section-title" style="margin-top:0;">${b.title || 'Veelgestelde vragen'}</div>
              <div style="display:grid; gap:10px; margin-top:10px;">
                ${items.map(it => html`
                  <details class="quote">
                    <summary style="cursor:pointer;"><b>${it.q || ''}</b></summary>
                    <div class="small-muted" style="margin-top:8px; white-space:pre-wrap;">${it.a || ''}</div>
                  </details>
                `)}
              </div>
            </div>
          </div>
        `;
      }
      if (kind === 'next_questions') {
        const items = Array.isArray(b.items) ? b.items : [];
        return html`
          <div class="card" style="margin-top:14px;">
            <div class="card-body">
              <div class="section-title" style="margin-top:0;">${b.title || 'Vervolgvraag'}</div>
              <div class="small-muted">Klik om direct opnieuw te zoeken.</div>
              <div style="display:flex; flex-wrap:wrap; gap:10px; margin-top:10px;">
                ${items.map(q => html`
                  <button class="pill" style="cursor:pointer;" @click=${() => this._genuiQuickSearch(String(q || ''))}>
                    ${q}
                  </button>
                `)}
              </div>
            </div>
          </div>
        `;
      }
      if (kind === 'decision') {
        const opts = Array.isArray(b.options) ? b.options : [];
        const question = String(b.question || '').trim();
        return html`
          <div class="card" style="margin-top:14px;">
            <div class="card-body">
              <div class="section-title" style="margin-top:0;">${b.title || 'Keuze'}</div>
              <div style="margin-top:6px;"><b>${question}</b></div>
              <div style="display:flex; flex-wrap:wrap; gap:10px; margin-top:10px;">
                ${opts.map(opt => html`
                  <button class="pill" style="cursor:pointer;" @click=${() => this._genuiTreeChoose(String(opt || ''))}>
                    ${opt}
                  </button>
                `)}
              </div>
            </div>
          </div>
        `;
      }
      if (kind === 'notice') {
        return html`
          <div class="status" style="margin-top:14px;">
            <div class="status-dot"></div>
            <div><b>${b.title || 'Let op:'}</b> ${b.body || ''}</div>
          </div>
        `;
      }
      return html`
        <div class="card" style="margin-top:14px;">
          <div class="card-body">
            <div class="section-title" style="margin-top:0;">Onbekend blok</div>
            <pre style="white-space:pre-wrap;">${JSON.stringify(b, null, 2)}</pre>
          </div>
        </div>
      `;
    };

    return html`${arr.map(renderOne)}`;
  }

  _genuiQuickSearch(q) {
    const qq = String(q || '').trim();
    if (!qq) return;

    // Works on genui_search (input exists) and on other surfaces (e.g. genui_tree).
    // We deliberately trigger the orchestrator flow directly to avoid dependence on DOM elements.
    const input = this.renderRoot.querySelector('#genuiQuery');
    if (input) input.value = qq;

    this._sendClientEvent('genui_search', 'genui/search', { query: qq });
  }

  _genuiSearch() {
    const loading = !!getByPointer(this.model, '/status/loading');
    if (loading) return;

    const query = (this.renderRoot.querySelector('#genuiQuery')?.value || '').trim();
    if (!query) return;

    this._sendClientEvent('genui_search', 'genui/search', { query });
  }


  _genuiTreeStart() {
    const loading = !!getByPointer(this.model, '/status/loading');
    if (loading) return;
    this._sendClientEvent('genui_tree', 'genui_tree/start', {});
  }

  _genuiTreeChoose(option) {
    const loading = !!getByPointer(this.model, '/status/loading');
    if (loading) return;
    const opt = String(option || '').trim();
    if (!opt) return;
    this._sendClientEvent('genui_tree', 'genui_tree/choose', { option: opt });
  }

  _humanizeGenuiSourceReason(reasonRaw) {
    const raw = String(reasonRaw || '').trim();
    if (!raw) return { label: '', code: '' };

    const r = raw.toLowerCase();

    // Expected codes from the GenUI agent / orchestrator.
    if (r === 'resource_exhausted' || r.includes('resource_exhausted')) {
      return { code: 'resource_exhausted', label: 'Quota bereikt' };
    }
    if (r === 'http_429' || r.includes('http_429') || r.includes(' 429') || r.endsWith('429') || r.includes('429 too many')) {
      return { code: 'http_429', label: 'Te veel verzoeken (HTTP 429)' };
    }
    if (r === 'bad_json' || r.includes('bad_json') || r.includes('invalid_json') || (r.includes('json') && (r.includes('parse') || r.includes('decode') || r.includes('error')))) {
      return { code: 'bad_json', label: 'Ongeldige JSON-output' };
    }
    if (r === 'a2a_down_or_error' || r.includes('a2a_down_or_error')) {
      return { code: 'a2a_down_or_error', label: 'GenUI-agent niet bereikbaar' };
    }
    if (r === 'deterministic_tree' || r.includes('deterministic_tree')) {
      return { code: 'deterministic_tree', label: 'Deterministische wizard' };
    }

    // Default: show as-is (kept for future reason codes).
    return { code: raw, label: raw };
  }

  _renderGenuiSourcePill() {
    const source = String(getByPointer(this.model, '/status/source') || '').trim().toLowerCase();
    const reasonRaw = String(getByPointer(this.model, '/status/sourceReason') || '').trim();

    if (!source) return '';

    const label = source === 'gemini' ? 'Gemini' : (source === 'fallback' ? 'Fallback' : source.toUpperCase());
    const { label: reasonLabel } = this._humanizeGenuiSourceReason(reasonRaw);
    const reason = String(reasonLabel || '').trim();

    // Tooltip shows the raw code (useful for debugging), pill shows human-friendly text.
    const title = reasonRaw ? `GenUI bron: ${label} · reason=${reasonRaw}` : `GenUI bron: ${label}`;

    return html`
      <div style="display:flex; justify-content:flex-end; margin-top:10px;">
        <div class="pill" title="${title}">GenUI: ${label}${reason ? ` · ${reason}` : ''}</div>
      </div>
    `;
  }

_renderGenuiSearch() {
    const loading = !!getByPointer(this.model, '/status/loading');
    const blocks = (getByPointer(this.model, '/results') || []);

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
              <div style="font-size:26px;font-weight:650;">Generatieve UI — Zoeken</div>
            </div>
            <div class="hamburger">${menuSvg}</div>
          </div>

          <div class="card-body">
            <div class="form-grid">
              <div>Vraag:</div>
              <input class="input" id="genuiQuery" placeholder="Bijv. 'Hoe werkt bezwaar maken?'" />

              <div></div>
              <div style="display:flex; justify-content:flex-end; gap:10px;">
                <button class="btn" style="min-width:140px;" ?disabled=${loading} @click=${this._genuiSearch}>Zoek</button>
              </div>
            </div>

            ${this._renderStatus()}

            ${this._renderGenuiSourcePill()}

            ${this._renderBlocks(blocks)}
          </div>
        </div>
      </div>
    `;
  }

  _renderGenuiTree() {
    const loading = !!getByPointer(this.model, '/status/loading');
    const blocks = (getByPointer(this.model, '/results') || []);
    const hasBlocks = Array.isArray(blocks) && blocks.length;

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
              <div style="font-size:26px;font-weight:650;">Generatieve UI — Wizard</div>
            </div>
            <div class="hamburger">${menuSvg}</div>
          </div>

          <div class="card-body">
            <div style="display:flex; justify-content:flex-end; gap:10px;">
              <button class="btn" style="min-width:170px;" ?disabled=${loading} @click=${this._genuiTreeStart}>Opnieuw starten</button>
            </div>

            ${this._renderStatus()}

            ${this._renderGenuiSourcePill()}

            ${hasBlocks ? this._renderBlocks(blocks) : html`<div class="small-muted">Nog geen output. Klik op “Opnieuw starten”.</div>`}
          </div>
        </div>
      </div>
    `;
  }


  render() {
    return html`
      <div class="shell">
        ${this._renderHeader()}
        <div class="main">
          ${this.surfaceId === 'home' ? this._renderHome() : ''}
          ${this.surfaceId === 'toeslagen' ? this._renderToeslagen() : ''}
          ${this.surfaceId === 'bezwaar' ? this._renderBezwaar() : ''}
          ${this.surfaceId === 'genui_search' ? this._renderGenuiSearch() : ''}
          ${this.surfaceId === 'genui_tree' ? this._renderGenuiTree() : ''}
        </div>
      </div>
    `;
  }
}

customElements.define('bd-app', BdApp);
