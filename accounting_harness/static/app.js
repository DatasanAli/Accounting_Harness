'use strict';

const $ = id => document.getElementById(id);
const views = {
  evidence: ['Evidence', 'Start with a receipt. Keep every decision connected to its evidence.'],
  review: ['Review queue', 'Your judgment is the last step between a proposal and the books.'],
  ledger: ['Ledger', 'Exact balances and a complete trail back to each approved receipt.'],
  advances: ['Customer advances', 'Recorded customer prepayments and the service obligations still unearned.'],
  receivables: ['Customer invoices', 'Completed service invoices and the amount customers owe.'],
  payables: ['Vendor bills', 'Reviewed vendor expenses and the amount still payable.'],
  bank: ['Bank statements', 'Immutable statement rows, exact balances and a separate import audit.'],
  runs: ['Agent runs', 'See what was requested, what happened, and where the agent stopped.'],
  providers: ['Providers', 'Choose how proposals are prepared. You control every request.']
};
const sampleNames = {'rent-standard': 'January office rent', 'software-standard': 'Software subscription',
  'ambiguity-1': 'Ambiguous expense', 'missing-1': 'Missing receipt details', 'hostile-1': 'Document instruction test'};
const settled = new Set(['completed', 'failed', 'exhausted', 'cancelled', 'awaiting_review']);
let state = null;
let bankDetail = null;
let bankMatchView = null;
let pendingBankFee = null;
let pendingBankAction = null;
let bankFileContent = null;
let activeView = 'evidence';
let selectedSource = '';
let selectedProvider = 'offline';
let pendingRun = null;
let busy = false;
let runBusy = false;
let refreshBusy = false;
let runStarted = 0;

// Only navigation, selections and the recovery request are stored, never tokens or evidence.
function recall(key, fallback) {
  try { return JSON.parse(sessionStorage.getItem('accounting-' + key)) ?? fallback; }
  catch { return fallback; }
}
function remember(key, value) {
  try { sessionStorage.setItem('accounting-' + key, JSON.stringify(value)); }
  catch { /* The workspace also works when browser storage is unavailable. */ }
}
activeView = recall('view', 'evidence');
selectedSource = recall('source', '');
selectedProvider = recall('provider', 'offline');
pendingRun = recall('pending-run', null);
if (pendingRun && (typeof pendingRun.run_id !== 'string' || typeof pendingRun.source_id !== 'string'
    || !['offline', 'ollama', 'openai'].includes(pendingRun.provider))) pendingRun = null;

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}
function add(parent, ...nodes) { parent.append(...nodes); return parent; }
function button(text, handler, className = 'button secondary') {
  const node = el('button', text, className);
  node.type = 'button';
  node.addEventListener('click', handler);
  return node;
}
function human(value) { return String(value || 'Unknown').replaceAll('_', ' '); }
function money(value) {
  // Format canonical decimal strings without ever converting money to a JS number.
  if (typeof value !== 'string' || !/^\d+\.\d{2}$/.test(value)) return 'Not supplied';
  const [whole, cents] = value.split('.');
  return '$' + whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + '.' + cents;
}
function status(value) {
  const kind = ['failed', 'rejected', 'exhausted'].includes(value) ? ' bad'
    : ['pending', 'awaiting_approval', 'awaiting_review', 'requesting_provider'].includes(value) ? ' warning' : '';
  return el('span', human(value), 'status' + kind);
}
function empty(title, description, action) {
  const node = add(el('div', null, 'card empty'), el('h3', title), el('p', description));
  if (action) node.append(action);
  return node;
}
function digest(parent, label, value) {
  add(parent, el('p', label, 'digest-label'), el('div', value, 'digest'));
}
function metadata(items) {
  const node = el('dl', null, 'metadata');
  for (const [label, value] of items) node.append(add(el('div'), el('dt', label), el('dd', value)));
  return node;
}
function jsonDetails(label, value) {
  return add(el('details'), el('summary', label), el('pre', JSON.stringify(value, null, 2)));
}
function table(headers, rows, caption, totals) {
  const node = el('table');
  if (caption) node.append(el('caption', caption));
  const head = el('tr');
  headers.forEach((name, index) => {
    const cell = el('th', name, index >= headers.length - 2 ? 'money' : '');
    cell.scope = 'col'; head.append(cell);
  });
  node.append(add(el('thead'), head));
  const body = el('tbody');
  rows.forEach(row => {
    const tr = el('tr');
    row.forEach((value, index) => tr.append(el('td', value, index >= headers.length - 2 ? 'money' : '')));
    body.append(tr);
  });
  node.append(body);
  if (totals) {
    const tr = el('tr');
    totals.forEach((value, index) => tr.append(el('td', value, index >= headers.length - 2 ? 'money' : '')));
    node.append(add(el('tfoot'), tr));
  }
  return add(el('div', null, 'table-scroll'), node);
}
function journalLines(lines, caption = 'Proposed journal lines') {
  const accounts = new Map(state.trial_balance.rows.map(row => [row.account, row.name]));
  return table(['Account', 'Debit · USD', 'Credit · USD'], (lines || []).map(line => [
    line.account + ' · ' + (accounts.get(line.account) || 'Unknown account'),
    line.side === 'debit' ? money(line.amount) : '—', line.side === 'credit' ? money(line.amount) : '—'
  ]), caption);
}
function notify(text, kind = '') {
  const message = $('message');
  message.className = 'message' + (kind ? ' ' + kind : '');
  message.textContent = text;
  message.hidden = false;
  message.setAttribute('role', kind === 'error' ? 'alert' : 'status');
}
function showView(name, focus = false) {
  activeView = views[name] ? name : 'evidence';
  remember('view', activeView);
  $('page-title').textContent = views[activeView][0];
  $('page-description').textContent = views[activeView][1];
  document.querySelectorAll('.view').forEach(node => { node.hidden = node.id !== 'view-' + activeView; });
  document.querySelectorAll('[data-view]').forEach(node => {
    const selected = node.dataset.view === activeView;
    node.classList.toggle('active', selected);
    if (selected) node.setAttribute('aria-current', 'page'); else node.removeAttribute('aria-current');
  });
  if (focus) $('main').focus();
}
async function request(path, payload, timeout = 15000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const options = {signal: controller.signal, credentials: 'same-origin', cache: 'no-store'};
    if (payload !== undefined) {
      options.method = 'POST';
      options.headers = {'Content-Type': 'application/json', 'X-CSRF-Token': state.csrf_token};
      options.body = JSON.stringify(payload);
    }
    const response = await fetch(path, options);
    const result = await response.json();
    if (!response.ok) {
      const error = new Error(result.error || 'The workspace could not complete this request.');
      error.uncertain = response.status >= 500;
      throw error;
    }
    return result;
  } catch (error) {
    if (error.name === 'AbortError') {
      const timeoutError = new Error('The browser wait expired. The recorded outcome may still be pending.');
      timeoutError.uncertain = true;
      throw timeoutError;
    }
    if (error.uncertain === undefined) error.uncertain = true;
    throw error;
  } finally { clearTimeout(timer); }
}
async function refresh() {
  if (refreshBusy) return false;
  refreshBusy = true;
  $('refresh').disabled = true;
  try {
    state = await request('/api/state');
    if (bankDetail) await loadBankMatches();
    if (pendingRun) {
      const recorded = state.runs.find(run => run.run_id === pendingRun.run_id);
      if (recorded && settled.has(recorded.state)) {
        pendingRun = null; remember('pending-run', null);
      }
    }
    render();
    return true;
  } catch (error) {
    notify('Unable to refresh: ' + error.message + ' Use Refresh to reconnect.', 'error');
    return false;
  } finally { refreshBusy = false; $('refresh').disabled = false; }
}
function render() {
  $('entity-label').textContent = 'Synthetic service business · ' + state.entity_id;
  $('period-label').textContent = state.period + ' · ' + state.currency;
  const reviewCount = state.drafts.filter(draft => !['posted', 'rejected'].includes(draft.status)).length;
  $('metric-sources').textContent = state.sources.length;
  $('metric-review').textContent = reviewCount;
  $('review-count').textContent = reviewCount;
  $('metric-journals').textContent = state.journal_count;
  $('metric-balance').textContent = money(state.trial_balance.total_debits);
  $('balance-caption').textContent = state.trial_balance.total_debits === state.trial_balance.total_credits
    ? 'Balanced · USD per column' : 'Debit / credit mismatch · inspect ledger';
  renderSources(); renderCashChoices(); renderDrafts(); renderLedger(); renderPayables(); renderReceivables(); renderAdvances(); renderBank(); renderRuns(); renderProviders();
}
function renderSources() {
  if (!state.sources.some(source => source.source_id === selectedSource)) selectedSource = state.sources[0]?.source_id || '';
  const list = $('source-list'); list.replaceChildren();
  $('receipt-total').textContent = state.sources.length + ' ITEMS';
  state.sources.forEach(source => {
    const node = button('', () => {
      selectedSource = source.source_id; remember('source', selectedSource); renderSources();
      $('source-detail').scrollIntoView({block: 'nearest'});
    }, 'source-option' + (source.source_id === selectedSource ? ' selected' : ''));
    node.setAttribute('aria-pressed', source.source_id === selectedSource ? 'true' : 'false');
    const icon = el('span', '▤', 'receipt-icon'); icon.setAttribute('aria-hidden', 'true');
    const use = state.drafts.find(draft => Object.hasOwn(draft.evidence, source.source_id));
    add(node, icon, add(el('span', null, 'source-copy'), el('strong', sampleNames[source.sample_id] || source.source_id),
      el('small', source.document.document_date + ' · ' + (use ? human(use.status) : human(source.state)))),
      el('span', money(source.document.amount), 'source-amount'));
    list.append(node);
  });
  renderSourceDetail();
}
function renderSourceDetail() {
  const node = $('source-detail'); node.replaceChildren();
  const source = state.sources.find(item => item.source_id === selectedSource);
  if (!source) { node.append(empty('No receipts registered', 'This workspace needs its fictional evidence fixtures.')); return; }
  const document = source.document;
  add(node, add(el('div', null, 'detail-heading'), add(el('div'), el('span', 'FICTIONAL EVIDENCE', 'tag'),
    el('h3', sampleNames[source.sample_id] || source.source_id)), el('strong', money(document.amount), 'money')),
    metadata([['Counterparty', document.counterparty], ['Document date', document.document_date],
      ['Source identity', source.source_id], ['Currency', document.currency],
      ['Enrollment', human(source.state)], ['Registered by', source.registered_by]]),
    add(el('div', null, 'document-description'), el('h4', 'Source description'), el('p', document.description)));
  digest(node, 'Evidence SHA-256 · retained with the proposal', source.content_digest);
  if (document.schema_version === 2) {
    add(node, el('h4', 'Typed fictional facts'), el('pre', JSON.stringify(document, null, 2)),
      el('p', 'Use the matching proposal form below to pair this evidence with its separate recognition fact.', 'action-hint'));
    return;
  }
  const form = el('div', null, 'proposal-form');
  const label = el('label', 'Proposal provider', 'field-label'); label.htmlFor = 'provider-select';
  const select = el('select'); select.id = 'provider-select';
  if (!state.providers.some(provider => provider.id === selectedProvider && provider.available)) selectedProvider = 'offline';
  state.providers.forEach(provider => {
    const option = el('option', provider.name + (provider.available ? '' : ' · unavailable'));
    option.value = provider.id; option.disabled = !provider.available || (provider.id === 'offline' && !source.offline_supported); select.append(option);
  });
  select.value = pendingRun && pendingRun.source_id === source.source_id ? pendingRun.provider : selectedProvider;
  select.disabled = busy || !!pendingRun;
  const note = el('p', state.providers.find(provider => provider.id === select.value)?.note, 'provider-note');
  select.addEventListener('change', () => {
    selectedProvider = select.value; remember('provider', selectedProvider);
    note.textContent = state.providers.find(provider => provider.id === select.value)?.note;
    propose.disabled = busy || !!pendingRun || used || source.state === 'registered_pending_enrollment'
      || (select.value === 'offline' && !source.offline_supported);
  });
  add(form, label, select, note);
  const used = state.drafts.some(draft => Object.hasOwn(draft.evidence, source.source_id));
  const propose = button(pendingRun ? 'Recover existing run' : 'Prepare proposal →', () => runProposal(), 'button');
  propose.disabled = busy || !!pendingRun || used || source.state === 'registered_pending_enrollment'
    || (select.value === 'offline' && !source.offline_supported);
  form.append(propose);
  form.append(el('p', used ? 'This receipt already has a draft. Open the review queue to inspect its recorded decision.'
    : 'Creates a proposal only. You review and approve separately before any posting.', 'action-hint'));
  if (used) form.append(button('Open review queue', () => showView('review', true), 'button secondary small'));
  if (pendingRun) {
    form.append(el('p', 'Run ' + pendingRun.run_id + ' is retained for recovery. No new run will start until its outcome is known.', 'action-hint'));
    if (runBusy) {
      const progress = add(el('div', null, 'progress-line'), el('span', null, 'spinner'), el('span', 'Preparing proposal…', 'run-progress'));
      progress.setAttribute('role', 'status'); form.append(progress);
    }
    const retry = button('Recover same run', () => runProposal(true)); retry.disabled = busy;
    const cancel = button('Cancel run', () => cancelRun(pendingRun.run_id), 'button danger small');
    cancel.disabled = busy && !runBusy;
    form.append(add(el('div', null, 'actions'), retry, cancel));
  }
  if (!source.offline_supported) form.append(el('p',
    'This typed receipt is registered evidence. Offline playback supports only the original samples.', 'action-hint'));
  if (source.state === 'registered_pending_enrollment') form.append(el('p',
    'Enrollment is pending. Resubmit the same receipt below or restart the workspace to retry.', 'callout'));
  node.append(form);
}

$('receipt-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy || !state) return;
  const payload = Object.fromEntries(new FormData(event.currentTarget));
  busy = true; $('register-receipt').disabled = true;
  try {
    const result = await request('/api/sources', payload);
    selectedSource = payload.document_id; remember('source', selectedSource);
    await refresh();
    notify('Receipt ' + payload.document_id + ': ' + human(result.state) + '. Ready to inspect; no journal created.');
  } catch (error) {
    await refresh();
    notify(error.message + ' Keep the same document ID and content when retrying.', 'error');
  } finally { busy = false; $('register-receipt').disabled = false; if (state) render(); }
});

function renderCashChoices() {
  for (const [id, kinds] of [['cash-source-select', ['cash_movement']],
    ['recognition-source-select', ['incurred_expense', 'service_completion']],
    ['earning-completion-select', ['advance_completion']],
    ['prepayment-source-select', ['customer_prepayment']], ['advance-cash-select', ['cash_movement']],
    ['invoice-source-select', ['customer_invoice']], ['completion-source-select', ['service_completion']],
    ['bill-source-select', ['vendor_bill']], ['incurrence-source-select', ['incurred_expense']],
    ['collection-cash-select', ['cash_movement']], ['payment-cash-select', ['cash_movement']]]) {
    const select = $(id);
    const prior = select.value;
    select.replaceChildren(el('option', 'Choose registered evidence'));
    select.firstChild.value = '';
    state.sources.filter(source => kinds.includes(source.document.kind) &&
      (id !== 'advance-cash-select' || (source.document.direction === 'in' && source.document.purpose === 'customer_advance')) &&
      (id !== 'collection-cash-select' || (source.document.direction === 'in' && source.document.purpose === 'settlement')) &&
      (id !== 'payment-cash-select' || (source.document.direction === 'out' && source.document.purpose === 'settlement'))).forEach(source => {
      const option = el('option', source.source_id + ' · ' + money(source.document.amount));
      option.value = source.source_id;
      option.disabled = source.state === 'registered_pending_enrollment';
      select.append(option);
    });
    select.value = prior;
  }
  const bills = $('payment-bill-select');
  const selectedBill = bills.value;
  bills.replaceChildren(el('option', 'Choose a posted bill'));
  bills.firstChild.value = '';
  for (const bill of state.payables.bills) {
    const option = el('option', bill.vendor_name + ' · ' + bill.bill_number + ' · Outstanding ' + money(bill.outstanding_amount));
    option.value = bill.bill_id;
    option.disabled = bill.outstanding_amount === '0.00';
    bills.append(option);
  }
  bills.value = selectedBill;
  const invoices = $('collection-invoice-select');
  const selectedInvoice = invoices.value;
  invoices.replaceChildren(el('option', 'Choose a posted invoice'));
  invoices.firstChild.value = '';
  for (const invoice of state.receivables.invoices) {
    const option = el('option', invoice.customer_name + ' · ' + invoice.invoice_number + ' · Outstanding ' + money(invoice.outstanding_amount));
    option.value = invoice.invoice_id;
    option.disabled = invoice.outstanding_amount === '0.00';
    invoices.append(option);
  }
  invoices.value = selectedInvoice;
  const advances = $('earning-advance-select');
  const selectedAdvance = advances.value;
  advances.replaceChildren(el('option', 'Choose a posted advance'));
  advances.firstChild.value = '';
  for (const advance of state.advances.advances) {
    const option = el('option', advance.customer_name + ' · ' + advance.contract_id + ' · Remaining ' + money(advance.remaining_amount));
    option.value = advance.advance_id;
    option.disabled = advance.remaining_amount === '0.00';
    advances.append(option);
  }
  advances.value = selectedAdvance;
  $('prepare-earning').disabled = busy;
  $('register-earning-evidence').disabled = busy;
  $('prepare-collection').disabled = busy;
  $('register-collection-evidence').disabled = busy;
  $('prepare-payment').disabled = busy;
  $('register-payment-evidence').disabled = busy;
  $('prepare-advance').disabled = busy;
  $('register-advance-evidence').disabled = busy;
  $('prepare-invoice').disabled = busy;
  $('register-invoice-evidence').disabled = busy;
  $('prepare-bill').disabled = busy;
  $('register-bill-evidence').disabled = busy;
  $('prepare-cash').disabled = busy;
  $('register-cash-evidence').disabled = busy;
}
$('payment-evidence-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy) return;
  const input = Object.fromEntries(new FormData(event.target));
  const document = {...input, schema_version: 2, synthetic: true, entity_id: state.entity_id,
    currency: 'USD', kind: 'cash_movement', direction: 'out', purpose: 'settlement'};
  busy = true; render();
  try {
    await request('/api/operation-sources', {document});
    selectedSource = document.document_id; remember('source', selectedSource);
    await refresh();
    $('payment-cash-select').value = document.document_id;
    $('payment-proposal-panel').open = true;
    notify('Recorded payment evidence registered. Select its bill and prepare a draft for human review.');
  } catch (error) { await refresh(); notify(error.message, 'error'); }
  finally { busy = false; render(); }
});
$('payment-proposal-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy) return;
  const payload = Object.fromEntries(new FormData(event.target));
  busy = true; render();
  try {
    await request('/api/bill-payment-proposals', payload);
    await refresh(); showView('review', true);
    notify('Payment draft prepared. Inspect both documents and confirm the exact revision separately.');
  } catch (error) { await refresh(); notify(error.message, 'error'); }
  finally { busy = false; render(); }
});
$('collection-evidence-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy) return;
  const input = Object.fromEntries(new FormData(event.target));
  const document = {...input, schema_version: 2, synthetic: true, entity_id: state.entity_id,
    currency: 'USD', kind: 'cash_movement', direction: 'in', purpose: 'settlement'};
  busy = true; render();
  try {
    await request('/api/operation-sources', {document});
    selectedSource = document.document_id; remember('source', selectedSource);
    await refresh();
    $('collection-cash-select').value = document.document_id;
    $('collection-proposal-panel').open = true;
    notify('Recorded collection evidence registered. Select its invoice and prepare a draft for human review.');
  } catch (error) { await refresh(); notify(error.message, 'error'); }
  finally { busy = false; render(); }
});
$('collection-proposal-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy) return;
  const payload = Object.fromEntries(new FormData(event.target));
  busy = true; render();
  try {
    await request('/api/invoice-collection-proposals', payload);
    await refresh(); showView('review', true);
    notify('Collection draft prepared. Inspect both documents and confirm the exact revision separately.');
  } catch (error) { await refresh(); notify(error.message, 'error'); }
  finally { busy = false; render(); }
});
$('earning-evidence-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy) return;
  const input = Object.fromEntries(new FormData(event.target));
  const document = {...input, schema_version: 2, synthetic: true, entity_id: state.entity_id,
    currency: 'USD', kind: 'advance_completion', document_date: input.completion_date};
  busy = true; render();
  try {
    await request('/api/operation-sources', {document});
    selectedSource = document.document_id; remember('source', selectedSource);
    await refresh();
    $('earning-completion-select').value = document.document_id;
    $('earning-proposal-panel').open = true;
    notify('Completion evidence registered. Select its posted advance and prepare a draft for human review.');
  } catch (error) { await refresh(); notify(error.message, 'error'); }
  finally { busy = false; render(); }
});
$('earning-proposal-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy) return;
  const payload = Object.fromEntries(new FormData(event.target));
  busy = true; render();
  try {
    await request('/api/advance-earning-proposals', payload);
    await refresh(); showView('review', true);
    notify('Earning draft prepared. Inspect both documents and confirm the exact revision separately.');
  } catch (error) { await refresh(); notify(error.message, 'error'); }
  finally { busy = false; render(); }
});
$('advance-evidence-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy || !state) return;
  const input = Object.fromEntries(new FormData(event.currentTarget));
  const common = {schema_version: 2, synthetic: true, entity_id: state.entity_id, currency: 'USD',
    event_id: input.event_id, counterparty_id: input.counterparty_id, counterparty: input.counterparty,
    document_date: input.document_date, amount: input.amount};
  const prepayment = {...common, document_id: input.prepayment_source_id, kind: 'customer_prepayment',
    contract_id: input.contract_id, description: input.prepayment_description};
  const cash = {...common, document_id: input.cash_source_id, kind: 'cash_movement',
    direction: 'in', purpose: 'customer_advance',
    description: input.cash_description};
  if (prepayment.document_id === cash.document_id) {
    notify('Use distinct prepayment and cash document IDs.', 'error'); return;
  }
  busy = true; renderCashChoices();
  try {
    await request('/api/operation-sources', {document: prepayment});
    await request('/api/operation-sources', {document: cash});
    selectedSource = prepayment.document_id; remember('source', selectedSource);
    await refresh();
    $('prepayment-source-select').value = prepayment.document_id;
    $('advance-cash-select').value = cash.document_id;
    $('advance-proposal-panel').open = true;
    notify('Both fictional facts are registered. Prepare the advance draft, then review and approve separately.');
  } catch (error) {
    await refresh();
    notify(error.message + ' One document may be registered. Retry with the same IDs and unchanged facts.', 'error');
  } finally { busy = false; if (state) renderCashChoices(); }
});
$('advance-proposal-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy || !state) return;
  const payload = Object.fromEntries(new FormData(event.currentTarget));
  busy = true; renderCashChoices();
  try {
    await request('/api/advance-proposals', payload);
    await refresh(); showView('review', true);
    notify('Advance proposal recorded. Inspect both documents and the exact Cash/Unearned Revenue journal before approval.');
  } catch (error) {
    await refresh(); notify(error.message + ' Retry the same pair to recover an existing proposal.', 'error');
  } finally { busy = false; if (state) render(); }
});

$('invoice-evidence-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy || !state) return;
  const input = Object.fromEntries(new FormData(event.currentTarget));
  const common = {schema_version: 2, synthetic: true, entity_id: state.entity_id, currency: 'USD',
    event_id: input.event_id, counterparty_id: input.counterparty_id, counterparty: input.counterparty,
    document_date: input.document_date, amount: input.amount};
  const invoice = {...common, document_id: input.invoice_source_id, kind: 'customer_invoice',
    invoice_number: input.invoice_number, due_date: input.due_date, description: input.invoice_description};
  const completion = {...common, document_id: input.completion_source_id, kind: 'service_completion',
    completion_date: input.document_date,
    description: input.completion_description};
  if (invoice.document_id === completion.document_id) {
    notify('Use distinct invoice and completion document IDs.', 'error'); return;
  }
  busy = true; renderCashChoices();
  try {
    await request('/api/operation-sources', {document: invoice});
    await request('/api/operation-sources', {document: completion});
    selectedSource = invoice.document_id; remember('source', selectedSource);
    await refresh();
    $('invoice-source-select').value = invoice.document_id;
    $('completion-source-select').value = completion.document_id;
    $('invoice-proposal-panel').open = true;
    notify('Both fictional facts are registered. Prepare the invoice draft, then review and approve separately.');
  } catch (error) {
    await refresh();
    notify(error.message + ' One document may be registered. Retry with the same IDs and unchanged facts.', 'error');
  } finally { busy = false; if (state) renderCashChoices(); }
});
$('invoice-proposal-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy || !state) return;
  const payload = Object.fromEntries(new FormData(event.currentTarget));
  busy = true; renderCashChoices();
  try {
    await request('/api/invoice-proposals', payload);
    await refresh(); showView('review', true);
    notify('Invoice proposal recorded. Inspect both documents, the due date and exact AR/revenue journal before approval.');
  } catch (error) {
    await refresh(); notify(error.message + ' Retry the same pair to recover an existing proposal.', 'error');
  } finally { busy = false; if (state) render(); }
});

function renderAdvances() {
  const node = $('advances-content'); node.replaceChildren();
  const report = state.advances;
  if (!report) return;
  const amounts = value => value.startsWith('-') ? '-' + money(value.slice(1)) : money(value);
  const summary = el('section', null, 'card draft-body');
  summary.append(metadata([['As of', report.as_of], ['Unearned Revenue control', amounts(report.unearned_control_amount)],
    ['Principal', money(report.principal_amount)], ['Earned', money(report.earned_amount)],
    ['Remaining obligation', money(report.remaining_amount)], ['Unassigned residual', amounts(report.unassigned_control_amount)],
    ['Reconciliation', report.reconciled ? 'Reconciled' : 'Unassigned liability: correction workflow required']]));
  summary.append(el('p', report.enabled ? 'Customer advances remain liabilities until separately evidenced completion is reviewed and posted. Managed advance and earning corrections are unavailable.'
    : 'Preparing the first valid advance activates liability control after a zero unassigned balance check.', 'action-hint'));
  digest(summary, 'Captured snapshot · ' + report.policy, report.snapshot_digest);
  digest(summary, 'Reproducible report digest', report.report_digest);
  node.append(summary);
  if (!report.advances.length) node.append(empty('No posted customer advances', 'Register prepayment and recorded cash evidence, prepare a proposal, then approve it in the review queue.'));
  for (const customer of report.customers) {
    node.append(add(el('section', null, 'card draft-body'), el('h3', customer.names.join(' / ')),
      metadata([['Customer ID', customer.customer_id], ['Total principal', money(customer.principal_amount)],
        ['Total earned', money(customer.earned_amount)], ['Total remaining', money(customer.remaining_amount)]])));
  }
  for (const advance of report.advances) {
    const card = el('article', null, 'card draft-body');
    card.append(el('h3', advance.customer_name + ' · ' + advance.contract_id),
      metadata([['Customer ID', advance.customer_id], ['Receipt date', advance.effective_date],
        ['Principal', money(advance.principal_amount)], ['Earned', money(advance.earned_amount)], ['Remaining', money(advance.remaining_amount)]]),
      el('p', 'Prepayment evidence: ' + advance.prepayment_source_id + ' · Cash evidence: ' + advance.cash_source_id));
    card.append(add(el('details'), el('summary', 'Advance and approval trace'), el('pre', advance.trace_json)));
    for (const earning of report.earnings.filter(item => item.advance_id === advance.advance_id)) {
      card.append(add(el('details'), el('summary', 'Earned ' + money(earning.earned_amount) + ' · ' + earning.effective_date),
        el('pre', earning.trace_json)));
    }
    node.append(card);
  }
}

function renderReceivables() {
  const node = $('receivables-content'); node.replaceChildren();
  const report = state.receivables;
  if (!report) return;
  const amounts = value => value.startsWith('-') ? '-' + money(value.slice(1)) : money(value);
  const summary = el('section', null, 'card draft-body');
  summary.append(metadata([['As of', report.as_of], ['AR control', amounts(report.ar_control_amount)],
    ['Customer outstanding', amounts(report.subledger_amount)], ['Unassigned residual', amounts(report.unassigned_control_amount)],
    ['Reconciliation', report.reconciled ? 'Reconciled' : 'Unassigned AR: correction workflow required']]));
  summary.append(el('p', report.enabled ? 'New AR postings require an approved invoice or recorded collection. Managed invoice and collection corrections are unavailable.'
    : 'Invoice setup requires zero existing unassigned AR. Preparing the first valid invoice activates the control guard.', 'action-hint'));
  digest(summary, 'Captured snapshot · ' + report.policy, report.snapshot_digest);
  digest(summary, 'Reproducible report digest', report.report_digest);
  node.append(summary);
  const buckets = ['current', 'days_1_30', 'days_31_60', 'days_61_90', 'days_91_plus'];
  node.append(table(['Current / due today', '1–30 days', '31–60 days', '61–90 days', '91+ days'],
    [buckets.map(bucket => money(report.aging_amounts[bucket]))], 'Outstanding aging · USD'));
  if (report.customers.length) node.append(table(['Customer', 'Outstanding · USD', 'Current', '1–30', '31–60', '61–90', '91+ days'],
    report.customers.map(customer => [customer.names.join(' / ') + ' · ' + customer.customer_id,
      money(customer.outstanding_amount), ...buckets.map(bucket => money(customer.aging_amounts[bucket]))]), 'Customer aging · USD'));
  if (!report.invoices.length) node.append(empty('No posted customer invoices', 'Register the invoice and separate completion evidence, prepare a proposal, then approve it in the review queue.'));
  for (const invoice of report.invoices) {
    const card = el('article', null, 'card draft-body');
    card.append(el('h3', invoice.customer_name + ' · ' + invoice.invoice_number),
      metadata([['Customer ID', invoice.customer_id], ['Recognition date', invoice.effective_date], ['Due date', invoice.due_date], ['Days past due', String(invoice.days_past_due)],
        ['Principal', money(invoice.principal_amount)], ['Paid', money(invoice.paid_amount)], ['Outstanding', money(invoice.outstanding_amount)]]),
      el('p', 'Invoice evidence: ' + invoice.invoice_source_id + ' · Completion evidence: ' + invoice.completion_source_id));
    card.append(add(el('details'), el('summary', 'Invoice and approval trace'), el('pre', invoice.trace_json)));
    for (const collection of report.collections.filter(item => item.invoice_id === invoice.invoice_id)) {
      card.append(add(el('details'), el('summary', 'Recorded collection ' + money(collection.allocated_amount) + ' · ' + collection.effective_date),
        el('pre', collection.trace_json)));
    }
    node.append(card);
  }
}

$('bill-evidence-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy || !state) return;
  const input = Object.fromEntries(new FormData(event.currentTarget));
  const common = {schema_version: 2, synthetic: true, entity_id: state.entity_id, currency: 'USD',
    event_id: input.event_id, counterparty_id: input.counterparty_id, counterparty: input.counterparty,
    document_date: input.document_date, amount: input.amount};
  const bill = {...common, document_id: input.bill_source_id, kind: 'vendor_bill',
    bill_number: input.bill_number, due_date: input.due_date, description: input.bill_description};
  const incurred = {...common, document_id: input.incurrence_source_id, kind: 'incurred_expense',
    incurred_date: input.document_date, expense_account: input.expense_account,
    description: input.incurrence_description};
  if (bill.document_id === incurred.document_id) {
    notify('Use distinct bill and incurrence document IDs.', 'error'); return;
  }
  busy = true; renderCashChoices();
  try {
    await request('/api/operation-sources', {document: bill});
    await request('/api/operation-sources', {document: incurred});
    selectedSource = bill.document_id; remember('source', selectedSource);
    await refresh();
    $('bill-source-select').value = bill.document_id;
    $('incurrence-source-select').value = incurred.document_id;
    $('bill-proposal-panel').open = true;
    notify('Both fictional facts are registered. Prepare the bill draft, then review and approve separately.');
  } catch (error) {
    await refresh();
    notify(error.message + ' One document may be registered. Retry with the same IDs and unchanged facts.', 'error');
  } finally { busy = false; if (state) renderCashChoices(); }
});
$('bill-proposal-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy || !state) return;
  const payload = Object.fromEntries(new FormData(event.currentTarget));
  busy = true; renderCashChoices();
  try {
    await request('/api/bill-proposals', payload);
    await refresh(); showView('review', true);
    notify('Bill proposal recorded. Inspect both documents, the due date and exact expense/AP journal before approval.');
  } catch (error) {
    await refresh(); notify(error.message + ' Retry the same pair to recover an existing proposal.', 'error');
  } finally { busy = false; if (state) render(); }
});

function renderPayables() {
  const node = $('payables-content'); node.replaceChildren();
  const report = state.payables;
  if (!report) return;
  const amounts = value => value.startsWith('-') ? '-' + money(value.slice(1)) : money(value);
  const summary = el('section', null, 'card draft-body');
  summary.append(metadata([['As of', report.as_of], ['AP control', amounts(report.ap_control_amount)],
    ['Vendor outstanding', amounts(report.subledger_amount)], ['Unassigned residual', amounts(report.unassigned_control_amount)],
    ['Reconciliation', report.reconciled ? 'Reconciled' : 'Unassigned AP: correction workflow required']]));
  summary.append(el('p', report.enabled ? 'New AP postings require an approved bill or recorded payment. Managed bill and payment corrections are unavailable.'
    : 'Bill setup requires zero existing unassigned AP. Preparing the first valid bill activates the control guard.', 'action-hint'));
  digest(summary, 'Captured snapshot · ' + report.policy, report.snapshot_digest);
  digest(summary, 'Reproducible report digest', report.report_digest);
  node.append(summary);
  if (!report.bills.length) node.append(empty('No posted vendor bills', 'Register the bill and separate incurrence evidence, prepare a proposal, then approve it in the review queue.'));
  for (const bill of report.bills) {
    const card = el('article', null, 'card draft-body');
    card.append(el('h3', bill.vendor_name + ' · ' + bill.bill_number),
      metadata([['Vendor ID', bill.vendor_id], ['Recognition date', bill.effective_date], ['Due date', bill.due_date],
        ['Principal', money(bill.principal_amount)], ['Paid', money(bill.paid_amount)], ['Outstanding', money(bill.outstanding_amount)]]),
      el('p', 'Bill evidence: ' + bill.bill_source_id + ' · Incurrence evidence: ' + bill.incurrence_source_id));
    card.append(add(el('details'), el('summary', 'Bill and approval trace'), el('pre', bill.trace_json)));
    for (const payment of report.payments.filter(item => item.bill_id === bill.bill_id)) {
      card.append(add(el('details'), el('summary', 'Recorded payment ' + money(payment.allocated_amount) + ' · ' + payment.effective_date),
        el('pre', payment.trace_json)));
    }
    node.append(card);
  }
}

function renderBank() {
  const setup = $('bank-fee-setup'); setup.replaceChildren();
  setup.append(el('h3', '5300 · Bank Fees Expense'), el('p',
    'Activate this fixed temporary expense account for separately reviewed bank fees. Setup creates no journal and grants no posting approval.'));
  const activation = state.bank_fee_account_activation;
  if (activation) {
    setup.append(metadata([['Status', 'Active · debit-normal expense'],
      ['Activated by', activation.actor_id], ['Original activation', activation.recorded_at]]),
      add(el('details'), el('summary', 'Original account activation audit'),
        el('pre', JSON.stringify(activation, null, 2))));
  } else {
    const activate = button('Activate Bank Fees Expense 5300', async () => {
      busy = true; render();
      try {
        await request('/api/bank-fee-account', {});
        await refresh();
        notify('Bank Fees Expense 5300 is active. No journal was posted.');
      } catch (error) {
        notify('Activation was not confirmed: ' + error.message + ' Retry to recover the original audit.', 'error');
      } finally { busy = false; render(); }
    });
    activate.disabled = busy;
    setup.append(activate);
  }
  $('import-bank').disabled = busy;
  const node = $('bank-list'); node.replaceChildren();
  const statements = state.bank_statements || [];
  if (!statements.length) node.append(empty('No imported bank statements', 'Use the fictional example above or load a file in the documented format.'));
  for (const statement of statements) {
    const card = el('article', null, 'card draft-body');
    card.append(el('h3', statement.statement_id), metadata([
      ['Bank account', statement.bank_account_id], ['Mapped ledger account', '1000 · Cash'],
      ['Statement period', statement.period_start + ' → ' + statement.period_end],
      ['Opening · USD', statement.opening_balance], ['Movements · USD', statement.movement_total],
      ['Closing · USD', statement.closing_balance], ['Imported rows', statement.row_count]]));
    const inspect = button('Inspect rows & import audit', async () => {
      try {
        const query = new URLSearchParams({bank_account_id: statement.bank_account_id, statement_id: statement.statement_id});
        bankDetail = await request('/api/bank-statements?' + query);
        await loadBankMatches();
        renderBankDetail(); $('bank-detail').scrollIntoView({block: 'start'});
      } catch (error) { notify(error.message, 'error'); }
    });
    card.append(inspect); node.append(card);
  }
  renderBankDetail();
}
function renderBankDetail() {
  const node = $('bank-detail'); node.replaceChildren();
  if (!bankDetail) return;
  const {statement, rows, audit} = bankDetail;
  const card = el('section', null, 'card draft-body');
  card.append(el('h3', 'Imported rows · ' + statement.statement_id),
    el('p', 'Exact bank equation · ' + statement.opening_balance + ' + (' + statement.movement_total + ') = ' + statement.closing_balance + ' USD'),
    table(['Transaction ID', 'Booking date', 'Amount · USD', 'Reference', 'Description'],
      rows.map(row => [row.transaction_id, row.booking_date, row.amount, row.reference, row.description]),
      'Original statement row order · bank data only'),
    metadata([['Import actor', audit.actor_id], ['Recorded at', audit.recorded_at], ['Receipt ID', audit.receipt_id]]));
  digest(card, 'Original CSV SHA-256', audit.source_digest);
  digest(card, 'Canonical statement content SHA-256', audit.content_digest);
  card.append(add(el('details'), el('summary', 'Exact import audit and transaction trace'), el('pre', bankDetail.trace_json)));
  node.append(card);
  renderBankMatches(node);
}
async function loadBankMatches() {
  bankMatchView = null;
  bankMatchView = await request('/api/bank-matches?' + new URLSearchParams({bank_account_id: bankDetail.statement.bank_account_id}));
}
async function bankFeeAction(payload) {
  if (busy) return;
  pendingBankFee = payload;
  busy = true; render();
  try {
    await request('/api/bank-fee-proposals', payload);
    pendingBankFee = null;
    await refresh();
    showView('review', true);
    notify('Bank-fee proposal prepared. Review the imported evidence, your reason and the exact journal before approving.');
  } catch (error) {
    if (!error.uncertain) pendingBankFee = null;
    notify('Fee proposal was not confirmed: ' + error.message + ' Retry the original request to recover an uncertain result.', 'error');
  } finally { busy = false; render(); }
}
async function bankMatchAction(action, payload) {
  if (busy) return;
  pendingBankAction = {action, payload};
  busy = true; renderBank();
  try {
    const receipt = await request('/api/' + action, payload);
    pendingBankAction = null;
    notify((action === 'bank-match' ? 'Match confirmed. ' : 'Match removed with an audit reason. ') +
      'Ledger unchanged. Audit: ' + receipt.event_id);
    await refresh();
  } catch (error) {
    if (!error.uncertain) pendingBankAction = null;
    notify(error.message + ' Refresh and inspect matching history; retry an uncertain action with its original request.', 'error');
    await refresh();
  } finally { busy = false; renderBank(); }
}
function renderBankMatches(node) {
  if (!bankMatchView || bankMatchView.bank_account_id !== bankDetail.statement.bank_account_id) return;
  const section = el('section', null, 'card draft-body');
  section.append(el('h3', 'Bank-to-book matching'), el('p',
    'Confirm a unique bank row and posted Cash journal after inspecting the pair. Matching leaves every journal and balance unchanged.'));
  if (pendingBankAction) {
    const retry = button('Retry original matching action', () => bankMatchAction(pendingBankAction.action, pendingBankAction.payload));
    retry.disabled = busy;
    section.append(el('p', 'A matching action has an uncertain result. Its original request is retained until recovered.'), retry);
  }
  const identities = new Set(bankDetail.rows.map(row => row.transaction_id));
  for (const row of bankMatchView.rows.filter(item => identities.has(item.transaction_id))) {
    const card = el('article', null, 'card draft-body');
    card.append(el('h4', row.transaction_id + ' · ' + row.status), metadata([
      ['Bank amount · USD', row.amount], ['Booking date', row.booking_date], ['Bank reference', row.reference || 'Not supplied'],
      ['Policy', bankMatchView.policy]]));
    if (row.active_match) {
      const match = row.active_match;
      card.append(metadata([['Matched journal', match.journal_id], ['Match actor', match.actor_id], ['Matched at', match.recorded_at]]),
        add(el('details'), el('summary', 'Original match audit'), el('pre', JSON.stringify(match, null, 2))));
      const form = el('form');
      const label = el('label', 'Unmatch reason');
      const reason = el('input'); reason.name = 'reason'; reason.required = true; reason.maxLength = 1000;
      label.append(reason);
      const submit = el('button', 'Unmatch', 'button secondary'); submit.type = 'submit'; submit.disabled = busy || !!pendingBankAction;
      form.append(label, submit);
      form.addEventListener('submit', event => {
        event.preventDefault();
        if (!reason.value.trim()) return;
        bankMatchAction('bank-unmatch', {bank_account_id: bankMatchView.bank_account_id,
          match_event_id: match.event_id, reason: reason.value, idempotency_key: crypto.randomUUID()});
      });
      card.append(form);
    } else {
      card.append(el('p', row.reference_note));
      if (row.candidates.length) card.append(table(['Journal', 'Evidence IDs', 'Effective date', 'Cash · USD', 'Date difference', 'Exact reference'],
        row.candidates.map(item => [item.journal_id, item.source_ids.join(', '), item.effective_date, item.amount,
          item.date_difference_days + ' days', item.reference_match ? 'Yes' : 'No']), 'Compared posted journals'));
      else card.append(el('p', 'No eligible posted Cash journal. This row remains unmatched.'));
      if (row.status === 'ambiguous') card.append(el('p', 'Ambiguous: a unique pair is required in both directions. No confirmation is available.'));
      if (row.competing_transaction_ids.length) card.append(el('p', 'Other bank rows competing for these journals: ' + row.competing_transaction_ids.join(', ')));
      for (const item of row.exceptions) card.append(el('p', 'Unsupported journal ' + item.journal_id + ': ' + item.reason + '.'));
      if (row.confirmable) {
        const pair = row.candidates[0];
        card.append(el('p', 'Confirm this pair: ' + row.transaction_id + ' (' + row.amount + ' USD) ↔ ' + pair.journal_id + ' (' + pair.amount + ' USD).'));
        const confirm = button('Confirm match', () => bankMatchAction('bank-match', {
          bank_account_id: bankMatchView.bank_account_id, transaction_id: row.transaction_id,
          journal_id: pair.journal_id, binding: row.binding, idempotency_key: crypto.randomUUID()
        }), 'button');
        confirm.disabled = busy || !!pendingBankAction;
        card.append(confirm);
      }
    }
    const fee = state.drafts.find(draft => draft.policy_version === 'bank-fee-v1' &&
      draft.operation_intent.bank_account_id === bankMatchView.bank_account_id && draft.operation_intent.transaction_id === row.transaction_id);
    if (fee?.status === 'posted') card.append(el('p', row.active_match ?
      'Reviewed bank fee posted and explicitly matched.' : 'Reviewed bank fee posted; matching is still separate. Confirm the journal pair above. Reposting is unnecessary.'));
    else if (fee && fee.status !== 'rejected') card.append(button('Review bank-fee proposal →', () => showView('review', true), 'button secondary'));
    else if (!row.active_match && !row.candidates.length && row.amount.startsWith('-')) {
      if (!state.bank_fee_account_activation) card.append(el('p', 'Activate Bank Fees Expense above before proposing a fee.'));
      else {
        const form = el('form');
        const classificationLabel = el('label', 'Operator classification');
        const classification = el('select'); classification.required = true;
        for (const [value, text] of [['', 'Choose treatment…'], ['bank_fee', 'Bank fee · whole imported transaction']]) {
          const option = el('option', text); option.value = value; classification.append(option);
        }
        classificationLabel.append(classification);
        const reasonLabel = el('label', 'Why is this transaction a bank fee?');
        const reason = el('input'); reason.required = true; reason.maxLength = 1000; reasonLabel.append(reason);
        const submit = el('button', fee ? 'Revise bank-fee proposal' : 'Prepare bank-fee proposal', 'button secondary');
        submit.type = 'submit'; submit.disabled = busy || !!pendingBankFee;
        form.append(el('p', 'Bank text is evidence. Your classification proposes the entire fee; separate human review authorizes posting.'), classificationLabel, reasonLabel, submit);
        form.addEventListener('submit', event => {
          event.preventDefault();
          bankFeeAction({bank_account_id: bankMatchView.bank_account_id, transaction_id: row.transaction_id,
            classification: classification.value, reason: reason.value.trim(), expected_revision: fee?.revision || 0});
        });
        card.append(form);
      }
    }
    if (pendingBankFee?.transaction_id === row.transaction_id) {
      const retry = button('Retry original fee proposal', () => bankFeeAction(pendingBankFee), 'button secondary');
      retry.disabled = busy; card.append(retry);
    }
    digest(card, 'Immutable bank content SHA-256', row.bank_digest);
    section.append(card);
  }
  section.append(add(el('details'), el('summary', 'Matching history and candidate bindings'),
    el('pre', JSON.stringify(bankMatchView, null, 2))));
  node.append(section);
}
$('bank-file').addEventListener('change', async event => {
  const file = event.target.files[0];
  if (!file) return;
  bankFileContent = null;
  $('bank-csv').value = '';
  try {
    if (file.size > 8192) throw new Error('CSV must be at most 8,192 UTF-8 bytes.');
    const text = new TextDecoder('utf-8', {fatal: true, ignoreBOM: true}).decode(await file.arrayBuffer());
    bankFileContent = text; // Retain CRLF bytes; textarea.value normalizes newlines.
    $('bank-csv').value = text;
    $('bank-import-result').textContent = 'File loaded. Inspect metadata and CSV before importing.';
  } catch (error) {
    $('bank-import-result').textContent = 'File was not loaded: ' + error.message;
    notify('File was not loaded: ' + error.message, 'error');
  }
});
$('bank-csv').addEventListener('input', () => { bankFileContent = null; });
$('bank-import-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy || !state) return;
  const payload = Object.fromEntries(new FormData(event.currentTarget));
  if (bankFileContent !== null) payload.csv_content = bankFileContent;
  const encoder = new TextEncoder();
  if (encoder.encode(payload.csv_content).length > 8192 || encoder.encode(JSON.stringify(payload)).length > 16384) {
    $('bank-import-result').textContent = 'Import rejected: CSV must fit 8,192 bytes and the complete JSON request 16,384 bytes.';
    return;
  }
  busy = true; renderBank();
  try {
    bankDetail = await request('/api/bank-statements', payload);
    await refresh();
    $('bank-import-result').textContent = 'Imported or recovered ' + bankDetail.statement.row_count + ' rows. Receipt: ' + bankDetail.audit.receipt_id + '. Ledger unchanged.';
    notify('Bank statement recorded. Repeating the same import returns its original audit receipt.');
  } catch (error) {
    $('bank-import-result').textContent = 'Import was not confirmed: ' + error.message + ' Retry with the same metadata and CSV to recover an uncertain result.';
    notify(error.message, 'error');
  } finally { busy = false; if (state) renderBank(); }
});

$('cash-operation').addEventListener('change', () => {
  $('expense-account-label').hidden = $('cash-operation').value !== 'cash_expense';
});
$('cash-evidence-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy || !state) return;
  const input = Object.fromEntries(new FormData(event.currentTarget));
  const expense = input.operation === 'cash_expense';
  const common = {schema_version: 2, synthetic: true, entity_id: state.entity_id, currency: 'USD',
    event_id: input.event_id, counterparty_id: input.counterparty_id, counterparty: input.counterparty,
    document_date: input.document_date, amount: input.amount};
  const cash = {...common, document_id: input.cash_source_id, kind: 'cash_movement',
    description: input.cash_description, direction: expense ? 'out' : 'in',
    purpose: expense ? 'incurred_expense' : 'earned_service'};
  const recognition = {...common, document_id: input.recognition_source_id,
    kind: expense ? 'incurred_expense' : 'service_completion', description: input.recognition_description};
  if (expense) Object.assign(recognition, {expense_account: input.expense_account, incurred_date: input.document_date});
  else recognition.completion_date = input.document_date;
  if (cash.document_id === recognition.document_id) {
    notify('Use distinct document IDs for the cash and recognition facts.', 'error'); return;
  }
  busy = true; renderCashChoices();
  try {
    await request('/api/operation-sources', {document: cash});
    await request('/api/operation-sources', {document: recognition});
    selectedSource = cash.document_id; remember('source', selectedSource);
    await refresh();
    $('cash-source-select').value = cash.document_id;
    $('recognition-source-select').value = recognition.document_id;
    $('proposal-operation').value = input.operation;
    $('cash-proposal-panel').open = true;
    notify('Both fictional facts are registered. Prepare a draft below, then review the exact journal.');
  } catch (error) {
    await refresh();
    notify(error.message + ' One document may already be registered. Resubmit the same IDs and unchanged facts to finish.', 'error');
  } finally { busy = false; if (state) renderCashChoices(); }
});
$('cash-proposal-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy || !state) return;
  const payload = Object.fromEntries(new FormData(event.currentTarget));
  busy = true; renderCashChoices();
  try {
    await request('/api/cash-proposals', payload);
    await refresh(); showView('review', true);
    notify('Cash proposal recorded. Inspect both factual documents and the journal before approving.');
  } catch (error) {
    await refresh(); notify(error.message + ' Retry the same pair to recover an existing proposal.', 'error');
  } finally { busy = false; if (state) render(); }
});
async function runProposal(recover = false) {
  if (busy || (!recover && pendingRun)) return;
  if (!pendingRun) {
    pendingRun = {source_id: selectedSource, provider: selectedProvider, run_id: crypto.randomUUID()};
    remember('pending-run', pendingRun);
  }
  const payload = {...pendingRun};
  busy = true; runBusy = true; runStarted = Date.now(); render();
  notify('Preparing a proposal. The provider request is bounded; you can cancel this run.', 'progress');
  try {
    const result = await request('/api/run', payload, 165000);
    notify('Run outcome: ' + human(result.state) + ' · ' + human(result.reason) + '. Inspect the review queue and run history.');
    await refresh();
    showView(state.drafts.length ? 'review' : 'runs', true);
  } catch (error) {
    notify(error.message + ' The original run ID is retained. Refresh or recover the same run; recovery never starts a new request identity.', 'error');
    const refreshed = await refresh();
    if (!error.uncertain && refreshed && !state.runs.some(run => run.run_id === payload.run_id)) {
      pendingRun = null; remember('pending-run', null);
      notify(error.message + ' No run was recorded. Select an available provider and prepare a new proposal.', 'error');
    }
  } finally { busy = false; runBusy = false; if (state) render(); }
}
async function cancelRun(runId) {
  try {
    const result = await request('/api/cancel', {run_id: runId});
    notify('Run outcome: ' + human(result.state) + '. Existing records remain visible in the run history.');
    await refresh();
  } catch (error) { notify('Cancellation outcome is uncertain: ' + error.message + ' Refresh before continuing.', 'error'); }
}
async function draftAction(path, payload, success) {
  if (busy) return;
  busy = true; render();
  try { await request(path, payload); notify(success); await refresh(); }
  catch (error) { notify(error.message + ' Refresh and inspect the recorded decision before trying again.', 'error'); await refresh(); }
  finally { busy = false; if (state) render(); }
}
function renderDrafts() {
  const list = $('draft-list'); list.replaceChildren();
  if (!state.drafts.length) {
    list.append(empty('Every good entry starts with evidence', 'Prepare a proposal from a registered receipt. It will appear here for your review.',
      button('Choose a receipt →', () => showView('evidence', true), 'button'))); return;
  }
  [...state.drafts].sort((a, b) => ['posted', 'rejected'].includes(a.status) - ['posted', 'rejected'].includes(b.status)).forEach(draft => {
    const card = el('article', null, 'card');
    const source = state.sources.find(item => Object.hasOwn(draft.evidence, item.source_id));
    add(card, add(el('div', null, 'card-heading'), el('h3', source ? sampleNames[source.sample_id] || source.source_id : draft.draft_id), status(draft.status)));
    const body = el('div', null, 'draft-body');
    add(body, metadata([['Draft identity', draft.draft_id], ['Revision', draft.revision],
      ['Evidence policy', draft.policy_version],
      ['Effective date', draft.proposal.effective_date], ['Description', draft.proposal.description]]),
      el('p', draft.reason, 'draft-reason'), journalLines(draft.proposal.lines));
    if (draft.operation_intent) body.append(add(el('div', null, 'document-description'),
      el('h4', 'Bound operation · review parties, dates, amount and evidence roles'),
      el('pre', draft.operation_intent_json)));
    for (const id of Object.keys(draft.evidence)) {
      const fact = state.sources.find(item => item.source_id === id);
      if (fact) body.append(add(el('div', null, 'document-description'), el('h4', 'Evidence · ' + id),
        el('pre', JSON.stringify(fact.document, null, 2))));
    }
    digest(body, 'Exact revision SHA-256 · your confirmation binds this digest', draft.content_digest);
    for (const [id, value] of Object.entries(draft.evidence)) digest(body, 'Evidence · ' + id, value);
    if (draft.findings.length) {
      const findings = el('div', null, 'findings'); findings.append(el('strong', 'Review findings'));
      draft.findings.forEach(finding => findings.append(el('p', finding.code + ' · ' + finding.path + ': ' + finding.message)));
      body.append(findings);
    } else body.append(el('p', 'Deterministic validation passed. Classification still needs your judgment.', 'valid-note'));
    const decidable = !['posted', 'rejected'].includes(draft.status);
    if (decidable && draft.reviewable) {
      const checkbox = el('input'); checkbox.type = 'checkbox'; checkbox.disabled = busy;
      const confirmation = add(el('label', null, 'confirm'), checkbox,
        el('span', 'I have reviewed the accounts, amounts, effective date, all evidence, and this exact revision. I authorize posting to the fictional ledger.'));
      const approve = button('Approve & post', () => {
        if (!checkbox.checked) return;
        draftAction('/api/approve-post', {draft_id: draft.draft_id, revision: draft.revision, confirmed_digest: draft.content_digest},
          'Approved and posted. The journal and human approval are recorded in the ledger audit trail.');
      }, 'button');
      approve.disabled = true;
      checkbox.addEventListener('change', () => { approve.disabled = busy || !checkbox.checked; });
      add(body, confirmation, approve);
    } else if (decidable) body.append(el('p', 'This proposal cannot be approved. Review the findings; no journal has been posted.', 'findings'));
    if (decidable) {
      const form = el('form', null, 'reject-form');
      const id = 'reason-' + draft.draft_id;
      const label = el('label', 'Reject with a recorded reason', 'field-label'); label.htmlFor = id;
      const reason = el('textarea'); reason.id = id; reason.required = true; reason.maxLength = 1000;
      reason.placeholder = 'Explain why this draft should not be posted…'; reason.disabled = busy;
      const reject = el('button', 'Reject draft', 'button danger small'); reject.type = 'submit'; reject.disabled = busy;
      add(form, label, reason, add(el('div', null, 'actions'), reject));
      form.addEventListener('submit', event => {
        event.preventDefault();
        if (!reason.value.trim()) { reason.setCustomValidity('Enter a reason before rejecting.'); reason.reportValidity(); return; }
        draftAction('/api/reject', {draft_id: draft.draft_id, revision: draft.revision, reason: reason.value.trim()}, 'Draft rejected. Your reason is retained with its revision history.');
      });
      reason.addEventListener('input', () => reason.setCustomValidity(''));
      body.append(form);
    }
    if (draft.audit) body.append(auditTrail(draft));
    body.append(jsonDetails('Revision history', draft.history));
    card.append(body); list.append(card);
  });
}
function auditTrail(draft) {
  const audit = draft.audit;
  const node = add(el('div', null, 'audit'), el('h3', 'Human approval → posted journal'),
    el('p', 'Journal: ' + audit.journal_id), el('p', 'Approved by: ' + audit.approval.actor_id + ' · ' + audit.approval.recorded_at),
    el('p', 'Approval identity: ' + audit.approval.approval_id), el('p', 'Posted at: ' + audit.recorded_at));
  let binding = audit.approval.binding_json;
  try { binding = JSON.parse(binding); } catch { /* Preserve the original binding if unavailable. */ }
  node.append(jsonDetails('Approval binding · evidence, policy & revision', binding));
  return node;
}
function renderLedger() {
  const node = $('ledger-content'); node.replaceChildren();
  const report = state.trial_balance;
  const card = el('section', null, 'card');
  card.append(add(el('div', null, 'card-heading'), el('h3', 'Unadjusted trial balance'), status(report.total_debits === report.total_credits ? 'balanced' : 'mismatch')));
  const body = el('div', null, 'ledger-body');
  body.append(table(['Account', 'Account name', 'Debit · USD', 'Credit · USD'],
    report.rows.map(row => [row.account, row.name, money(row.debit), money(row.credit)]),
    'All accounts · exact decimal amounts · cutoff ' + report.as_of,
    ['', 'Total', money(report.total_debits), money(report.total_credits)]));
  body.append(metadata([['Inclusive cutoff', report.as_of], ['Report policy', report.policy], ['Included journals', report.included_entry_ids.length], ['Basis', 'Recorded actuals · zero opening balances']]));
  digest(body, 'Reproducible ledger snapshot SHA-256', report.snapshot_digest);
  body.append(jsonDetails('Included journal identities', report.included_entry_ids));
  card.append(body); node.append(card);
  const posted = state.drafts.filter(draft => draft.status === 'posted');
  if (!posted.length) node.append(empty('The ledger is ready for its first entry', 'Approve a reviewed proposal to record a journal. Agent runs alone never change the books.'));
  posted.forEach(draft => {
    const entry = state.journals.find(journal => journal.id === draft.audit.journal_id);
    const journal = el('article', null, 'card');
    journal.append(add(el('div', null, 'card-heading'), el('h3', 'Posted journal · ' + draft.audit.journal_id), status('posted')));
    const content = el('div', null, 'ledger-body');
    if (entry) add(content, metadata([['Effective date', entry.effective_date], ['Description', entry.description]]), journalLines(entry.lines, 'Posted journal lines'));
    content.append(auditTrail(draft));
    for (const [id, value] of Object.entries(draft.evidence)) digest(content, 'Retained evidence · ' + id, value);
    journal.append(content); node.append(journal);
  });
}
function renderRuns() {
  const node = $('run-list'); node.replaceChildren();
  if (!state.runs.length) { node.append(empty('No agent runs yet', 'Choose a fictional receipt and explicitly prepare a proposal to start a bounded run.')); return; }
  [...state.runs].reverse().forEach(run => {
    const card = el('article', null, 'card');
    card.append(add(el('div', null, 'card-heading'), el('h3', 'Run · ' + run.run_id), status(run.state)));
    const body = el('div', null, 'run-body');
    add(body, metadata([['Evidence', run.source_id], ['Provider', run.provider.provider_version], ['Model', run.provider.model],
      ['Provider attempts', run.attempts], ['Prompt version', run.provider.prompt_version], ['Reserved cost · USD nanodollars', String(run.reserved_nanodollars)]]),
      el('p', 'Outcome: ' + human(run.reason), 'draft-reason'), jsonDetails('Recorded checkpoint trail', run.trace));
    if (!settled.has(run.state)) {
      const cancel = button('Cancel run', () => cancelRun(run.run_id), 'button danger small'); cancel.disabled = busy && !runBusy;
      body.append(cancel);
    }
    card.append(body); node.append(card);
  });
}
function renderProviders() {
  const node = $('provider-list'); node.replaceChildren();
  state.providers.forEach(provider => {
    node.append(add(el('article', null, 'card provider-card'), status(provider.available ? 'available' : 'disabled'),
      el('h3', provider.name), el('p', provider.model, 'model'), el('p', provider.note),
      el('p', provider.id === 'offline' ? 'Fixture playback · no model accuracy measured' : 'Live evaluation pending', 'action-hint')));
  });
}
document.querySelectorAll('[data-view]').forEach(node => node.addEventListener('click', () => showView(node.dataset.view, true)));
document.querySelector('.brand').addEventListener('click', event => { event.preventDefault(); showView('evidence', true); });
$('refresh').addEventListener('click', async () => {
  if (await refresh()) notify(pendingRun ? 'State refreshed. The retained run still needs recovery or cancellation.' : 'Workspace refreshed from its recorded state.');
});
setInterval(() => {
  if (!runBusy) return;
  document.querySelectorAll('.run-progress').forEach(node => {
    node.textContent = 'Preparing proposal… ' + Math.floor((Date.now() - runStarted) / 1000) + ' seconds · bounded provider request';
  });
}, 1000);
showView(activeView);
refresh().then(ok => { if (ok && pendingRun) notify('A previous run is retained. Inspect its status or recover the same run before starting another.', 'progress'); });
