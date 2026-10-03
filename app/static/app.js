(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const state = {
    documents: [], current: null, invoiceIndex: 0, view: 'overview', tab: 'overview',
    health: null, queue: [], uploading: false, saving: false, deleting: false,
    dirty: false, editorBaseline: '', listLoading: true, listError: false,
    openVersion: 0, listVersion: 0, samplesLoaded: false, lastOpener: null,
  };
  const labels = { validated: 'Consistency checked', needs_review: 'Needs review', invalid: 'Invalid' };
  const supported = new Set(['pdf', 'png', 'jpg', 'jpeg', 'csv', 'xlsx']);
  const moneyFields = ['unit_price', 'discount', 'taxable_value', 'gst_rate', 'cgst_rate', 'sgst_rate', 'igst_rate', 'cgst_amount', 'sgst_amount', 'igst_amount', 'cess_amount', 'total', 'quantity'];
  const views = {
    overview: ['Overview', 'Clarity, in every invoice.', 'Turn scattered invoices into structured, reviewable GST data.'],
    documents: ['All documents', 'Every document. One clear view.', 'Find the details, follow the evidence, and keep your records in order.'],
    review: ['Needs attention', 'A closer look makes a difference.', 'Review uncertain extractions and resolve inconsistencies against the source.'],
    samples: ['Sample files', 'Try a little clarity.', 'Explore the workflow with safe, synthetic invoices in different formats.'],
  };

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function icon(name) {
    const node = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    node.classList.add('icon');
    node.setAttribute('aria-hidden', 'true');
    const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    use.setAttribute('href', `#i-${name}`);
    node.append(use);
    return node;
  }

  function describeError(data, fallback) {
    const detail = data?.detail ?? data?.error ?? data?.message;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) return detail.slice(0, 5).map((item) => {
      if (typeof item === 'string') return item;
      const location = Array.isArray(item.loc) ? item.loc.filter((part) => part !== 'body').join('.') : '';
      return `${location ? `${location}: ` : ''}${item.msg || 'Invalid value'}`;
    }).join(' · ');
    return fallback;
  }

  async function request(path, options = {}, timeout = 25000, mode = 'json') {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetch(path, { ...options, signal: controller.signal, credentials: 'same-origin', cache: 'no-store' });
      if (!response.ok) {
        let data;
        try { data = await response.json(); } catch { /* The server may return a non-JSON error page. */ }
        const error = new Error(describeError(data, `The server returned ${response.status}. Please try again.`));
        error.status = response.status;
        throw error;
      }
      if (response.status === 204) return null;
      if (mode === 'blob') return await response.blob();
      try { return await response.json(); } catch (error) {
        if (error.name === 'AbortError') throw error;
        throw new Error('The server returned an unreadable response. Please refresh and try again.');
      }
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('This request took too long. Processing may still finish on the server; refresh your documents before trying again.');
      if (error instanceof TypeError) throw new Error('The server could not be reached. Check that the local app is running and try again.');
      throw error;
    } finally {
      window.clearTimeout(timer);
    }
  }

  function toast(message, type = 'success') {
    const node = el('div', `toast toast-${type}`);
    if (type === 'error') node.setAttribute('role', 'alert');
    const close = el('button', 'icon-button');
    close.type = 'button';
    close.setAttribute('aria-label', 'Dismiss notification');
    close.append(icon('close'));
    close.addEventListener('click', () => node.remove());
    node.append(icon(type === 'error' ? 'alert' : 'check'), el('p', '', message), close);
    $('toast-stack').append(node);
    window.setTimeout(() => node.remove(), type === 'error' ? 16000 : 8000);
  }

  function formatDate(value, includeTime = false) {
    if (!value) return 'Not available';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat('en-IN', { day: '2-digit', month: 'short', year: 'numeric', ...(includeTime ? { hour: '2-digit', minute: '2-digit' } : {}) }).format(date);
  }

  function humanize(value) {
    return String(value || 'Not available').replace(/[_-]/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
  }

  function formatMoney(value, currency = 'INR') {
    if (value === null || value === undefined || value === '') return '—';
    const number = Number(value);
    if (!Number.isFinite(number)) return String(value);
    try { return new Intl.NumberFormat('en-IN', { style: 'currency', currency, minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(number); }
    catch { return `${currency} ${new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(number)}`; }
  }

  function statusBadge(status) {
    const known = Object.hasOwn(labels, status);
    return el('span', `status-badge${known ? ` status-${status}` : ''}`, known ? labels[status] : 'Unknown status');
  }

  function docPath(id = state.current?.id) { return `/api/documents/${encodeURIComponent(id)}`; }
  function extension(name) { return String(name || '').split('.').pop().toLowerCase(); }

  function fileIcon(filename) {
    const type = extension(filename);
    const node = el('span', `file-type-icon${['csv', 'xlsx', 'pdf'].includes(type) ? ` type-${type}` : ''}`);
    node.append(icon('file'));
    return node;
  }

  function summaryOf(doc) {
    return { id: doc.id, filename: doc.filename, source_type: doc.source_type, pipeline: doc.pipeline, status: doc.status,
      created_at: doc.created_at, invoice_count: doc.invoices?.length || 0, issue_count: doc.issues?.length || 0 };
  }

  function upsertDocument(doc) {
    state.documents = [summaryOf(doc), ...state.documents.filter((item) => item.id !== doc.id)];
    state.documents.sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
    renderMetrics();
    renderDocuments();
  }

  async function loadHealth() {
    $('connection-text').textContent = 'Connecting';
    $('connection').className = 'connection';
    try {
      const health = await request('/api/health');
      if (health.status !== 'ok') throw new Error('The local service is not ready yet. Please try again shortly.');
      state.health = health;
      $('connection').className = 'connection connected';
      $('connection-text').textContent = 'Local workspace online';
      $('global-error').hidden = true;
      const maxMb = health.limits?.max_upload_mb || 20;
      const maxPages = health.limits?.max_pages || 20;
      $('upload-limits').textContent = `Up to ${maxMb} MB per file · ${maxPages} pages per document · Multiple files welcome`;
      $('handwriting-hint').textContent = health.vision_configured ? 'Optional local vision model is configured' : health.ocr_available ? 'Handwriting uses local OCR fallback · Review carefully' : 'OCR unavailable · Digital PDFs and spreadsheets still work';
      $('about-runtime').textContent = `Local OCR: ${health.ocr_available ? 'available' : 'not installed'}. Local vision model: ${health.vision_configured ? health.vision_model || 'configured' : 'not configured; handwriting falls back to OCR when available'}.`;
    } catch (error) {
      state.health = null;
      $('connection').className = 'connection offline';
      $('connection-text').textContent = 'Connection unavailable';
      $('global-error').hidden = false;
      $('global-error-text').textContent = error.message;
      $('about-runtime').textContent = 'Runtime capabilities could not be checked. Reconnect to see OCR and vision-model availability.';
    }
  }

  async function loadDocuments() {
    const version = ++state.listVersion;
    state.listLoading = true;
    state.listError = false;
    $('documents-error').hidden = true;
    $('refresh-documents').disabled = true;
    renderDocuments();
    try {
      const data = await request('/api/documents');
      if (version !== state.listVersion) return;
      if (!Array.isArray(data.documents)) throw new Error('The document list was not in the expected format.');
      state.documents = data.documents.sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
      renderMetrics();
    } catch (error) {
      if (version !== state.listVersion) return;
      state.listError = true;
      $('documents-error').textContent = `${error.message} Use Refresh to try again.${state.documents.length ? ' Previously loaded documents are shown below.' : ''}`;
      $('documents-error').hidden = false;
    } finally {
      if (version === state.listVersion) {
        state.listLoading = false;
        $('refresh-documents').disabled = false;
        renderDocuments();
      }
    }
  }

  function renderMetrics() {
    const docs = state.documents;
    const attention = docs.filter((item) => item.status !== 'validated').length;
    $('metric-documents').textContent = docs.length;
    $('metric-validated').textContent = docs.filter((item) => item.status === 'validated').length;
    $('metric-review').textContent = attention;
    $('metric-invoices').textContent = docs.reduce((sum, item) => sum + (Number(item.invoice_count) || 0), 0);
    $('nav-doc-count').textContent = docs.length;
    $('nav-review-count').textContent = attention;
  }

  function renderDocuments() {
    const query = $('document-search').value.trim().toLocaleLowerCase();
    const status = $('status-filter').value;
    const docs = state.documents.filter((doc) =>
      (state.view !== 'review' || doc.status !== 'validated') &&
      (status === 'all' || doc.status === status) &&
      String(doc.filename).toLocaleLowerCase().includes(query));
    $('list-count').textContent = docs.length;
    $('document-footer-count').textContent = `${docs.length} shown · ${state.documents.length} document${state.documents.length === 1 ? '' : 's'} in this workspace`;
    $('documents-loading').hidden = !state.listLoading;
    $('documents-section').setAttribute('aria-busy', String(state.listLoading));
    $('document-table-wrap').hidden = !docs.length;
    $('documents-empty').hidden = Boolean(docs.length || state.listLoading || state.listError);
    const hasFilters = Boolean(query || status !== 'all');
    if (state.view === 'review' && !hasFilters) {
      $('empty-title').textContent = 'Nothing needs attention right now';
      $('empty-description').textContent = 'Documents with review flags or invalid records will appear here. A clean check is not legal certification.';
    } else if (hasFilters) {
      $('empty-title').textContent = 'No matching documents';
      $('empty-description').textContent = 'Try another file name or select a different status.';
    } else {
      $('empty-title').textContent = 'Your next clear picture starts here';
      $('empty-description').textContent = 'Upload an invoice to see the details, catch inconsistencies, and take the next step with confidence.';
    }
    $('empty-upload').hidden = hasFilters || state.view === 'review';
    $('try-samples').hidden = hasFilters || state.view === 'review';
    $('document-list').replaceChildren();
    for (const doc of docs) {
      const row = el('tr', state.current?.id === doc.id ? 'selected' : '');
      const nameCell = el('td');
      const open = el('button', 'document-open');
      open.type = 'button';
      open.setAttribute('aria-label', `Review ${doc.filename}`);
      const name = el('span');
      name.append(el('span', 'document-name', doc.filename), el('span', 'document-subtitle', `${humanize(doc.source_type)} · ${humanize(doc.pipeline)}`));
      open.append(fileIcon(doc.filename), name);
      open.addEventListener('click', () => openDocument(doc.id, open));
      nameCell.append(open);
      const statusCell = el('td');
      statusCell.append(statusBadge(doc.status));
      const actionCell = el('td');
      const action = el('button', 'icon-button');
      action.type = 'button';
      action.setAttribute('aria-label', `Open ${doc.filename}`);
      action.append(icon('arrow'));
      action.addEventListener('click', () => openDocument(doc.id, action));
      actionCell.append(action);
      row.append(nameCell, statusCell, el('td', '', doc.invoice_count ?? 0), el('td', '', formatDate(doc.created_at)), actionCell);
      $('document-list').append(row);
    }
  }

  function canLeaveReview() {
    if (state.saving || state.deleting) { toast('Please wait for the current change to finish.', 'error'); return false; }
    return !state.dirty || window.confirm('You have unsaved edits. Discard them and leave this document?');
  }

  function setView(view, updateHash = true) {
    if (!Object.hasOwn(views, view)) view = 'overview';
    if (view !== state.view && state.current && !canLeaveReview()) return false;
    if (view !== state.view) closeReview(false);
    state.view = view;
    const [title, heading, description] = views[view];
    $('breadcrumb-current').textContent = title;
    $('page-title').replaceChildren(document.createTextNode(heading.replace(/\.$/, '')), el('span', '', '.'));
    $('page-description').textContent = description;
    $('metrics-section').hidden = view === 'samples';
    $('intake-section').hidden = view !== 'overview';
    $('documents-section').hidden = view === 'samples';
    $('samples-section').hidden = view !== 'samples';
    $('documents-title').textContent = view === 'review' ? 'Documents needing attention' : 'Your documents';
    $('documents-subtitle').textContent = view === 'review' ? 'Review flags and invalid records, all in one place.' : 'A clear view of everything you’ve brought in.';
    $('status-filter').value = 'all';
    $('document-search').value = '';
    document.querySelectorAll('[data-view]').forEach((button) => {
      const selected = button.dataset.view === view;
      button.classList.toggle('active', selected);
      if (selected) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
    });
    if (updateHash) history.replaceState(null, '', `#${view}`);
    renderDocuments();
    closeMenu();
    if (view === 'samples') loadSamples();
    return true;
  }

  function chooseFiles() {
    if (state.uploading) { toast('Your current files are still processing. You can add more when this batch finishes.', 'error'); return; }
    if (state.view !== 'overview' && !setView('overview')) return;
    $('file-input').click();
  }

  function renderQueue() {
    $('upload-queue').hidden = !state.queue.length;
    const finished = state.queue.filter((item) => ['success', 'error'].includes(item.status)).length;
    $('queue-title').textContent = state.uploading ? `Processing files · ${finished} of ${state.queue.length} finished` : `Upload results · ${state.queue.filter((item) => item.status === 'success').length} successful, ${state.queue.filter((item) => item.status === 'error').length} unsuccessful`;
    $('queue-list').replaceChildren();
    for (const item of state.queue) {
      const row = el('li', `queue-item queue-${item.status}`);
      const text = el('div');
      text.append(el('span', 'queue-name', item.name), el('span', 'queue-detail', item.message));
      row.append(item.status === 'uploading' ? el('span', 'spinner') : icon(item.status === 'error' ? 'alert' : item.status === 'success' ? 'check' : 'clock'), text);
      if (item.documentId) {
        const open = el('button', 'text-button queue-open', 'Review');
        open.type = 'button';
        open.addEventListener('click', () => openDocument(item.documentId, open));
        row.append(open);
      }
      $('queue-list').append(row);
    }
    $('clear-queue').disabled = state.uploading;
  }

  async function uploadFiles(fileList) {
    if (!fileList?.length) return;
    if (state.uploading) { toast('Wait for the current upload batch to finish before adding more files.', 'error'); return; }
    const files = Array.from(fileList);
    const handwriting = $('handwriting').checked;
    const maxMb = state.health?.limits?.max_upload_mb || 20;
    state.queue = files.map((file) => ({ file, name: file.name, status: 'queued', message: 'Waiting to process…' }));
    state.uploading = true;
    $('file-input').disabled = true;
    $('handwriting').disabled = true;
    $('browse-files').disabled = true;
    $('header-upload').disabled = true;
    $('empty-upload').disabled = true;
    $('dropzone').setAttribute('aria-busy', 'true');
    renderQueue();
    let successful = 0;
    for (const item of state.queue) {
      if (!supported.has(extension(item.name))) {
        item.status = 'error';
        item.message = 'Unsupported format. Use PDF, PNG, JPG, CSV, or XLSX.';
        renderQueue();
        continue;
      }
      if (item.file.size > maxMb * 1024 * 1024 || item.file.size === 0) {
        item.status = 'error';
        item.message = item.file.size === 0 ? 'This file is empty. Choose a file containing invoice data.' : `This file exceeds the ${maxMb} MB limit.`;
        renderQueue();
        continue;
      }
      item.status = 'uploading';
      item.message = 'Extracting and checking… Scanned documents can take a little longer.';
      renderQueue();
      const form = new FormData();
      form.append('file', item.file);
      form.append('handwriting', String(handwriting));
      try {
        const doc = await request('/api/documents', { method: 'POST', body: form }, 180000);
        if (!doc?.id || !Array.isArray(doc.invoices)) throw new Error('The document response was incomplete. Refresh before uploading again.');
        upsertDocument(doc);
        item.status = 'success';
        item.documentId = doc.id;
        item.message = `${doc.invoices.length} record${doc.invoices.length === 1 ? '' : 's'} extracted · ${labels[doc.status] || 'Ready to review'}`;
        successful++;
      } catch (error) {
        item.status = 'error';
        item.message = error.message;
      }
      delete item.file;
      renderQueue();
    }
    state.queue.forEach((item) => delete item.file);
    state.uploading = false;
    $('file-input').disabled = false;
    $('handwriting').disabled = false;
    $('browse-files').disabled = false;
    $('header-upload').disabled = false;
    $('empty-upload').disabled = false;
    $('file-input').value = '';
    $('dropzone').setAttribute('aria-busy', 'false');
    renderQueue();
    const failed = files.length - successful;
    toast(`${successful} document${successful === 1 ? '' : 's'} added${failed ? `; ${failed} unsuccessful. See each file’s result above.` : '. Open a document to review its extracted details.'}`, failed ? 'error' : 'success');
    // Refresh also discovers uploads that completed server-side after a client timeout.
    await loadDocuments();
  }

  async function openDocument(id, opener, scroll = true) {
    if (!canLeaveReview()) return;
    const version = ++state.openVersion;
    state.current = null;
    state.dirty = false;
    state.lastOpener = opener || null;
    $('review-section').hidden = false;
    $('review-loading').hidden = false;
    $('review-content').hidden = true;
    $('review-error').hidden = true;
    $('review-title').textContent = 'Opening document…';
    $('review-meta').textContent = 'Fetching the latest extraction and review details';
    setReviewBusy(true);
    if (scroll) $('review-section').scrollIntoView({ behavior: 'smooth', block: 'start' });
    try {
      const doc = await request(docPath(id));
      if (version !== state.openVersion) return;
      if (!Array.isArray(doc.invoices) || !Array.isArray(doc.issues)) throw new Error('This document was not in the expected format.');
      state.current = doc;
      state.invoiceIndex = 0;
      state.tab = 'overview';
      renderReview();
      renderDocuments();
      if (scroll) $('review-title').focus({ preventScroll: true });
    } catch (error) {
      if (version !== state.openVersion) return;
      $('review-title').textContent = 'This document couldn’t be opened';
      $('review-meta').textContent = 'Close this panel and select the document to try again.';
      $('review-error').textContent = error.message;
      $('review-error').hidden = false;
    } finally {
      if (version === state.openVersion) {
        $('review-loading').hidden = true;
        setReviewBusy(false);
      }
    }
  }

  function closeReview(check = true) {
    if (check && !canLeaveReview()) return;
    ++state.openVersion;
    state.current = null;
    state.dirty = false;
    $('review-section').hidden = true;
    renderDocuments();
    if (check) {
      if (state.lastOpener?.isConnected) state.lastOpener.focus();
      else $('refresh-documents').focus();
    }
  }

  function setReviewBusy(busy) {
    ['save-document', 'delete-document', 'download-json', 'download-csv', 'reset-json', 'reviewer-confirmed', 'json-editor', 'invoice-select'].forEach((id) => {
      $(id).disabled = busy || !state.current;
    });
    $('review-section').setAttribute('aria-busy', String(busy));
  }

  function renderReview() {
    const doc = state.current;
    if (!doc) return;
    $('review-content').hidden = false;
    $('review-error').hidden = true;
    $('review-title').textContent = doc.filename;
    $('review-meta').textContent = `${humanize(doc.source_type)} · ${humanize(doc.pipeline)} · Added ${formatDate(doc.created_at, true)}`;
    $('review-status').replaceChildren(statusBadge(doc.status));
    $('source-link').href = `${docPath()}/source`;
    $('invoice-select').replaceChildren();
    doc.invoices.forEach((invoice, index) => {
      const option = el('option', '', `${index + 1} of ${doc.invoices.length} · ${invoice.invoice_number || 'Invoice number unavailable'}`);
      option.value = String(index);
      $('invoice-select').append(option);
    });
    if (!doc.invoices.length) {
      const option = el('option', '', 'No invoice records extracted');
      option.value = '0';
      $('invoice-select').append(option);
    }
    state.invoiceIndex = Math.min(state.invoiceIndex, Math.max(doc.invoices.length - 1, 0));
    $('invoice-select').value = String(state.invoiceIndex);
    $('issues-tab-count').textContent = doc.issues.length;
    $('raw-text').textContent = doc.raw_text || 'No raw text was extracted from this document. Check the source and extraction warnings.';
    state.editorBaseline = JSON.stringify(doc.invoices, null, 2);
    $('json-editor').value = state.editorBaseline;
    $('reviewer-confirmed').checked = Boolean(doc.review?.confirmed);
    $('review-saved-at').textContent = doc.review?.updated_at ? `Last saved ${formatDate(doc.review.updated_at, true)}${doc.review.confirmed ? ' · Reviewer confirmation recorded' : ' · Not reviewer-confirmed'}` : 'Changes and reviewer confirmation are stored when you save.';
    $('json-error').hidden = true;
    state.dirty = false;
    $('unsaved-indicator').hidden = true;
    renderInvoice();
    renderIssues();
    activateTab(state.tab);
    setReviewBusy(false);
  }

  function currentInvoice() { return state.current?.invoices[state.invoiceIndex] || null; }

  function addField(grid, label, value) {
    const field = el('div', 'field');
    field.append(el('dt', '', label), el('dd', value === null || value === undefined || value === '' ? 'missing' : '', value === null || value === undefined || value === '' ? 'Not extracted' : value));
    grid.append(field);
  }

  function partyCard(label, party = {}) {
    const card = el('div', 'party-card');
    card.append(el('h4', '', label), el('strong', '', party?.name || 'Name not extracted'), el('p', '', party?.address || 'Address not extracted'), el('code', '', `GSTIN: ${party?.gstin || 'Not extracted'}`));
    return card;
  }

  function documentTotalNote(invoices) {
    const values = invoices.filter((invoice) => invoice.currency === 'INR').map((invoice) => invoice.totals?.grand_total).filter((value) => value !== null && value !== undefined && /^-?\d+(\.\d{1,8})?$/.test(String(value)));
    if (values.length < 2) return null;
    // Sum at the schema's maximum decimal precision, not with floating-point arithmetic.
    const scale = 100000000n;
    const total = values.reduce((sum, value) => {
      const raw = String(value);
      const [whole, fraction = ''] = raw.replace('-', '').split('.');
      const scaled = BigInt(whole) * scale + BigInt(fraction.padEnd(8, '0'));
      return sum + (raw.startsWith('-') ? -scaled : scaled);
    }, 0n);
    const absolute = total < 0n ? -total : total;
    const decimal = `${total < 0n ? '-' : ''}${absolute / scale}.${String(absolute % scale).padStart(8, '0')}`;
    return `Document-wide sum of ${values.length} available INR grand totals: ${formatMoney(decimal)}. Descriptive only; record types and credit notes are not netted.`;
  }

  function renderInvoice() {
    const invoice = currentInvoice();
    const panel = $('panel-overview');
    panel.replaceChildren();
    $('items-tab-count').textContent = invoice?.line_items?.length || 0;
    if (!invoice) {
      panel.append(el('div', 'compact-empty', 'No invoice records were extracted. Review the issues, raw text, and source file. You can add a record using the JSON editor.'));
      renderWarnings(panel);
      renderLineItems();
      return;
    }
    const grid = el('div', 'review-overview-grid');
    const details = el('div');
    const heading = el('div', 'overview-heading');
    heading.append(el('h3', '', humanize(invoice.document_type || 'invoice')));
    const confidence = invoice.confidence;
    heading.append(el('span', `confidence-pill${confidence !== null && confidence !== undefined && confidence < .85 ? ' confidence-low' : ''}`, confidence === null || confidence === undefined ? 'No OCR recognition score' : `${Math.round(confidence * 100)}% OCR recognition score`));
    details.append(heading);
    if (confidence !== null && confidence !== undefined) details.append(el('p', 'section-note', 'Recognition score measures OCR text recognition, not invoice-field accuracy. Compare all extracted fields with the source.'));
    const fields = el('dl', 'field-grid');
    addField(fields, 'Invoice number', invoice.invoice_number);
    addField(fields, 'Invoice date', invoice.invoice_date);
    addField(fields, 'Place of supply', invoice.place_of_supply);
    addField(fields, 'Reverse charge', invoice.reverse_charge === null || invoice.reverse_charge === undefined ? null : invoice.reverse_charge ? 'Yes' : 'No');
    addField(fields, 'Currency', invoice.currency);
    addField(fields, 'Extraction method', humanize(invoice.extraction_method));
    details.append(fields);
    const parties = el('div', 'party-grid');
    parties.append(partyCard('Supplier · From', invoice.supplier), partyCard('Buyer · Billed to', invoice.buyer));
    details.append(parties);
    const totals = el('div', 'totals-card');
    totals.append(el('h3', '', 'The numbers, at a glance'));
    const totalsLabels = [['taxable_value', 'Taxable value'], ['cgst_amount', 'CGST'], ['sgst_amount', 'SGST'], ['igst_amount', 'IGST'], ['cess_amount', 'Cess'], ['discount', 'Discount'], ['round_off', 'Round off'], ['grand_total', 'Grand total']];
    for (const [key, label] of totalsLabels) {
      const row = el('div', `total-row${key === 'grand_total' ? ' grand-total' : ''}`);
      row.append(el('span', '', label), el('span', '', formatMoney(invoice.totals?.[key], invoice.currency || 'INR')));
      totals.append(row);
    }
    totals.append(el('p', 'totals-note', 'Extracted amounts, displayed to two decimal places. Missing amounts are shown as —, not zero. These figures are not accountant-certified.'));
    grid.append(details, totals);
    panel.append(grid);
    if (confidence !== null && confidence !== undefined && confidence < .85) panel.append(el('p', 'extraction-warning', 'Low-confidence extraction: always check these fields against the original document. Reviewer confirmation does not remove validation findings.'));
    const aggregate = documentTotalNote(state.current.invoices);
    if (aggregate) panel.append(el('p', 'section-note', aggregate));
    renderWarnings(panel);
    const evidence = invoice.field_evidence;
    if (evidence && Object.keys(evidence).length) {
      const disclosure = el('details', 'evidence-details');
      disclosure.append(el('summary', '', 'View extraction evidence'));
      const list = el('dl', 'evidence-list');
      for (const [field, value] of Object.entries(evidence)) list.append(el('dt', '', field), el('dd', '', typeof value === 'string' ? value : JSON.stringify(value, null, 2)));
      disclosure.append(list);
      panel.append(disclosure);
    }
    if (['png', 'jpg', 'jpeg'].includes(extension(state.current.filename))) {
      const disclosure = el('details', 'evidence-details');
      disclosure.append(el('summary', '', 'Preview original image'));
      disclosure.addEventListener('toggle', () => {
        if (!disclosure.open || disclosure.querySelector('img')) return;
        const image = el('img', 'source-preview');
        image.alt = `Original uploaded invoice: ${state.current.filename}`;
        image.loading = 'lazy';
        image.src = `${docPath()}/source`;
        image.addEventListener('error', () => { image.hidden = true; disclosure.append(el('p', 'preview-error', 'The image preview could not be loaded. Use Open source to view or download the original.')); }, { once: true });
        disclosure.append(image);
      });
      panel.append(disclosure);
    }
    renderLineItems();
  }

  function renderWarnings(panel) {
    const warnings = state.current?.extraction_warnings || [];
    if (!warnings.length) return;
    const block = el('div', 'extraction-notes');
    for (const warning of warnings) block.append(el('p', 'extraction-warning', warning));
    panel.append(block);
  }

  function panelHeading(title, description) {
    const heading = el('div', 'panel-heading');
    const text = el('div');
    text.append(el('h3', '', title), el('p', '', description));
    heading.append(text);
    return heading;
  }

  function renderLineItems() {
    const invoice = currentInvoice();
    const items = invoice?.line_items || [];
    const panel = $('panel-items');
    panel.replaceChildren(panelHeading(`${items.length} line item${items.length === 1 ? '' : 's'}`, 'Values are extracted, not inferred. Edit any missing or incorrect details in the JSON editor.'));
    if (!items.length) { panel.append(el('div', 'compact-empty', 'No line items were extracted for this invoice record.')); return; }
    const columns = [['description', 'Description'], ['hsn_sac', 'HSN / SAC'], ['quantity', 'Quantity'], ['unit', 'Unit'], ['unit_price', 'Unit price'], ['discount', 'Discount'], ['taxable_value', 'Taxable value'], ['gst_rate', 'GST %'], ['cgst_rate', 'CGST %'], ['sgst_rate', 'SGST %'], ['igst_rate', 'IGST %'], ['cgst_amount', 'CGST'], ['sgst_amount', 'SGST'], ['igst_amount', 'IGST'], ['cess_amount', 'Cess'], ['total', 'Total']];
    const monetary = new Set(['unit_price', 'discount', 'taxable_value', 'cgst_amount', 'sgst_amount', 'igst_amount', 'cess_amount', 'total']);
    const wrapper = el('div', 'table-scroll');
    wrapper.tabIndex = 0;
    wrapper.setAttribute('role', 'region');
    wrapper.setAttribute('aria-label', 'Invoice line items; scroll horizontally for tax details');
    const table = el('table', 'line-items-table');
    const head = el('thead');
    const headRow = el('tr');
    for (const [, label] of columns) { const th = el('th', '', label); th.scope = 'col'; headRow.append(th); }
    head.append(headRow);
    const body = el('tbody');
    for (const item of items) {
      const row = el('tr');
      for (const [key] of columns) row.append(el('td', '', monetary.has(key) ? formatMoney(item[key], invoice.currency || 'INR') : item[key] ?? '—'));
      body.append(row);
    }
    table.append(head, body);
    wrapper.append(table);
    panel.append(wrapper);
  }

  function renderIssues() {
    const issues = state.current.issues || [];
    const panel = $('panel-issues');
    panel.replaceChildren(panelHeading('A clear view of the exceptions', 'All issues for this document are shown here. Check the record number, field, and source before making a correction.'));
    if (!issues.length) { panel.append(el('div', 'compact-empty', 'No consistency issues were returned. This does not certify the document’s legal or tax compliance.')); return; }
    const list = el('ul', 'issue-list');
    for (const issue of issues) {
      const severity = ['error', 'warning', 'info'].includes(issue.severity) ? issue.severity : 'info';
      const item = el('li', `issue-card issue-${severity}`);
      const body = el('div', 'issue-body');
      body.append(el('p', '', issue.message));
      const meta = el('div', 'issue-meta');
      meta.append(el('span', '', humanize(severity)), el('code', '', issue.code), el('code', '', issue.field || 'Document'), el('span', '', issue.invoice_index === null || issue.invoice_index === undefined ? 'Document-wide' : `Record ${issue.invoice_index + 1}`));
      body.append(meta);
      item.append(icon(severity === 'info' ? 'info' : 'alert'), body);
      list.append(item);
    }
    panel.append(list);
  }

  function activateTab(name, focus = false) {
    if (!['overview', 'items', 'issues', 'raw', 'json'].includes(name)) return;
    state.tab = name;
    document.querySelectorAll('[data-tab]').forEach((button) => {
      const selected = button.dataset.tab === name;
      button.setAttribute('aria-selected', String(selected));
      button.tabIndex = selected ? 0 : -1;
      $(`panel-${button.dataset.tab}`).hidden = !selected;
      if (selected && focus) button.focus();
    });
  }

  function updateDirty() {
    if (!state.current) return;
    state.dirty = $('json-editor').value !== state.editorBaseline || $('reviewer-confirmed').checked !== Boolean(state.current.review?.confirmed);
    $('unsaved-indicator').hidden = !state.dirty;
    $('json-error').hidden = true;
  }

  function validateEditedInvoices(invoices) {
    if (!Array.isArray(invoices) || !invoices.length) throw new Error('The editor must contain a non-empty JSON array of invoice records.');
    for (const [index, invoice] of invoices.entries()) {
      if (!invoice || typeof invoice !== 'object' || Array.isArray(invoice)) throw new Error(`Record ${index + 1} must be a JSON object.`);
      for (const [field, value] of Object.entries(invoice.totals || {})) {
        if (value !== null && typeof value !== 'string') throw new Error(`Record ${index + 1}, totals.${field}: keep monetary amounts as decimal strings (for example "100.00") or null.`);
      }
      if (invoice.line_items !== undefined && !Array.isArray(invoice.line_items)) throw new Error(`Record ${index + 1}: line_items must be an array.`);
      for (const [line, item] of (invoice.line_items || []).entries()) {
        if (!item || typeof item !== 'object' || Array.isArray(item)) throw new Error(`Record ${index + 1}, line item ${line + 1} must be an object.`);
        for (const key of moneyFields) if (item[key] !== undefined && item[key] !== null && typeof item[key] !== 'string') throw new Error(`Record ${index + 1}, line item ${line + 1}, ${key}: use a decimal string or null, not a JSON number.`);
      }
    }
  }

  async function saveDocument() {
    if (!state.current || state.saving || state.deleting) return;
    let invoices;
    try {
      invoices = JSON.parse($('json-editor').value);
      validateEditedInvoices(invoices);
    } catch (error) {
      $('json-error').textContent = error instanceof SyntaxError ? `The JSON could not be parsed: ${error.message}` : error.message;
      $('json-error').hidden = false;
      activateTab('json');
      $('json-editor').focus();
      return;
    }
    state.saving = true;
    const id = state.current.id;
    const savedTab = state.tab;
    setReviewBusy(true);
    $('save-document').querySelector('span').textContent = 'Checking…';
    $('review-error').hidden = true;
    try {
      const doc = await request(docPath(id), { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ invoices, reviewer_confirmed: $('reviewer-confirmed').checked }) }, 45000);
      if (!Array.isArray(doc.invoices) || !Array.isArray(doc.issues)) throw new Error('The save response was incomplete. Your changes may have been saved; refresh the document to confirm.');
      state.current = doc;
      state.tab = savedTab;
      upsertDocument(doc);
      renderReview();
      toast(`Changes saved and checks re-run. ${labels[doc.status] || 'Review updated'}.${doc.issues.length ? ` ${doc.issues.length} issue${doc.issues.length === 1 ? '' : 's'} remain; see the Issues tab.` : ''}`);
    } catch (error) {
      $('review-error').textContent = `Changes could not be confirmed: ${error.message} Your edits are still in the editor.`;
      $('review-error').hidden = false;
      toast(error.message, 'error');
    } finally {
      state.saving = false;
      setReviewBusy(false);
      $('save-document').querySelector('span').textContent = 'Save & revalidate';
    }
  }

  async function deleteDocument() {
    if (!state.current || state.saving || state.deleting) return;
    if (!window.confirm(`Delete “${state.current.filename}” and its extracted records? This cannot be undone.${state.dirty ? ' Your unsaved edits will also be lost.' : ''}`)) return;
    const id = state.current.id;
    state.deleting = true;
    setReviewBusy(true);
    try {
      await request(docPath(id), { method: 'DELETE' });
      state.documents = state.documents.filter((doc) => doc.id !== id);
      closeReview(false);
      renderMetrics();
      $('refresh-documents').focus();
      toast('Document and its extracted records deleted.');
    } catch (error) { toast(`The document could not be deleted. ${error.message}`, 'error'); }
    finally { state.deleting = false; setReviewBusy(false); }
  }

  async function downloadDocument(format) {
    if (!state.current) return;
    if (state.dirty && !window.confirm('The download contains the last saved version, not your unsaved edits. Download it anyway?')) return;
    const doc = state.current;
    const button = $(`download-${format}`);
    button.disabled = true;
    try {
      const blob = await request(`${docPath(doc.id)}/export?format=${format}`, {}, 45000, 'blob');
      const url = URL.createObjectURL(blob);
      const link = el('a');
      link.href = url;
      link.download = `${String(doc.filename).replace(/\.[^.]+$/, '').replace(/[\\/:*?"<>|\x00-\x1f]/g, '_') || 'invoice'}.${format}`;
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
      toast(`${format.toUpperCase()} download is ready. It contains the last saved records.`);
    } catch (error) { toast(`Download failed. ${error.message}`, 'error'); }
    finally { button.disabled = !state.current || state.saving || state.deleting; }
  }

  async function loadSamples() {
    if (state.samplesLoaded) return;
    const panel = $('samples-list');
    const loading = el('div', 'loading-state', 'Loading synthetic examples…');
    loading.setAttribute('role', 'status');
    panel.replaceChildren(loading);
    try {
      const data = await request('/api/samples');
      if (!Array.isArray(data.samples)) throw new Error('The sample list was not in the expected format.');
      panel.replaceChildren();
      for (const sample of data.samples) {
        const card = el('article', 'sample-card');
        const details = el('div');
        details.append(el('h3', '', sample.name || sample.filename), el('p', '', sample.description || 'A synthetic invoice for testing the extraction workflow.'));
        let url;
        try {
          url = new URL(sample.url, window.location.origin);
          if (url.origin !== window.location.origin || !['http:', 'https:'].includes(url.protocol)) url = null;
        } catch { url = null; }
        if (url) {
          const link = el('a', 'button button-small');
          link.href = url.href;
          link.download = sample.filename || 'sample';
          link.append(icon('download'), document.createTextNode(`Download ${extension(sample.filename).toUpperCase()}`));
          details.append(link);
        } else details.append(el('p', 'section-note', 'This sample’s download link is unavailable.'));
        card.append(fileIcon(sample.filename), details);
        panel.append(card);
      }
      if (!data.samples.length) panel.append(el('div', 'compact-empty', 'No sample files are currently available. You can still upload your own documents.'));
      state.samplesLoaded = true;
    } catch (error) {
      const notice = el('div', 'notice notice-error');
      const retry = el('button', 'button button-small', 'Try again');
      retry.type = 'button';
      retry.addEventListener('click', loadSamples);
      notice.append(el('p', '', error.message), retry);
      panel.replaceChildren(notice);
    }
  }

  function closeMenu() {
    $('sidebar').classList.remove('is-open');
    $('sidebar-backdrop').hidden = true;
    $('menu-button').setAttribute('aria-expanded', 'false');
    $('menu-button').setAttribute('aria-label', 'Open navigation');
    if (window.matchMedia('(max-width: 760px)').matches) $('sidebar').inert = true;
  }

  function openMenu() {
    $('sidebar').inert = false;
    $('sidebar').classList.add('is-open');
    $('sidebar-backdrop').hidden = false;
    $('menu-button').setAttribute('aria-expanded', 'true');
    $('menu-button').setAttribute('aria-label', 'Close navigation');
    $('sidebar').querySelector('[aria-current="page"]').focus();
  }

  function bindEvents() {
    document.querySelectorAll('[data-view]').forEach((button) => button.addEventListener('click', () => {
      if (setView(button.dataset.view)) { window.scrollTo({ top: 0, behavior: 'smooth' }); $('main').focus({ preventScroll: true }); }
    }));
    document.querySelector('.brand').addEventListener('click', (event) => { event.preventDefault(); setView('overview'); });
    ['header-upload', 'browse-files', 'empty-upload'].forEach((id) => $(id).addEventListener('click', chooseFiles));
    $('file-input').addEventListener('change', (event) => uploadFiles(event.target.files));
    $('clear-queue').addEventListener('click', () => { if (!state.uploading) { state.queue = []; renderQueue(); } });
    $('try-samples').addEventListener('click', () => { if (setView('samples')) $('samples-section').scrollIntoView({ behavior: 'smooth' }); });
    let dragDepth = 0;
    $('dropzone').addEventListener('dragenter', (event) => { event.preventDefault(); dragDepth++; if (!state.uploading) $('dropzone').classList.add('drag-over'); });
    $('dropzone').addEventListener('dragover', (event) => { event.preventDefault(); event.dataTransfer.dropEffect = state.uploading ? 'none' : 'copy'; });
    $('dropzone').addEventListener('dragleave', (event) => { event.preventDefault(); dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) $('dropzone').classList.remove('drag-over'); });
    $('dropzone').addEventListener('drop', (event) => { event.preventDefault(); dragDepth = 0; $('dropzone').classList.remove('drag-over'); uploadFiles(event.dataTransfer.files); });
    // Prevent an accidental drop outside the upload area from navigating away.
    window.addEventListener('dragover', (event) => { if (Array.from(event.dataTransfer?.types || []).includes('Files')) event.preventDefault(); });
    window.addEventListener('drop', (event) => { if (event.dataTransfer?.files.length) event.preventDefault(); });
    $('document-search').addEventListener('input', renderDocuments);
    $('status-filter').addEventListener('change', renderDocuments);
    $('refresh-documents').addEventListener('click', loadDocuments);
    $('retry-connection').addEventListener('click', () => { loadHealth(); loadDocuments(); });
    $('close-review').addEventListener('click', () => closeReview());
    $('invoice-select').addEventListener('change', () => { state.invoiceIndex = Number($('invoice-select').value); renderInvoice(); });
    document.querySelectorAll('[data-tab]').forEach((button, index, buttons) => {
      button.addEventListener('click', () => activateTab(button.dataset.tab));
      button.addEventListener('keydown', (event) => {
        let next;
        if (event.key === 'ArrowRight') next = (index + 1) % buttons.length;
        if (event.key === 'ArrowLeft') next = (index - 1 + buttons.length) % buttons.length;
        if (event.key === 'Home') next = 0;
        if (event.key === 'End') next = buttons.length - 1;
        if (next !== undefined) { event.preventDefault(); activateTab(buttons[next].dataset.tab, true); }
      });
    });
    $('json-editor').addEventListener('input', updateDirty);
    $('reviewer-confirmed').addEventListener('change', updateDirty);
    $('reset-json').addEventListener('click', () => {
      if ($('json-editor').value !== state.editorBaseline && !window.confirm('Discard your JSON edits and restore the last saved records?')) return;
      $('json-editor').value = state.editorBaseline;
      updateDirty();
    });
    $('save-document').addEventListener('click', saveDocument);
    $('delete-document').addEventListener('click', deleteDocument);
    $('download-json').addEventListener('click', () => downloadDocument('json'));
    $('download-csv').addEventListener('click', () => downloadDocument('csv'));
    $('about-button').addEventListener('click', () => $('about-dialog').showModal());
    $('close-about').addEventListener('click', () => $('about-dialog').close());
    $('about-dialog').addEventListener('click', (event) => { if (event.target === $('about-dialog')) { const rect = $('about-dialog').getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) $('about-dialog').close(); } });
    $('menu-button').addEventListener('click', () => { if ($('sidebar').classList.contains('is-open')) closeMenu(); else openMenu(); });
    $('sidebar-backdrop').addEventListener('click', () => { closeMenu(); $('menu-button').focus(); });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && $('sidebar').classList.contains('is-open') && !$('about-dialog').open) { closeMenu(); $('menu-button').focus(); }
      if (event.key === 'Tab' && $('sidebar').classList.contains('is-open') && !$('about-dialog').open) {
        const focusable = Array.from($('sidebar').querySelectorAll('a, button')).filter((node) => !node.disabled);
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    });
    const mobile = window.matchMedia('(max-width: 760px)');
    const onResize = () => { closeMenu(); $('sidebar').inert = mobile.matches; };
    mobile.addEventListener('change', onResize);
    onResize();
    window.addEventListener('beforeunload', (event) => { if (state.dirty || state.uploading || state.saving) { event.preventDefault(); event.returnValue = ''; } });
    window.addEventListener('hashchange', () => { if (!setView(window.location.hash.slice(1), false)) history.replaceState(null, '', `#${state.view}`); });
  }

  $('today').textContent = new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }).format(new Date());
  bindEvents();
  setView(window.location.hash.slice(1) || 'overview', false);
  loadHealth();
  loadDocuments();
})();
