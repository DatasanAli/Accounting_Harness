'use strict';

const $ = id => document.getElementById(id);
const views = {
  projects: ['Projects', 'Attribute recorded revenue and expense to projects with an exact bridge to the books.'],
  close: ['Period close', 'Review the complete January books, then explicitly close temporary balances and lock posting dates.'],
  reports: ['Reports', 'Captured income, owner’s equity, assets and the sources and uses of Cash.'],
  'revenue-accrual': ['Revenue accruals', 'Completed unbilled services and their recorded cutoff assets.'],
  'expense-accrual': ['Expense accruals', 'Supported unbilled expenses and their recorded cutoff obligations.'],
  prepaid: ['Prepaid insurance', 'Coverage, supported consumption and the remaining recorded asset.'],
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
let financialReport = null;
let cashFlowReport = null;
let capturingCashFlow = false;
let closePreview = null;
let closeBusy = false;
let closeSelections = [];
let pendingClose = null;
let capturingFinancialReport = false;
let bankDetail = null;
let bankMatchView = null;
let reconciliationView = null;
let pendingReconciliation = null;
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
  renderSources(); renderCashChoices(); renderDrafts(); renderLedger(); renderFinancialReports(); renderClose(); renderPayables(); renderReceivables(); renderAdvances(); renderPrepaid(); renderExpenseAccruals(); renderRevenueAccruals(); renderBank(); renderRuns(); renderProviders();
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
  for (const [id, kinds] of [['revenue-accrual-completion-select', ['service_completion']], ['revenue-accrual-basis-select', ['revenue_accrual_basis']], ['expense-accrual-incurrence-select', ['incurred_expense']], ['expense-accrual-basis-select', ['expense_accrual_basis']], ['prepaid-coverage-select', ['prepaid_coverage']], ['cash-source-select', ['cash_movement']],
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
  renderReconciliation(node);
  renderBankMatches(node);
}
async function loadBankMatches() {
  bankMatchView = null;
  reconciliationView = null;
  bankMatchView = await request('/api/bank-matches?' + new URLSearchParams({bank_account_id: bankDetail.statement.bank_account_id}));
  reconciliationView = await request('/api/bank-reconciliation?' + new URLSearchParams({bank_account_id: bankDetail.statement.bank_account_id, statement_id: bankDetail.statement.statement_id}));
}
async function reconciliationAction(action, payload) {
  if (busy) return;
  pendingReconciliation = {action, payload};
  busy = true; renderBank();
  try {
    const receipt = await request('/api/' + action, payload);
    pendingReconciliation = null;
    notify((action === 'bank-reconcile' ? 'Reconciliation completed. ' : 'Timing review recorded. ') +
      'Ledger unchanged. Reference: ' + (receipt.completion_id || receipt.event_id));
    await refresh();
  } catch (error) {
    if (!error.uncertain) pendingReconciliation = null;
    notify(error.message + ' Refresh and review the exact current report.', 'error');
    await refresh();
  } finally { busy = false; renderBank(); }
}
function renderReconciliation(node) {
  if (!reconciliationView || reconciliationView.report.statement_id !== bankDetail.statement.statement_id) return;
  const {report, completions} = reconciliationView;
  const card = el('section', null, 'card draft-body');
  card.append(el('h3', 'Bank-to-book reconciliation'), el('p',
    'Review each existing cash movement at the statement cutoff, then confirm the exact report. Timing review creates no journal.'));
  card.append(metadata([['Statement period', report.period_start + ' through ' + report.cutoff],
    ['Bank account', report.bank_account_id], ['Ledger account', report.ledger_account + ' · ' + report.ledger_account_name],
    ['Report policy', report.policy]]));
  card.append(table(['Book bridge · USD', 'Amount'], [
    ['Book before linked fee adjustments (derived)', report.original_book_balance],
    ['Linked reviewed fee adjustments', report.book_adjustments_total],
    ['Captured book Cash at cutoff', report.book_balance]], 'Captured book balance and reviewed adjustments'));
  card.append(table(['Bank bridge · USD', 'Amount'], [
    ['Statement closing', report.bank_closing], ['Add deposits in transit', report.deposits_in_transit],
    ['Subtract outstanding payments', report.outstanding_payments], ['Adjusted bank', report.adjusted_bank_balance],
    ['Unexplained difference · book minus adjusted bank', report.unexplained_difference]], 'Statement balance and timing differences'));
  if (report.book_adjustments.length) card.append(table(['Adjustment journal', 'Bank transaction', 'Evidence', 'Amount · USD'],
    report.book_adjustments.map(item => [item.journal_id, item.transaction_id, item.source_id, item.amount]), 'Reviewed book adjustments'));
  if (report.matches.length) card.append(table(['Matched bank row', 'Book journal', 'Match confirmation', 'Amount · USD'],
    report.matches.map(item => [item.transaction_id, item.book.journal_id, item.match.event_id, item.book.amount]), 'Cleared cash movements at cutoff'));
  const base = () => ({bank_account_id: report.bank_account_id, statement_id: report.statement_id,
    binding: report.digest, idempotency_key: crypto.randomUUID()});
  const timingForm = (item, role, label) => {
    const form = el('form', null, 'stack');
    const reasonLabel = el('label', 'Review reason for ' + item.journal_id);
    const reason = el('input'); reason.type = 'text'; reason.required = true; reason.maxLength = 1000;
    reasonLabel.append(reason);
    const submit = el('button', label, 'button secondary'); submit.type = 'submit'; submit.disabled = busy;
    form.append(reasonLabel, submit);
    form.addEventListener('submit', event => {
      event.preventDefault();
      if (!reason.value.trim()) return;
      reconciliationAction('bank-timing', {...base(), journal_id: item.journal_id, role, reason: reason.value});
    });
    return form;
  };
  for (const item of report.timing_items) {
    const block = el('section', null, 'card');
    block.append(el('h4', (item.role === 'deposit_in_transit' ? 'Deposit in transit · ' : 'Outstanding payment · ') + item.amount + ' USD'),
      metadata([['Book journal', item.journal_id], ['Effective date', item.effective_date], ['Evidence', item.source_ids.join(', ')],
        ['Reviewed by', item.review.actor_id], ['Reason', item.review.reason], ['Review reference', item.review.event_id]]),
      timingForm(item, 'withdraw', 'Withdraw timing classification'));
    card.append(block);
  }
  if (report.eligible_timing.length) card.append(el('h4', 'Cash movements requiring timing review'));
  for (const item of report.eligible_timing) {
    const block = el('section', null, 'card');
    block.append(metadata([['Book journal', item.journal_id], ['Effective date', item.effective_date],
      ['Amount · USD', item.amount], ['Evidence', item.source_ids.join(', ')]]),
      timingForm(item, item.role, item.role === 'deposit_in_transit' ? 'Confirm deposit in transit' : 'Confirm outstanding payment'));
    card.append(block);
  }
  for (const item of report.timing_exceptions) {
    card.append(el('p', 'Timing exception · ' + item.event.journal_id + ': ' + item.reason),
      timingForm(item.event, 'withdraw', 'Withdraw invalid timing classification'));
  }
  for (const item of report.bank_exceptions) card.append(el('p', 'Bank exception · ' + item.transaction_id + ': ' + item.reason));
  for (const item of report.book_exceptions.filter(item => item.reason)) card.append(el('p', 'Book exception · ' + item.journal_id + ': ' + item.reason));
  digest(card, 'Exact report SHA-256', report.digest);
  digest(card, 'Ledger snapshot SHA-256', report.ledger_snapshot_digest);
  card.append(el('p', report.can_complete ? 'Both balances agree and all applicable movements are explained. Review and explicitly complete below.' :
    'Completion blocked: resolve the unexplained difference and every bank, book or timing exception.'));
  const label = el('label', null, 'check-label');
  const confirmed = el('input'); confirmed.type = 'checkbox'; confirmed.disabled = busy || !report.can_complete;
  label.append(confirmed, document.createTextNode(' I reviewed the exact report, references and timing classifications.'));
  const complete = button('Complete this reconciliation', () => reconciliationAction('bank-reconcile', base()));
  complete.disabled = true;
  confirmed.addEventListener('change', () => { complete.disabled = busy || !report.can_complete || !confirmed.checked; });
  card.append(label, complete);
  if (pendingReconciliation) {
    const retry = button('Retry original reconciliation action', () => reconciliationAction(pendingReconciliation.action, pendingReconciliation.payload));
    retry.disabled = busy; card.append(retry);
  }
  for (const item of completions) {
    const completion = item.completion;
    card.append(add(el('details'), el('summary', 'Completed by ' + completion.actor_id + ' · ' + completion.recorded_at +
      (item.current_state_drift ? ' · Current state has changed; historical completion preserved' : ' · Current state agrees')),
      el('pre', JSON.stringify(completion, null, 2))));
  }
  card.append(add(el('details'), el('summary', 'Captured statement, ledger, matching, timing and report evidence'),
    el('pre', JSON.stringify(reconciliationView, null, 2))));
  node.append(card);
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
function signedMoney(value) {
  return typeof value === 'string' && value.startsWith('-') ? '-' + money(value.slice(1)) : money(value);
}
function financialAccount(row) {
  const node = add(el('details'), el('summary', row.account + ' · ' + row.name + ' · ' + signedMoney(row.amount)));
  node.append(table(['Date', 'Journal', 'Net contribution · USD'], row.drilldown.map(line => [
    line.effective_date, line.journal_id, signedMoney(line.amount)
  ]), 'Contributing journal lines · ' + row.name, ['', 'Account total', signedMoney(row.amount)]));
  for (const line of row.drilldown) {
    node.append(add(el('details'), el('summary', line.journal_id + ' · line ' + line.line_number + ' · evidence & posting'),
      metadata([['Effective date', line.effective_date], ['Recorded at', line.recorded_at], ['Actor', line.actor_id],
        ['Classification', line.classification], ['Posted side', line.side], ['Posted amount', money(line.posted_amount)],
        ['Original journal', line.original_entry_id || '—'], ['Source references', line.source_ids.join(', ')]]),
      el('p', line.description)));
  }
  if (!row.drilldown.length) node.append(el('p', 'No included activity for this account.'));
  return node;
}
function renderFinancialReports() {
  renderCashFlow();
  const node = $('financial-reports'); node.replaceChildren();
  $('capture-financial-report').disabled = capturingFinancialReport;
  if (!financialReport) {
    node.append(empty('Choose a cutoff and capture the books', 'Review all linked statements, then expand any account to inspect its journal and evidence references.'));
    return;
  }
  const report = financialReport;
  const capture = add(el('div', null, 'card setup-card'), el('h3', 'Captured books · through ' + report.as_of),
    metadata([['Entity', report.entity_id], ['Period start', report.period_start], ['Inclusive cutoff', report.as_of],
      ['Included journals', report.included_journal_ids.length], ['Basis', report.policy.basis],
      ['Equity model', 'Owner capital and drawings'], ['Policy', report.policy.version]]));
  digest(capture, 'Common snapshot SHA-256', report.snapshot_digest);
  capture.append(jsonDetails('Captured account catalog and journal identities', {
    catalog: report.catalog, included_journal_ids: report.included_journal_ids,
    excluded_closing_journal_ids: report.excluded_closing_journal_ids, policy: report.policy,
    policy_digest: report.policy_digest, report_digest: report.report_digest}));
  node.append(capture);
  const choice = $('financial-statement').value;
  for (const [key,title] of [['income_statement','Income statement'],['owners_equity','Owner’s equity'],['balance_sheet','Balance sheet']]) {
    if (choice !== 'all' && choice !== key) continue;
    const statement = report[key];
    const card = add(el('article', null, 'card'), add(el('div', null, 'card-heading'), el('h3', title)));
    const body = el('div', null, 'ledger-body');
    if (key === 'income_statement') {
      body.append(metadata([['Revenue', signedMoney(statement.revenue_amount)], ['Expenses', signedMoney(statement.expenses_amount)],
        ['Net income / loss', signedMoney(statement.net_income_amount)]]));
      for (const [label,rows] of [['Revenue accounts',statement.revenue],['Expense accounts',statement.expenses]]) {
        body.append(el('h4', label)); rows.forEach(row => body.append(financialAccount(row)));
      }
    } else if (key === 'owners_equity') {
      body.append(metadata([['Opening capital', signedMoney(statement.opening_capital_amount)],
        ['Net contributions / withdrawals', signedMoney(statement.contributions_amount)], ['Current-period income / loss', signedMoney(statement.net_income_amount)],
        ['Less net drawings / returns', signedMoney(statement.drawings_amount)], ['Ending owner’s equity', signedMoney(statement.ending_equity_amount)]]),
        financialAccount(statement.contributions), financialAccount(statement.drawings));
      body.append(el('p', 'Current-period income comes from the linked income statement.', 'action-hint'));
    } else {
      body.append(metadata([['Assets', signedMoney(statement.assets_amount)], ['Liabilities', signedMoney(statement.liabilities_amount)],
        ['Owner’s equity', signedMoney(statement.equity_amount)], ['Equation residual', signedMoney(statement.residual_amount)]]),
        status(statement.reconciled ? 'reconciled' : 'failed'));
      body.append(el('p', statement.reconciled ? 'Assets equal liabilities plus linked owner’s equity.' : 'The accounting equation does not reconcile. Inspect the signed residual.', 'action-hint'));
      for (const [label,rows] of [['Asset accounts',statement.assets],['Liability accounts',statement.liabilities]]) {
        body.append(el('h4', label)); rows.forEach(row => body.append(financialAccount(row)));
      }
    }
    body.append(jsonDetails('Statement identity and cross-links', {snapshot_digest: statement.snapshot_digest,
      policy_digest: statement.policy_digest, report_digest: statement.report_digest,
      income_statement_digest: statement.income_statement_digest, owners_equity_digest: statement.owners_equity_digest}));
    card.append(body); node.append(card);
  }
}
$('financial-report-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (capturingFinancialReport) return;
  const cutoff = $('financial-cutoff').value;
  capturingFinancialReport = true; renderFinancialReports();
  try {
    financialReport = await request('/api/financial-statements?as_of=' + encodeURIComponent(cutoff));
    notify('Statements captured through ' + financialReport.as_of + '. Expand an account to inspect its contributing journals.');
  } catch (error) { notify('Unable to capture statements: ' + error.message + ' The previous capture remains displayed.', 'error'); }
  finally { capturingFinancialReport = false; renderFinancialReports(); }
});
$('financial-statement').addEventListener('change', renderFinancialReports);

$('cash-flow-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (capturingCashFlow) return;
  capturingCashFlow = true; renderCashFlow();
  try {
    cashFlowReport = await request('/api/cash-flow?as_of=' + encodeURIComponent($('cash-flow-cutoff').value));
    notify('Cash flow captured through ' + cashFlowReport.as_of + '. Expand a cash movement for its evidence and classification.');
  } catch (error) { notify('Unable to capture cash flow: ' + error.message + ' The previous capture remains displayed.', 'error'); }
  finally { capturingCashFlow = false; renderCashFlow(); }
});
function renderCashFlow() {
  const node = $('cash-flow-report'); node.replaceChildren();
  $('capture-cash-flow').disabled = capturingCashFlow;
  if (!cashFlowReport) return;
  const report = cashFlowReport;
  const card = add(el('article', null, 'card setup-card'), el('h3', 'Direct cash flow · through ' + report.as_of),
    metadata([['Period start', report.period_start], ['Inclusive cutoff', report.as_of], ['Currency', report.currency],
      ['Opening Cash', signedMoney(report.opening_cash_amount)], ['Operating receipts', signedMoney(report.operating_receipts_amount)],
      ['Operating payments', signedMoney(report.operating_payments_amount)], ['Net operating cash', signedMoney(report.operating_amount)],
      ['Net investing cash', signedMoney(report.investing_amount)], ['Net financing cash', signedMoney(report.financing_amount)],
      ['Unresolved cash', signedMoney(report.unresolved_amount)], ['Net cash change', signedMoney(report.net_change_amount)],
      ['Ending ledger Cash', signedMoney(report.ending_cash_amount)], ['Bridge residual', signedMoney(report.residual_amount)]]),
    el('p', report.reconciled ? 'Cash bridge reconciles to the captured ledger.' : 'Cash bridge does not reconcile.', 'action-hint'),
    status(report.classification_complete ? 'complete' : 'failed'),
    el('p', report.classification_complete ? 'Classification complete under the displayed policy.' : 'Classification incomplete. Resolve every exception, including movements that net to zero.'));
  for (const exception of report.exceptions) card.append(el('p', exception.journal_id + ': ' + exception.message + ' Cash ' + signedMoney(exception.cash_amount), 'error'));
  for (const [category, title] of [['operating', 'Operating'], ['investing', 'Investing'], ['financing', 'Financing'], ['unresolved', 'Unresolved']]) {
    card.append(el('h4', title + ' · ' + signedMoney(report[category + '_amount'])));
    const rows = report.rows.filter(row => row.category === category);
    if (!rows.length) card.append(el('p', 'No included cash movements.'));
    for (const row of rows) {
      const details = add(el('details'), el('summary', row.effective_date + ' · ' + row.journal_id + ' · ' + signedMoney(row.cash_amount)),
        metadata([['Cash movement', signedMoney(row.cash_amount)], ['Category', row.category], ['Actor', row.actor_id],
          ['Recorded at', row.recorded_at], ['Journal classification', row.classification], ['Original journal', row.original_entry_id || '—'],
          ['Source references', row.source_ids.join(', ')]]), el('p', row.description),
        table(['Account', 'Side', 'Posted amount · USD'], [...row.cash_lines, ...row.counterparts].map(line =>
          [line.account, line.side, money(line.posted_amount)]), 'Cash and counterpart lines'));
      if (row.exception) details.append(el('p', row.exception, 'error'));
      if (row.payable_trace) details.append(jsonDetails('Captured approved payment and underlying bill evidence', row.payable_trace));
      details.append(jsonDetails('Captured journal and source trace', row));
      card.append(details);
    }
  }
  digest(card, 'Cash-flow snapshot SHA-256', report.snapshot_digest);
  digest(card, 'Financial snapshot SHA-256', report.financial_snapshot_digest);
  card.append(jsonDetails('Captured policy, journal classifications and report identity', {policy: report.policy,
    policy_digest: report.policy_digest, report_digest: report.report_digest,
    included_journal_ids: report.included_journal_ids, excluded_closing_journal_ids: report.excluded_closing_journal_ids}));
  node.append(card);
}


async function captureClose() {
  if (closeBusy) return;
  closeBusy = true; renderClose();
  try {
    closePreview = await request('/api/close-preview', {period_start: '2026-01-01', period_end: '2026-01-31', selections: closeSelections});
    pendingClose = null;
    notify(closePreview.can_close ? 'Close preview captured. Review the statements and closing lines before confirmation.' : 'Close is blocked. Resolve the readiness findings and capture again.');
  } catch (error) { notify(error.message, 'error'); }
  finally { closeBusy = false; renderClose(); }
}
async function confirmClose() {
  if (closeBusy || !closePreview) return;
  closeBusy = true;
  pendingClose ??= {period_start: closePreview.period_start, period_end: closePreview.period_end,
    selections: closePreview.selections, confirmed_digest: closePreview.digest, confirmed: true, idempotency_key: crypto.randomUUID()};
  renderClose();
  try {
    const result = await request('/api/close-confirm', pendingClose);
    state.period_close = result; pendingClose = null;
    notify('January is closed. Posting dates are locked; statements and the complete approval trace remain available.');
    await refresh();
  } catch (error) {
    if (!error.uncertain) pendingClose = null;
    notify(error.message + (error.uncertain ? ' Retry the same confirmation or Refresh to inspect the recorded outcome.' : ' Capture a new preview if the books changed.'), 'error');
  } finally { closeBusy = false; renderClose(); }
}
function renderClose() {
  const node = $('close-content'); node.replaceChildren();
  const recorded = state.period_close;
  if (recorded) {
    const card = add(el('div', null, 'card setup-card'), el('h3', 'January 2026 · Closed and locked'),
      metadata([['Locked dates', recorded.period_start + ' through ' + recorded.period_end], ['Confirmed by', recorded.actor_id],
        ['Recorded at', recorded.recorded_at], ['Closing journal', recorded.journal_id || 'No entry · all temporary balances were zero'],
        ['Approval', recorded.approval_id]]),
      el('p', 'Read access remains available. Reopening and prior-period corrections require a later audited policy and are unavailable here.'));
    digest(card, 'Confirmed preview SHA-256', recorded.confirmed_digest);
    card.append(jsonDetails('Complete close, approval, captured statements and evidence trace', recorded));
    node.append(card);
    const preview = recorded.preview;
    node.append(closeSummary(preview));
    return;
  }
  const setup = add(el('div', null, 'card setup-card'), el('h3', 'Prepare the complete January close'),
    el('p', 'Temporary revenue, expense and drawings balances transfer to Owner Capital. Permanent asset and liability balances stay open.'));
  const accounts = [...new Set(state.bank_statements.filter(s => s.period_start <= '2026-01-01' && s.period_end >= '2026-01-31').map(s => s.bank_account_id))];
  for (const account of accounts) {
    const label = el('label', 'Statement and completion for ' + account + ' ');
    const select = el('select'); select.setAttribute('aria-label', 'Statement for ' + account);
    select.append(new Option('Choose a statement explicitly', ''));
    state.bank_statements.filter(s => s.bank_account_id === account && s.period_start <= '2026-01-01' && s.period_end >= '2026-01-31').forEach(s => select.append(new Option(s.statement_id, s.statement_id)));
    const selected = closeSelections.find(s => s.bank_account_id === account);
    select.value = selected?.statement_id || ''; select.disabled = closeBusy;
    select.addEventListener('change', async () => {
      closeSelections = closeSelections.filter(s => s.bank_account_id !== account); closePreview = null; pendingClose = null;
      if (!select.value) { renderClose(); return; }
      try {
        const view = await request('/api/bank-reconciliation?bank_account_id=' + encodeURIComponent(account) + '&statement_id=' + encodeURIComponent(select.value));
        const choices = add(el('div'), el('p', 'Select a recorded completion for ' + select.value + ':'));
        if (!view.completions.length) choices.append(el('p', 'No recorded completion. Resolve and complete this reconciliation in Bank statements first.'));
        for (const item of view.completions) {
          choices.append(button(item.completion.completion_id + (item.current_state_drift ? ' · stale' : ' · current'), () => {
            closeSelections.push({bank_account_id: account, statement_id: select.value, completion_id: item.completion.completion_id});
            renderClose();
          }));
        }
        label.append(choices);
      } catch (error) { notify(error.message, 'error'); }
    });
    label.append(select);
    if (selected) label.append(el('p', 'Selected completion: ' + selected.completion_id, 'digest'));
    setup.append(label);
  }
  const capture = button('Capture close preview', captureClose); capture.disabled = closeBusy;
  setup.append(capture); node.append(setup);
  if (!closePreview) return;
  node.append(closeSummary(closePreview));
  const confirmation = add(el('div', null, 'card setup-card'), el('h3', 'Separate human confirmation'),
    el('p', 'Close and lock prevents all later postings and reversals dated January 1–31. Reopening and prior-period corrections are unavailable until a later audited policy. The books and original statements remain readable.'));
  for (const finding of closePreview.findings) confirmation.append(el('p', finding, 'message error'));
  digest(confirmation, 'Exact preview SHA-256', closePreview.digest);
  const label = el('label'); const check = el('input'); check.type = 'checkbox';
  check.disabled = closeBusy || !closePreview.can_close;
  label.append(check, document.createTextNode(' I reviewed these captured statements, temporary balances, evidence and exact closing journal.'));
  const confirm = button(pendingClose ? 'Retry same close confirmation' : 'Close and lock January', confirmClose, 'button');
  confirm.disabled = closeBusy || !closePreview.can_close || !pendingClose;
  check.addEventListener('change', () => { confirm.disabled = closeBusy || !closePreview.can_close || !check.checked; });
  confirmation.append(label, confirm); node.append(confirmation);
}
function closeSummary(preview) {
  const statements = preview.statements;
  const card = add(el('div', null, 'card setup-card'), el('h3', 'Captured close calculation'),
    metadata([['Period', preview.period_start + ' through ' + preview.period_end], ['Closing effective date', preview.effective_date],
      ['Net income / loss', signedMoney(statements.income_statement.net_income_amount)],
      ['Ending owner’s equity', signedMoney(statements.owners_equity.ending_equity_amount)],
      ['Assets', signedMoney(statements.balance_sheet.assets_amount)], ['Liabilities', signedMoney(statements.balance_sheet.liabilities_amount)],
      ['Capital transfer', signedMoney(preview.capital_transfer_amount)], ['Policy', preview.policy]]),
    table(['Temporary account', 'Name', 'Net debit · USD'], preview.temporary_balances.map(r => [r.account, r.name, r.amount]), 'Signed balances to clear'));
  if (preview.journal) card.append(journalLines(preview.journal.lines, 'Exact proposed closing journal · January 31'));
  else card.append(el('p', 'No closing journal is needed: every temporary balance is zero. Confirmation still records an audited close and date lock.'));
  for (const [key,title] of [['income_statement','Pre-close income statement'],['owners_equity','Pre-close owner’s equity'],['balance_sheet','Pre-close balance sheet']]) {
    const statement = statements[key];
    const details = add(el('details'), el('summary', title));
    const rows = key === 'income_statement' ? [...statement.revenue, ...statement.expenses] : key === 'owners_equity' ? [statement.contributions, statement.drawings] : [...statement.assets, ...statement.liabilities];
    rows.forEach(row => details.append(financialAccount(row)));
    details.append(jsonDetails('Captured statement and cross-links', statement)); card.append(details);
  }
  digest(card, 'Ledger snapshot SHA-256', statements.snapshot_digest);
  card.append(jsonDetails('Readiness and overlapping bank statements', preview.readiness),
    jsonDetails('Input journals and source references', {journal_ids: preview.journal_ids, source_ids: preview.source_ids}),
    jsonDetails('Generated calculation evidence · no posting permission', preview.artifact));
  return card;
}

function renderLedger() {
  const node = $('ledger-content'); node.replaceChildren();
  const report = state.trial_balance;
  const card = el('section', null, 'card');
  card.append(add(el('div', null, 'card-heading'), el('h3', state.period_close ? 'Post-close trial balance' : 'Trial balance'), status(report.total_debits === report.total_credits ? 'balanced' : 'mismatch')));
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

$('prepaid-coverage-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy || !state) return;
  const document = {...Object.fromEntries(new FormData(event.target)), schema_version: 2, synthetic: true,
    entity_id: state.entity_id, currency: 'USD', kind: 'prepaid_coverage', allocation_policy: 'equal-months-cents-v1'};
  busy = true; render();
  try {
    await request('/api/operation-sources', {document});
    await refresh(); $('prepaid-coverage-select').value = document.document_id; $('prepaid-proposal-panel').open = true;
    notify('Coverage registered. Prepare the supported monthly allocation, then confirm it separately in review.');
  } catch (error) { await refresh(); notify(error.message, 'error'); }
  finally { busy = false; render(); }
});
$('prepaid-proposal-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy || !state) return;
  const payload = Object.fromEntries(new FormData(event.target));
  payload.expected_revision = Number(payload.expected_revision);
  busy = true; render();
  try {
    const result = await request('/api/prepaid-proposals', payload);
    await refresh();
    if (result.state === 'no_journal_required') notify('This month allocates 0.00 USD. No journal is required.');
    else { showView('review', true); notify('Consumption draft prepared. Confirm the exact revision separately after reviewing its evidence.'); }
  } catch (error) { await refresh(); notify(error.message, 'error'); }
  finally { busy = false; render(); }
});
function renderPrepaid() {
  const node = $('prepaid-report'); node.replaceChildren();
  const report = state.prepaid;
  node.append(add(el('div', null, 'card'), el('h3', 'Remaining insurance asset'),
    metadata([['Principal', money(report.principal_amount)], ['Supported consumption', money(report.consumed_amount)],
      ['Supported remainder', money(report.remaining_amount)], ['1200 control balance', report.control_amount + ' USD'],
      ['Unassigned control residual', report.unassigned_control_amount + ' USD']]),
    el('p', 'An unrelated account movement is shown in the residual and does not count as supported policy consumption.', 'action-hint')));
  if (!report.policies.length) node.append(empty('No prepared coverage policies', 'Register coverage for an existing posted purchase and prepare its monthly allocation.'));
  for (const policy of report.policies) {
    const card = add(el('article', null, 'card'), el('h3', policy.coverage_source_id),
      metadata([['Original journal', policy.original_journal_id], ['Coverage', policy.coverage_start + ' to ' + policy.coverage_end],
        ['Principal', money(policy.principal_amount)], ['Consumed', money(policy.consumed_amount)], ['Remaining', money(policy.remaining_amount)]]));
    for (const item of policy.allocations) card.append(el('p', item.effective_date + ' · Posted journal ' + item.journal_id));
    card.append(add(el('details'), el('summary', 'Coverage, allocation and approval trace'), el('pre', policy.trace_json)));
    node.append(card);
  }
  node.append(el('p', report.report_policy + ' · Snapshot ' + report.snapshot_digest, 'action-hint'));
}

$('expense-accrual-facts-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy || !state) return;
  const input = Object.fromEntries(new FormData(event.target));
  if (input.incurrence_source_id === input.basis_source_id) {
    notify('Incurrence and cutoff basis require distinct document IDs.', 'error'); return;
  }
  const common = {schema_version: 2, synthetic: true, entity_id: state.entity_id, currency: 'USD',
    event_id: input.event_id, counterparty_id: input.counterparty_id, counterparty: input.counterparty, amount: input.amount};
  const incurrence = {...common, document_id: input.incurrence_source_id, kind: 'incurred_expense',
    document_date: input.incurred_date, incurred_date: input.incurred_date,
    expense_account: input.expense_account, description: input.incurrence_description};
  const basis = {...common, document_id: input.basis_source_id, kind: 'expense_accrual_basis',
    document_date: '2026-01-31', cutoff_date: '2026-01-31', status: 'unbilled_unpaid', description: input.basis_description};
  busy = true; render();
  try {
    await request('/api/operation-sources', {document: incurrence});
    await request('/api/operation-sources', {document: basis});
    await refresh();
    $('expense-accrual-incurrence-select').value = incurrence.document_id;
    $('expense-accrual-basis-select').value = basis.document_id;
    $('expense-accrual-proposal-panel').open = true;
    notify('Both expense facts registered. Prepare the supported accrual, then review and confirm it separately.');
  } catch (error) { await refresh(); notify(error.message + ' Resubmit the same facts to recover any pending enrollment.', 'error'); }
  finally { busy = false; render(); }
});
$('expense-accrual-proposal-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy || !state) return;
  const payload = Object.fromEntries(new FormData(event.target));
  payload.expected_revision = Number(payload.expected_revision);
  busy = true; render();
  try {
    await request('/api/expense-accrual-proposals', payload);
    await refresh(); showView('review', true);
    notify('Expense accrual draft prepared. Review its two sources and confirm the exact January 31 journal separately.');
  } catch (error) { await refresh(); notify(error.message, 'error'); }
  finally { busy = false; render(); }
});
function renderExpenseAccruals() {
  const node = $('expense-accrual-report'); node.replaceChildren();
  const report = state.expense_accruals;
  node.append(add(el('div', null, 'card'), el('h3', 'Recognized unbilled obligations'),
    metadata([['Supported accruals', money(report.principal_amount)], ['2050 control', report.control_amount + ' USD'],
      ['Unassigned control residual', report.unassigned_control_amount + ' USD'], ['Cutoff', report.as_of]])));
  if (!report.obligations.length) node.append(empty('No posted expense accruals', 'Register two supported facts, prepare a draft, and confirm it separately.'));
  for (const item of report.obligations) {
    node.append(add(el('article', null, 'card'), el('h3', item.vendor_name),
      metadata([['Vendor ID', item.vendor_id], ['Expense event', item.event_id], ['Accrued amount', money(item.principal_amount)],
        ['Expense account', item.expense_account], ['Cutoff', item.cutoff_date], ['Incurrence evidence', item.incurrence_source_id],
        ['Unbilled/unpaid evidence', item.basis_source_id], ['Posted journal', item.journal_id], ['Approval', item.approval_id]]),
      add(el('details'), el('summary', 'Evidence, exact amount and approval trace'), el('pre', item.trace_json))));
  }
  node.append(el('p', report.report_policy + ' · Snapshot ' + report.snapshot_digest + ' · Report ' + report.report_digest, 'action-hint'));
}

$('revenue-accrual-facts-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy || !state) return;
  const input = Object.fromEntries(new FormData(event.target));
  if (input.completion_source_id === input.basis_source_id) {
    notify('Completion and cutoff basis require distinct document IDs.', 'error'); return;
  }
  const common = {schema_version: 2, synthetic: true, entity_id: state.entity_id, currency: 'USD',
    event_id: input.event_id, counterparty_id: input.counterparty_id, counterparty: input.counterparty, amount: input.amount};
  const completion = {...common, document_id: input.completion_source_id, kind: 'service_completion',
    document_date: input.completion_date, completion_date: input.completion_date,
    description: input.completion_description};
  const basis = {...common, document_id: input.basis_source_id, kind: 'revenue_accrual_basis',
    document_date: '2026-01-31', cutoff_date: '2026-01-31', status: 'unbilled_uncollected', description: input.basis_description};
  busy = true; render();
  try {
    await request('/api/operation-sources', {document: completion});
    await request('/api/operation-sources', {document: basis});
    await refresh();
    $('revenue-accrual-completion-select').value = completion.document_id;
    $('revenue-accrual-basis-select').value = basis.document_id;
    $('revenue-accrual-proposal-panel').open = true;
    notify('Both revenue facts registered. Prepare the supported accrual, then review and confirm it separately.');
  } catch (error) { await refresh(); notify(error.message + ' Resubmit the same facts to recover any pending enrollment.', 'error'); }
  finally { busy = false; render(); }
});
$('revenue-accrual-proposal-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy || !state) return;
  const payload = Object.fromEntries(new FormData(event.target));
  payload.expected_revision = Number(payload.expected_revision);
  busy = true; render();
  try {
    await request('/api/revenue-accrual-proposals', payload);
    await refresh(); showView('review', true);
    notify('Revenue accrual draft prepared. Review its two sources and confirm the exact January 31 journal separately.');
  } catch (error) { await refresh(); notify(error.message, 'error'); }
  finally { busy = false; render(); }
});
function renderRevenueAccruals() {
  const node = $('revenue-accrual-report'); node.replaceChildren();
  const report = state.revenue_accruals;
  node.append(add(el('div', null, 'card'), el('h3', 'Recognized unbilled service assets'),
    metadata([['Supported accruals', money(report.principal_amount)], ['1150 control', report.control_amount + ' USD'],
      ['Unassigned control residual', report.unassigned_control_amount + ' USD'], ['Cutoff', report.as_of]])));
  if (!report.assets.length) node.append(empty('No posted revenue accruals', 'Register two supported facts, prepare a draft, and confirm it separately.'));
  for (const item of report.assets) {
    node.append(add(el('article', null, 'card'), el('h3', item.customer_name),
      metadata([['Customer ID', item.customer_id], ['Revenue event', item.event_id], ['Accrued amount', money(item.principal_amount)],
        ['Cutoff', item.cutoff_date], ['Completion evidence', item.completion_source_id],
        ['Unbilled/uncollected evidence', item.basis_source_id], ['Posted journal', item.journal_id], ['Approval', item.approval_id]]),
      add(el('details'), el('summary', 'Evidence, exact amount and approval trace'), el('pre', item.trace_json))));
  }
  node.append(el('p', report.report_policy + ' · Snapshot ' + report.snapshot_digest + ' · Report ' + report.report_digest, 'action-hint'));
}


$('report-export-form').addEventListener('submit', async event => {
  event.preventDefault();
  const button = $('download-reports');
  button.disabled = true;
  $('report-export-status').textContent = 'Capturing linked reports…';
  try {
    const kind = $('report-export-format').value;
    const query = new URLSearchParams({as_of: $('report-export-cutoff').value, format: kind});
    const response = await fetch('/api/report-export?' + query);
    if (!response.ok) throw new Error((await response.json()).error || 'Download failed');
    const blob = await response.blob();
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    link.href = url;
    link.download = kind === 'json' ? 'report.json' : 'reports.zip';
    document.body.appendChild(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    $('report-export-status').textContent = 'Downloaded ' + link.download + ' · Package ' + response.headers.get('X-Report-Package-Digest');
  } catch (error) {
    $('report-export-status').textContent = 'Unable to download reports: ' + error.message;
  } finally { button.disabled = false; }
});

let projectReport = null;
let pendingAttribution = null;
let attributionUncertain = false;
let attributionBusy = false;
function projectCentsAmount(value) {
  const cents = BigInt(value), absolute = cents < 0n ? -cents : cents;
  return (cents < 0n ? '-' : '') + (absolute / 100n).toString() + '.' + (absolute % 100n).toString().padStart(2, '0');
}
function projectSelectedSource() { return projectReport?.sources[$('project-source').value]; }
function projectField(title, input) { return add(el('label', title), input); }
function projectOptions(values, current) {
  const select = el('select');
  for (const [value, title] of values) { const option = el('option', title); option.value = value; select.append(option); }
  if (current !== undefined) select.value = current;
  return select;
}
function addProjectAllocation(portion = null) {
  const rows = $('project-allocation-rows');
  if (!projectReport || rows.children.length >= 100) return;
  const row = el('div', null, 'project-allocation-row');
  const project = projectOptions(projectReport.projects.map(p => [p.project_id, p.name + ' · ' + p.project_id]), portion?.project_id);
  project.name = 'project_id'; project.required = true;
  const customer = el('select'); customer.name = 'customer_id';
  const updateCustomer = () => {
    customer.replaceChildren();
    const none = el('option', 'Unassigned customer'); none.value = ''; customer.append(none);
    const selected = projectReport.projects.find(p => p.project_id === project.value);
    if (selected?.customer_id) { const option = el('option', selected.customer_id); option.value = selected.customer_id; customer.append(option); }
  };
  updateCustomer(); if (portion?.customer_id) customer.value = portion.customer_id;
  project.addEventListener('change', updateCustomer);
  const amount = el('input'); amount.name = 'amount'; amount.required = true; amount.inputMode = 'decimal';
  amount.pattern = '[0-9]+\\.[0-9]{2}'; amount.maxLength = 22; amount.placeholder = '120.00';
  if (portion) amount.value = projectCentsAmount(portion.cents);
  const category = el('input'); category.name = 'category'; category.required = true; category.maxLength = 100;
  category.placeholder = 'software'; category.value = portion?.category || '';
  const behavior = projectOptions(['unclassified', 'fixed', 'variable'].map(v => [v, v]), portion?.behavior); behavior.name = 'behavior';
  const trace = projectOptions(['unclassified', 'direct', 'indirect'].map(v => [v, v]), portion?.traceability); trace.name = 'traceability';
  row.append(projectField('Project', project), projectField('Customer attribution', customer), projectField('Portion (USD)', amount),
    projectField('Cost category', category), projectField('Cost behavior', behavior), projectField('Traceability', trace),
    button('Remove allocation row', () => row.remove(), 'button secondary'));
  rows.append(row);
}
function selectProjectSource() {
  $('project-allocation-rows').replaceChildren();
  $('project-source-context').replaceChildren();
  $('project-reason').value = '';
  const source = projectSelectedSource();
  if (!source) return;
  $('project-source-context').append(metadata([['Journal', source.journal_id], ['Line', source.line_number],
    ['Account', source.account + ' · ' + source.account_name], ['Signed actual', signedMoney(source.actual_amount)],
    ['Effective date', source.effective_date], ['Evidence', source.source_ids.join(', ')],
    ['Original journal (reversal)', source.original_entry_id || 'None'], ['Current revision', source.revision_id || 'Unassigned']]),
    jsonDetails('Source and attribution audit', source));
  for (const portion of source.attribution?.allocations || []) addProjectAllocation(portion);
}
function renderProjectReport() {
  const node = $('project-report'); node.replaceChildren();
  if (!projectReport) return;
  const report = projectReport;
  const card = add(el('article', null, 'card setup-card'), el('h3', 'Captured project actuals · through ' + report.as_of),
    el('p', 'Allocated plus unallocated reproduces the same captured financial actuals. Each classification table partitions the allocated rows independently.'));
  card.append(table(['Type', 'Ledger actual · USD', 'Allocated · USD', 'Unallocated · USD', 'Residual · USD'],
    Object.entries(report.totals).map(([kind,r]) => [kind, r.actual_amount, r.allocated_amount, r.unallocated_amount, r.residual_amount]),
    report.reconciled ? 'Exact reconciliation · all accounts agree' : 'Reconciliation requires attention'));
  card.append(table(['Account', 'Ledger actual · USD', 'Allocated · USD', 'Unallocated · USD', 'Residual · USD'],
    report.accounts.map(r => [r.account + ' · ' + r.name, r.actual_amount, r.allocated_amount, r.unallocated_amount, r.residual_amount]), 'Every supported revenue and expense account'));
  card.append(table(['Project', 'Name', 'Customer reference', 'Created by'], report.projects.map(p => [p.project_id,p.name,p.customer_id || 'None',p.actor_id]), 'Immutable projects in this capture'));
  for (const [axis, title] of [['project_id','Project'],['customer_id','Customer'],['category','Cost category'],['behavior','Cost behavior'],['traceability','Traceability']]) {
    card.append(table([title, 'Revenue · USD', 'Expense · USD'],report.groups[axis].map(r => [r.key ?? 'Unassigned customer',r.revenue_amount,r.expense_amount]),
      title + ' · allocated amounts only; unallocated remains in the reconciliation above'));
  }
  const drilldown = add(el('details'), el('summary', 'Source lines, evidence and attribution revisions'));
  for (const source of report.sources) {
    const detail = add(el('details'), el('summary', source.journal_id + ' · line ' + source.line_number + ' · ' + source.account + ' · ' + signedMoney(source.actual_amount)),
      metadata([['Effective date',source.effective_date],['Evidence',source.source_ids.join(', ')],['Original journal',source.original_entry_id || 'None'],
        ['Allocated',signedMoney(source.allocated_amount)],['Unallocated',signedMoney(source.unallocated_amount)],['Revision',source.revision_id || 'Unassigned']]));
    detail.append(table(['Project','Customer','Category','Behavior','Traceability','Signed amount · USD'],
      source.allocations.map(r => [r.project_id,r.customer_id || 'Unassigned',r.category,r.behavior,r.traceability,r.signed_amount]),'Explicit portions'));
    detail.append(jsonDetails('Complete captured source and attribution audit',source)); drilldown.append(detail);
  }
  card.append(drilldown);
  digest(card, 'Management capture SHA-256',report.snapshot_digest);
  digest(card, 'Financial snapshot SHA-256',report.financial_snapshot_digest);
  digest(card, 'Project report SHA-256',report.report_digest);
  card.append(jsonDetails('Captured books, project identities, current revision IDs and policy',report.capture)); node.append(card);
}
$('project-create-form').addEventListener('submit', async event => {
  event.preventDefault(); const submit = $('create-project'); submit.disabled = true;
  try {
    const values = Object.fromEntries(new FormData(event.target));
    const result = await request('/api/projects', {...values, customer_id: values.customer_id || null, entity_id: state.entity_id});
    $('project-create-result').textContent = 'Created ' + result.project_id + ' · ' + result.recorded_at + '. Capture project actuals to include this identity.';
    event.target.reset();
  } catch (error) { notify(error.message, 'error'); }
  finally { submit.disabled = false; }
});
$('project-capture-form').addEventListener('submit', async event => {
  event.preventDefault(); if (pendingAttribution) { notify('Finish or edit the pending attribution review before capturing again.', 'error'); return; }
  $('capture-projects').disabled = true;
  try {
    projectReport = await request('/api/project-dimensions?as_of=' + encodeURIComponent($('project-cutoff').value));
    const select = $('project-source'); select.replaceChildren();
    projectReport.sources.forEach((source,index) => { const option = el('option', source.account + ' · ' + source.journal_id + ' · line ' + source.line_number + ' · ' + source.actual_amount + ' USD'); option.value = String(index); select.append(option); });
    $('project-assignment-fields').disabled = projectReport.sources.length === 0;
    selectProjectSource(); renderProjectReport(); notify('Project actuals captured. Attribution and books share the displayed snapshot.');
  } catch (error) { notify(error.message, 'error'); }
  finally { $('capture-projects').disabled = false; }
});
$('project-source').addEventListener('change', selectProjectSource);
$('add-project-allocation').addEventListener('click', () => addProjectAllocation());
$('project-assignment-form').addEventListener('submit', event => {
  event.preventDefault(); const source = projectSelectedSource(); if (!source || pendingAttribution) return;
  try {
    const allocations = Array.from($('project-allocation-rows').children).map(row => {
      const value = name => row.querySelector('[name="' + name + '"]').value;
      const amount = value('amount');
      if (!/^[0-9]+\.[0-9]{2}$/.test(amount)) throw new Error('Each portion requires an unsigned USD amount with exactly two decimal places.');
      const cents = BigInt(amount.replace('.', ''));
      if (cents <= 0n) throw new Error('Every portion must be positive. Remove a row to leave it unallocated.');
      return {project_id: value('project_id'), customer_id: value('customer_id') || null, category: value('category'), behavior: value('behavior'), traceability: value('traceability'), cents: cents.toString()};
    });
    const assigned = allocations.reduce((sum,r) => sum + BigInt(r.cents), 0n);
    const actual = BigInt(source.actual_cents), absolute = actual < 0n ? -actual : actual;
    if (assigned > absolute) throw new Error('The allocation portions exceed this posted source amount.');
    pendingAttribution = {entity_id: projectReport.entity_id, journal_id: source.journal_id, line_number: source.line_number,
      source_digest: source.source_digest, prior_revision_id: source.revision_id, reason: $('project-reason').value,
      idempotency_key: crypto.randomUUID(), allocations};
    attributionUncertain = false; $('project-assignment-fields').disabled = true;
    renderAttributionReview();
  } catch (error) { notify(error.message, 'error'); }
});
function renderAttributionReview() {
  const node = $('project-assignment-review'); node.replaceChildren();
  if (!pendingAttribution) return;
  const pending = pendingAttribution, source = projectSelectedSource();
  const sign = BigInt(source.actual_cents) < 0n ? -1n : 1n;
  const assigned = pending.allocations.reduce((sum,r) => sum + BigInt(r.cents),0n) * sign;
  node.append(el('h4','Confirm the complete replacement'),
    metadata([['Signed actual',source.actual_amount + ' USD'],['Assigned',projectCentsAmount(assigned) + ' USD'],
      ['Unallocated',projectCentsAmount(BigInt(source.actual_cents)-assigned) + ' USD'],['Reason',pending.reason]]),
    table(['Project','Customer','Category','Behavior','Traceability','Signed USD'],pending.allocations.map(r => [r.project_id,r.customer_id || 'Unassigned',r.category,r.behavior,r.traceability,projectCentsAmount(BigInt(r.cents)*sign)]),'Every row to be saved'),
    jsonDetails('Exact source binding and prior revision',pending));
  const save = button(attributionUncertain ? 'Retry same attribution confirmation' : 'Confirm and save attribution', async () => {
    if (attributionBusy) return;
    attributionBusy = true; renderAttributionReview();
    try {
      const result = await request('/api/project-assignments',pendingAttribution);
      pendingAttribution = null; attributionUncertain = false;
      $('project-assignment-result').textContent = 'Saved revision ' + result.revision_id + ' · ' + result.recorded_at + '. Displayed report remains its earlier capture. Capture again to see the new attribution.';
      notify('Attribution saved. Capture again to inspect the new reconciliation or make a correction.');
    } catch (error) { attributionUncertain = error.uncertain; notify(error.message + (attributionUncertain ? ' Retry the same confirmation to recover its recorded outcome.' : ' Edit the review, then capture current actuals if its prior revision is stale.'), 'error'); }
    finally { attributionBusy = false; renderAttributionReview(); }
  });
  save.disabled = attributionBusy;
  const edit = button('Edit allocation review', () => { pendingAttribution = null; $('project-assignment-fields').disabled = false; renderAttributionReview(); }, 'button secondary');
  edit.disabled = attributionBusy || attributionUncertain;
  node.append(add(el('div',null,'actions'),save,edit));
}

let projectTimeReport = null;
let projectTimeBusy = false;
function setProjectTimeBusy(value) {
  projectTimeBusy = value;
  $('capture-project-time').disabled = value;
  $('project-time-fields').disabled = value || !projectTimeReport?.projects.length;
  $('project-time-void-fields').disabled = value;
}
function timeClock(minute) {
  return String(Math.floor(minute / 60)).padStart(2,'0') + ':' + String(minute % 60).padStart(2,'0');
}
function renderProjectTimeReport() {
  const report = projectTimeReport, node = $('project-time-report'); node.replaceChildren();
  const card = add(el('section',null,'card'),el('h3','Captured service time · ' + report.as_of),
    el('p',report.scope,'callout'),metadata([['Active time',report.total_minutes + ' minutes · ' + report.duration],
      ['All recorded intervals',report.recorded_minutes + ' minutes'],['Voided intervals',report.voided_minutes + ' minutes'],
      ['Reconciled',report.reconciled ? 'Recorded − voided = active' : 'Review required'],['Policy',report.policy]]));
  card.append(table(['Project','Worker','Work date','Active minutes','Exact duration'],
    report.groups.map(r => [r.project_id,r.worker_id,r.work_date,r.total_minutes,r.duration]),'Active intervals by project, worker and date'));
  for (const record of report.records) {
    const detail = add(el('details'),el('summary',record.project_id + ' · ' + record.worker_id + ' · ' + record.work_date + ' · ' + record.minutes + ' minutes · ' + record.status),
      metadata([['Record ID',record.record_id],['Time event',record.time_event_id],['Interval',timeClock(record.start_minute) + '–' + timeClock(record.end_minute)],
        ['Recorded by',record.actor_id],['Recorded at',record.recorded_at],['Replaces',record.replaces_record_id || 'None'],
        ['Replacement',record.replacement_record_id || 'None']]));
    if (record.void) detail.append(metadata([['Void event',record.void.void_event_id],['Void reason',record.void.reason],
      ['Voided by',record.void.actor_id],['Voided at',record.void.recorded_at]]));
    const choose = button(record.status === 'active' ? 'Choose interval to void' : 'Use voided ID for replacement',() => {
      if (projectTimeBusy) return;
      const target = record.status === 'active' ? $('project-time-void-record') : $('project-time-replaces');
      target.value = record.record_id; target.focus();
    });
    detail.append(choose,jsonDetails('Complete captured time audit',record)); card.append(detail);
  }
  digest(card,'Time capture SHA-256',report.snapshot_digest); digest(card,'Time report SHA-256',report.report_digest);
  card.append(jsonDetails('Immutable projects, original time and void history',report.capture)); node.append(card);
}
$('project-time-capture-form').addEventListener('submit',async event => {
  event.preventDefault(); if (projectTimeBusy) return; setProjectTimeBusy(true);
  try {
    projectTimeReport = await request('/api/project-time?as_of=' + encodeURIComponent($('project-time-cutoff').value));
    const selected = $('project-time-project').value; $('project-time-project').replaceChildren();
    projectTimeReport.projects.forEach(p => $('project-time-project').append(new Option(p.name + ' · ' + p.project_id,p.project_id)));
    if (projectTimeReport.projects.some(p => p.project_id === selected)) $('project-time-project').value = selected;
    renderProjectTimeReport(); notify('Time history captured. Later entries and voids require another capture.');
  } catch (error) { notify(error.message,'error'); }
  finally { setProjectTimeBusy(false); }
});
for (const [formId,isVoid] of [['project-time-form',false],['project-time-void-form',true]]) {
  $(formId).addEventListener('submit',async event => {
    event.preventDefault(); if (projectTimeBusy) return;
    const form = event.target, values = Object.fromEntries(new FormData(form));
    let payload;
    try {
      if (isVoid) {
        payload = {entity_id:state.entity_id,record_id:values.record_id,void_event_id:values.void_event_id,reason:values.reason};
      } else {
        if (!/^\d+$/.test(values.start_minute) || !/^\d+$/.test(values.end_minute)) throw new Error('Use whole integer minutes without rounding.');
        payload = {...values,entity_id:state.entity_id,start_minute:Number(values.start_minute),end_minute:Number(values.end_minute),replaces_record_id:values.replaces_record_id || null};
      }
      setProjectTimeBusy(true);
      const result = await request(form.getAttribute('action'),payload);
      const label = isVoid ? 'Voided ' + result.record_id : result.status + ' · ' + result.record_id + ' · ' + result.minutes + ' minutes';
      $(isVoid ? 'project-time-void-result' : 'project-time-result').textContent = label + ' · ' + result.recorded_at + '. Displayed history remains its earlier capture; capture again to see the current totals.';
      if (isVoid) $('project-time-replaces').value = result.record_id;
      notify(isVoid ? 'Void recorded. Record a replacement separately with a new event ID.' : 'Time event recovered or recorded. Financial actuals are unchanged.');
    } catch (error) { notify(error.message + (error.uncertain ? ' Keep these exact fields and submit again to recover the original outcome.' : ''),'error'); }
    finally { setProjectTimeBusy(false); }
  });
}
