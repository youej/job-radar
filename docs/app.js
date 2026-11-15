/* Job Radar front-end. Vanilla JS, no build step. Data arrives as window.JOB_RADAR_DATA (data/jobs.js). */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const STATE_KEY = 'jobradar.v2';
  const LEGACY_KEY = 'jobradar.v1';

  const DEFAULTS = {
    q: '', loc: 'both', role: 'all', sort: 'score',
    days: '30', newOnly: false, programOnly: false,
    floor: true, floorOverride: '', unlisted: true,
    remote: false, adjacent: false, company: '',
    cap: true, showApplied: true, showHidden: false,
  };
  const SECONDARY = ['days', 'newOnly', 'programOnly', 'floor', 'floorOverride', 'unlisted', 'remote', 'adjacent', 'company', 'cap', 'showApplied', 'showHidden'];

  let DATA = { meta: {}, jobs: [] };
  let state = loadState();
  let filters = { ...DEFAULTS, ...(state.filters || {}) };
  const previousVisit = state.lastVisit || null;
  const expanded = new Set();

  function loadState() {
    let s = {};
    try { s = JSON.parse(localStorage.getItem(STATE_KEY)) || {}; } catch { s = {}; }
    if (!s.migrated) {
      try {
        const old = JSON.parse(localStorage.getItem(LEGACY_KEY)) || {};
        s = { ...s, saved: old.saved || {}, applied: old.applied || {}, hidden: old.hidden || {}, theme: old.theme, lastVisit: old.lastVisit, migrated: true };
      } catch { s.migrated = true; }
    }
    s.saved = s.saved || {}; s.applied = s.applied || {}; s.hidden = s.hidden || {};
    return s;
  }
  function saveState() { state.filters = filters; try { localStorage.setItem(STATE_KEY, JSON.stringify(state)); } catch { /* private mode */ } }

  // ---------- theme ----------
  const root = document.documentElement;
  if (state.theme) root.dataset.theme = state.theme;
  $('#theme-toggle').onclick = () => {
    const dark = root.dataset.theme === 'dark' || (!root.dataset.theme && matchMedia('(prefers-color-scheme: dark)').matches);
    root.dataset.theme = dark ? 'light' : 'dark'; state.theme = root.dataset.theme; saveState();
  };

  // ---------- tabs ----------
  function showTab(name) {
    $$('.tab').forEach(x => x.classList.toggle('active', x.dataset.tab === name));
    $$('.view').forEach(v => v.classList.toggle('hidden', v.id !== 'view-' + name));
    if (name === 'saved') renderSaved();
    window.scrollTo(0, 0);
  }
  $$('.tab').forEach(t => t.onclick = () => showTab(t.dataset.tab));
  $('#open-sources').onclick = e => { e.preventDefault(); showTab('sources'); };

  // ---------- helpers ----------
  const fmtK = n => n == null ? '' : '$' + Math.round(n / 1000) + 'k';
  const days = iso => iso ? Math.floor((Date.now() - new Date(iso + 'T12:00:00Z')) / 86400000) : null;
  const ago = iso => { const d = days(iso); if (d == null) return ''; if (d <= 0) return 'today'; if (d === 1) return 'yesterday'; if (d < 30) return d + 'd ago'; return Math.round(d / 30) + 'mo ago'; };
  const ROLE_LABEL = { pm: 'Product management', pmm: 'Product marketing', strategy: 'Strategy / BizOps', adjacent: 'Adjacent' };
  const LEVEL_LABEL = { entry: 'Entry level', mid: 'Mid level' };
  const BUCKET_LABEL = { nyc: 'NYC', bay: 'Bay Area', remote: 'Remote' };
  const isFresh = j => previousVisit ? j.first_seen > previousVisit.slice(0, 10) : j.is_new;
  function floors() {
    const f = { ...(DATA.meta.salary_floor || { nyc: 130000, bay: 150000, remote: 130000 }) };
    const o = parseInt(filters.floorOverride, 10);
    if (o) for (const k of Object.keys(f)) f[k] = o * 1000;
    return f;
  }
  function floorFor(job) {
    const f = floors();
    const want = filters.loc === 'both' ? ['nyc', 'bay', 'remote'] : [filters.loc];
    const bs = job.buckets.filter(b => want.includes(b));
    return Math.min(...(bs.length ? bs : job.buckets).map(b => f[b] ?? 130000));
  }
  function salaryClass(job) {
    const s = job.salary; if (!s || !s.max) return 'none';
    const fl = floorFor(job); const mid = (s.min + s.max) / 2;
    if (mid >= fl) return 'good'; if (s.max >= fl) return 'warn'; return 'bad';
  }

  // ---------- filtering ----------
  function passes(job) {
    if (state.hidden[job.id] && !filters.showHidden) return false;
    if (state.applied[job.id] && !filters.showApplied) return false;
    const b = job.buckets;
    const inCity = filters.loc === 'both' ? (b.includes('nyc') || b.includes('bay')) : b.includes(filters.loc);
    if (!inCity && !(filters.remote && b.includes('remote'))) return false;
    if (filters.role === 'all') { if (job.role === 'adjacent' && !filters.adjacent) return false; }
    else if (job.role !== filters.role) return false;
    if (filters.programOnly && !job.program) return false;
    if (filters.floor) {
      if (job.salary && job.salary.max) { if (job.salary.max < floorFor(job)) return false; }
      else if (!filters.unlisted) return false;
    }
    const d = parseInt(filters.days, 10);
    if (d && !job.program) { const age = days(job.posted); if (age != null && age > d) return false; }
    if (filters.newOnly && !isFresh(job)) return false;
    if (filters.company && job.company !== filters.company) return false;
    if (filters.q) {
      const q = filters.q.toLowerCase();
      if (!(job.title.toLowerCase().includes(q) || job.company.toLowerCase().includes(q))) return false;
    }
    return true;
  }
  const SORTS = {
    score: (a, b) => b.score - a.score || (b.posted || '').localeCompare(a.posted || ''),
    posted: (a, b) => (b.posted || b.first_seen || '').localeCompare(a.posted || a.first_seen || '') || b.score - a.score,
    salary: (a, b) => ((b.salary && b.salary.max) || 0) - ((a.salary && a.salary.max) || 0) || b.score - a.score,
  };
  const visibleJobs = () => DATA.jobs.filter(passes).sort(SORTS[filters.sort] || SORTS.score);

  // ---------- rows ----------
  const tpl = $('#row-tpl');
  function row(job) {
    const el = tpl.content.firstElementChild.cloneNode(true);
    const a = $('.title', el); a.textContent = job.title; a.href = job.url;
    $('.badge.new', el).classList.toggle('hidden', !isFresh(job));
    $('.badge.program', el).classList.toggle('hidden', !job.program);
    $('.company', el).textContent = job.company;
    const cities = job.buckets.filter(x => x !== 'remote').map(x => BUCKET_LABEL[x]);
    if (job.buckets.includes('remote')) cities.push('Remote');
    $('.loc', el).textContent = cities.join(' / ');
    $('.posted', el).textContent = job.posted ? ago(job.posted) : 'seen ' + ago(job.first_seen);
    const m = $('.row-meta', el); m.textContent = [ROLE_LABEL[job.role] || job.role, LEVEL_LABEL[job.seniority] || job.seniority].join(' · ');
    if (job.years_min != null) {
      const y = document.createElement('span'); y.textContent = ` · asks ${job.years_min}+ yrs`; if (job.years_min <= 2) y.className = 'yrs-ok'; m.appendChild(y);
    }
    const sal = $('.salary', el); const cls = salaryClass(job); sal.classList.add(cls);
    if (job.salary && job.salary.max) {
      sal.textContent = `${fmtK(job.salary.min)}–${fmtK(job.salary.max)}`;
      $('.salary-note', el).textContent = cls === 'good' ? 'base' : cls === 'warn' ? 'top of range clears floor' : 'below floor';
      sal.title = `Her floor here: ${fmtK(floorFor(job))}${job.salary.source === 'parsed' ? ' · range parsed from posting text' : ''}`;
    } else { sal.textContent = 'pay not listed'; }
    const snip = $('.snippet', el); snip.textContent = job.snippet || '';
    $('.act.more', el).onclick = () => snip.classList.toggle('hidden');
    const sync = () => {
      el.classList.toggle('is-saved', !!state.saved[job.id]);
      el.classList.toggle('is-applied', !!state.applied[job.id]);
      el.classList.toggle('is-hidden', !!state.hidden[job.id]);
      const sv = $('.act.save', el); sv.classList.toggle('on', !!state.saved[job.id]); sv.textContent = state.saved[job.id] ? '★' : '☆';
      $('.act.applied', el).classList.toggle('on', !!state.applied[job.id]);
      $('.act.hide', el).classList.toggle('on', !!state.hidden[job.id]);
    };
    const toggle = key => () => { if (state[key][job.id]) delete state[key][job.id]; else state[key][job.id] = new Date().toISOString(); saveState(); sync(); updateCounts(); };
    $('.act.save', el).onclick = toggle('saved');
    $('.act.applied', el).onclick = toggle('applied');
    $('.act.hide', el).onclick = () => { toggle('hidden')(); if (!filters.showHidden) { el.remove(); renderSummary(); } };
    sync();
    return el;
  }

  function foldByCompany(jobs) {
    if (!filters.cap || filters.company || filters.q) return jobs;
    const per = {}; const out = [];
    jobs.forEach(j => {
      per[j.company] = (per[j.company] || 0) + 1;
      if (per[j.company] <= 5 || expanded.has(j.company)) out.push(j);
      else if (per[j.company] === 6) out.push({ expander: j.company, rest: jobs.filter(x => x.company === j.company).length - 5 });
    });
    return out;
  }
  function renderList(container, jobs) {
    foldByCompany(jobs).forEach(r => {
      if (r.expander) {
        const b = document.createElement('button'); b.className = 'expander';
        b.textContent = `Show ${r.rest} more from ${r.expander}`;
        b.onclick = () => { expanded.add(r.expander); render(); };
        container.appendChild(b);
      } else container.appendChild(row(r));
    });
  }

  function render() {
    const host = $('#sections'); host.innerHTML = '';
    const jobs = visibleJobs();
    const age = j => days(j.posted ?? j.first_seen) ?? 99;
    const groups = [
      ['New-grad & rotational programs', jobs.filter(j => j.program)],
      ['This week', jobs.filter(j => !j.program && age(j) <= 7)],
      ['Earlier', jobs.filter(j => !j.program && age(j) > 7)],
    ];
    if (!jobs.length) host.innerHTML = '<p class="empty">Nothing matches. Open More and widen "Posted within", or turn off the pay floor.</p>';
    groups.forEach(([name, list]) => {
      if (!list.length) return;
      const h = document.createElement('div'); h.className = 'section-head';
      h.innerHTML = `<h3>${name}</h3><span class="count">${list.length}</span>`;
      host.appendChild(h);
      const box = document.createElement('div'); box.className = 'list'; host.appendChild(box);
      renderList(box, list);
    });
    renderSummary(jobs); updateCounts(); updateMoreCount();
  }
  function renderSummary(jobs = visibleJobs()) {
    const fresh = jobs.filter(isFresh).length;
    const withSal = jobs.filter(j => j.salary && j.salary.max).length;
    const where = { both: 'New York and the Bay Area', nyc: 'New York', bay: 'the Bay Area' }[filters.loc];
    $('#result-summary').textContent = `${jobs.length} role${jobs.length === 1 ? '' : 's'} in ${where} · ${fresh} new since your last visit · ${withSal} list pay`;
  }
  function updateCounts() { const n = Object.keys(state.saved).length + Object.keys(state.applied).length; $('#count-saved').textContent = n || ''; }
  function updateMoreCount() {
    const n = SECONDARY.filter(k => String(filters[k]) !== String(DEFAULTS[k])).length;
    $('#more-count').textContent = n ? n : '';
  }

  // ---------- saved ----------
  function renderSaved() {
    const byId = Object.fromEntries(DATA.jobs.map(j => [j.id, j]));
    const fill = (sel, ids) => {
      const el = $(sel); el.innerHTML = '';
      const jobs = ids.map(id => byId[id]).filter(Boolean);
      if (!jobs.length) el.innerHTML = '<p class="empty">Nothing here yet.</p>';
      jobs.forEach(j => el.appendChild(row(j)));
      const gone = ids.length - jobs.length;
      if (gone) el.insertAdjacentHTML('beforeend', `<p class="summary">${gone} saved posting${gone > 1 ? 's are' : ' is'} no longer live.</p>`);
    };
    fill('#saved-list', Object.keys(state.saved).filter(id => !state.applied[id]));
    fill('#applied-list', Object.keys(state.applied));
    $('#saved-summary').textContent = `${Object.keys(state.saved).length} saved · ${Object.keys(state.applied).length} applied`;
  }
  $('#export-csv').onclick = () => {
    const byId = Object.fromEntries(DATA.jobs.map(j => [j.id, j]));
    const rows = [['status', 'company', 'title', 'location', 'salary_min', 'salary_max', 'posted', 'url', 'marked_at']];
    const add = (status, map) => Object.entries(map).forEach(([id, ts]) => { const j = byId[id]; if (j) rows.push([status, j.company, j.title, j.primary_location, j.salary.min || '', j.salary.max || '', j.posted || '', j.url, ts]); });
    add('applied', state.applied); add('saved', Object.fromEntries(Object.entries(state.saved).filter(([id]) => !state.applied[id])));
    const csv = rows.map(r => r.map(v => `"${String(v ?? '').replace(/"/g, '""')}"`).join(',')).join('\n');
    const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' })); a.download = 'job-radar-tracker.csv'; a.click();
  };

  // ---------- programs + sources ----------
  function renderPrograms() {
    const p = window.JOB_RADAR_PROGRAMS;
    if (!p) { $('#programs').innerHTML = '<p>programs.js missing.</p>'; return; }
    const progRows = p.programs.map(x => `<tr><td><a href="${x.url}" target="_blank" rel="noopener">${x.company}</a></td><td>${x.program}</td><td>${x.track}</td><td>${x.window}</td><td>${x.notes || ''}</td></tr>`).join('');
    const manual = p.manual_checks.map(x => `<tr><td><a href="${x.url}" target="_blank" rel="noopener">${x.company}</a></td><td>${x.why}</td></tr>`).join('');
    const quick = p.quick_searches.map(x => `<a href="${x.url}" target="_blank" rel="noopener">${x.label}</a>`).join('');
    $('#programs').innerHTML = `
      <h2>New-grad and rotational programs</h2>
      ${p.timing_note ? `<p><strong>Timing.</strong> ${p.timing_note}</p>` : ''}
      <p>Windows are typical past patterns; verify on the program page. When a program posts at a tracked company it also appears in the Jobs tab under its own heading.</p>
      <table><thead><tr><th>Company</th><th>Program</th><th>Track</th><th>Typical window</th><th>Notes</th></tr></thead><tbody>${progRows}</tbody></table>
      <h2>Quick searches on sites this tool can't read</h2>
      <p>LinkedIn, Indeed and campus portals block automated access. Open these once or twice a week.</p>
      <div class="pill-list">${quick}</div>
      <h2>Companies to check by hand</h2>
      <table><thead><tr><th>Company</th><th>Why</th></tr></thead><tbody>${manual}</tbody></table>`;
  }
  function renderSources() {
    const m = DATA.meta; const src = m.sources || [];
    const ok = src.filter(s => s.status === 'ok').length;
    const rows = src.slice().sort((a, b) => (a.status === 'ok') - (b.status === 'ok') || a.company.localeCompare(b.company))
      .map(s => `<tr><td>${s.company}</td><td>${s.ats}</td><td class="status-${s.status}">${s.status}</td><td>${s.raw}</td><td>${s.error || ''}</td></tr>`).join('');
    $('#sources').innerHTML = `
      <h2>Where the jobs come from</h2>
      <p>Postings are pulled straight from each company's applicant-tracking system (Greenhouse, Lever, Ashby, Workday, Eightfold) plus Amazon's and Google's public job search. Senior titles and roles asking for 5+ years are removed before they reach this page. ${ok} of ${src.length} sources responded on the last run (${new Date(m.generated_at).toLocaleString()}).</p>
      <p>${m.counts?.total ?? 0} roles kept · ${m.counts?.nyc ?? 0} NYC · ${m.counts?.bay ?? 0} Bay Area · ${m.counts?.remote ?? 0} remote · ${m.counts?.with_salary ?? 0} with a salary range.</p>
      <table><thead><tr><th>Company</th><th>ATS</th><th>Status</th><th>Raw postings</th><th>Error</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  // ---------- controls wiring ----------
  function paint() {
    $('#q').value = filters.q;
    $$('.seg').forEach(seg => $$('button', seg).forEach(b => b.classList.toggle('on', b.dataset.v === filters[seg.dataset.f])));
    $('#sort').value = filters.sort;
    $('#f-days').value = filters.days; $('#f-newonly').checked = filters.newOnly; $('#f-program').checked = filters.programOnly;
    $('#f-floor').checked = filters.floor; $('#f-floor-override').value = filters.floorOverride; $('#f-unlisted').checked = filters.unlisted;
    $('#f-remote').checked = filters.remote; $('#f-adjacent').checked = filters.adjacent; $('#f-company').value = filters.company;
    $('#f-cap').checked = filters.cap; $('#f-showapplied').checked = filters.showApplied; $('#f-showhidden').checked = filters.showHidden;
  }
  function read() {
    filters.q = $('#q').value.trim(); filters.sort = $('#sort').value;
    filters.days = $('#f-days').value; filters.newOnly = $('#f-newonly').checked; filters.programOnly = $('#f-program').checked;
    filters.floor = $('#f-floor').checked; filters.floorOverride = $('#f-floor-override').value; filters.unlisted = $('#f-unlisted').checked;
    filters.remote = $('#f-remote').checked; filters.adjacent = $('#f-adjacent').checked; filters.company = $('#f-company').value;
    filters.cap = $('#f-cap').checked; filters.showApplied = $('#f-showapplied').checked; filters.showHidden = $('#f-showhidden').checked;
    saveState(); render();
  }
  $$('.seg').forEach(seg => $$('button', seg).forEach(b => b.onclick = () => { filters[seg.dataset.f] = b.dataset.v; paint(); read(); }));
  $('#q').addEventListener('input', read);
  $('#sort').addEventListener('change', read);
  $('#more').addEventListener('change', read);
  $('#more-btn').onclick = () => { const m = $('#more'); m.classList.toggle('hidden'); $('#more-btn').setAttribute('aria-expanded', String(!m.classList.contains('hidden'))); };
  $('#more-done').onclick = () => { $('#more').classList.add('hidden'); $('#more-btn').setAttribute('aria-expanded', 'false'); };
  $('#reset-filters').onclick = () => { filters = { ...DEFAULTS }; paint(); read(); };

  // ---------- boot ----------
  function boot() {
    DATA = window.JOB_RADAR_DATA;
    if (!DATA) { $('#meta-line').textContent = 'No data yet. Run ./refresh.sh first.'; return; }
    const m = DATA.meta; const ageH = Math.round((Date.now() - new Date(m.generated_at)) / 3600000);
    $('#meta-line').textContent = `${m.counts.total} roles · refreshed ${ageH < 1 ? 'just now' : ageH < 48 ? ageH + 'h ago' : Math.round(ageH / 24) + ' days ago'}`;
    const companies = [...new Set(DATA.jobs.map(j => j.company))].sort();
    $('#f-company').innerHTML = '<option value="">any</option>' + companies.map(c => `<option>${c}</option>`).join('');
    paint(); render(); renderPrograms(); renderSources();
    state.lastVisit = new Date().toISOString(); saveState();
  }
  boot();
})();
