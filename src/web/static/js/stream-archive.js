const ELECTION_TYPES = {
    legislative:  'LÉGISLATIVES',
    presidential: 'PRÉSIDENTIEL',
    municipal:    'MUNICIPAL',
    referendum:   'RÉFÉRENDUM',
};

const STEP_ICONS = {
    'not-started': null,
    'pending':     'sync',
    'done':        'check',
    'error':       'error',
};

const STEP_DEFAULT_ICONS = {
    fingerprint: 'fingerprint',
    table:       'table',
    group:       'group',
    place:       'map',
    database:    'database',
};

// Couleurs par parti
const PARTY_COLORS = {
    'RHDP':     '#E8521A',
    'PDCI-RDA': '#1A6FE8',
    'FPI':      '#1DB86A',
    'ADCI':     '#8B5CF6',
    'CODE':     '#F59E0B',
};

function partyColor(party) {
    return PARTY_COLORS[party] || '#94A3B8';
}

function partyInitial(party) {
    return (party || '?').slice(0, 1).toUpperCase();
}

let _lastState = {};

// ------------------------------------------------------------------ //
//  Icône + état visuel du step                                        //
// ------------------------------------------------------------------ //

function updateStepVisual(step, state) {
    const $dot     = $(`#${step}-dot`);
    const $icon    = $(`#${step}-icon`);
    const $stepper = $(`#${step}-stepper`);
    const $title   = $(`#${step}-title`);

    if (state === 'not-started') {
        $dot.attr('class', 'relative z-10 w-10 h-10 rounded-full bg-slate-100 text-slate-400 flex items-center justify-center flex-shrink-0');
        $icon.text(STEP_DEFAULT_ICONS[step]);
        $stepper.removeClass('stepper-line-active');
        $title.removeClass('text-slate-900').addClass('text-slate-400');

    } else if (state === 'pending') {
        $dot.attr('class', 'relative z-10 w-10 h-10 rounded-full bg-tertiary text-white flex items-center justify-center flex-shrink-0 animate-pulse-soft');
        $icon.text('sync');
        $stepper.removeClass('stepper-line-active');
        $title.removeClass('text-slate-400').addClass('text-slate-900');

    } else if (state === 'done') {
        $dot.attr('class', 'relative z-10 w-10 h-10 rounded-full bg-secondary text-white flex items-center justify-center flex-shrink-0 shadow-lg shadow-secondary/20');
        $icon.text('check');
        $stepper.addClass('stepper-line-active');
        $title.removeClass('text-slate-400').addClass('text-slate-900');

    } else if (state === 'error') {
        $dot.attr('class', 'relative z-10 w-10 h-10 rounded-full bg-red-400 text-white flex items-center justify-center flex-shrink-0');
        $icon.text('error');
        $stepper.removeClass('stepper-line-active');
        $title.removeClass('text-slate-400').addClass('text-slate-900');
    }
}

// ------------------------------------------------------------------ //
//  Fingerprint                                                        //
// ------------------------------------------------------------------ //
function renderFingerprint(data) {
    if (_lastState.fingerprint?.state === data.state &&
        _lastState.fingerprint?.name  === data.name) return;

    const $el = $('#fingerprint-found');
    $el.empty();

    if (data.state !== 'done') return;

    if (data.type) {
        $el.append(`<span class="text-[10px] font-bold text-slate-500 bg-slate-100 px-2 py-1 rounded">
            ${ELECTION_TYPES[data.type] || data.type}
        </span>`);
    }

    if (data.name) {
        $el.append(`<span class="text-[10px] font-bold text-slate-500 bg-slate-100 px-2 py-1 rounded">
            ${data.name}
        </span>`);
    }

    if (data.election_raw) {
        $el.append(`<span class="text-[10px] text-slate-400 italic block mt-1 truncate max-w-[220px]" title="${data.election_raw}">
            ${data.election_raw}
        </span>`);
    }

    // Saisie manuelle si type ou name manquant
    if (!data.type || !data.name) {
        const typeOptions = Object.entries(ELECTION_TYPES)
            .map(([v, l]) => `<option value="${v}">${l}</option>`).join('');
        $el.append(`
            <select class="text-[10px] font-bold text-slate-500 bg-slate-100 px-2 py-1 rounded border-none outline-none mt-1">
                <option value="">Type...</option>${typeOptions}
            </select>
            <span class="text-[10px] font-bold text-slate-500 bg-slate-100 px-2 py-1 rounded">
                <input type="number" placeholder="2024" min="1900" max="2100"
                    class="bg-transparent border-none p-0 w-[36px] text-[10px] font-bold text-slate-500 focus:ring-0 outline-none
                           [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"/>
            </span>
        `);
    }
}

// ------------------------------------------------------------------ //
//  Table                                                              //
// ------------------------------------------------------------------ //
function renderTable(data) {
    if (data.state !== 'done') return;
    if (JSON.stringify(_lastState.table) === JSON.stringify(data)) return;

    const $el = $('#table-info');
    if (!$el.length) return;
    $el.empty();

    const cols = data.columns_found?.column || [];
    const count = cols.length;

    $el.html(`
        <p class="text-xs text-slate-500 mb-1">
            <strong>${data.header_rows_count || '?'}</strong> ligne(s) d'entête ·
            <strong>${count}</strong> colonne(s) détectée(s)
        </p>
        <div class="flex flex-wrap gap-1 mt-1">
            ${cols.slice(0, 8).map(c =>
                `<span class="text-[9px] bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded">${c}</span>`
            ).join('')}
            ${count > 8 ? `<span class="text-[9px] text-slate-400 italic">+${count - 8} autres</span>` : ''}
        </div>
    `);
}

// ------------------------------------------------------------------ //
//  Group — candidats avec parti                                       //
// ------------------------------------------------------------------ //
const GROUP_THRESHOLD = 8;   // au-delà → scroll

function renderGroup(data) {
    if (data.state === 'not-started') return;
    if (JSON.stringify(_lastState.group?.list) === JSON.stringify(data.list)) return;

    const $el = $('#group-list');
    if (!$el.length) return;
    $el.empty();

    const list = data.list || [];
    const total = list.length;

    if (total === 0) return;

    // Comptage par parti
    const partyCounts = {};
    list.forEach(g => {
        const p = g.party || 'INDEPENDANT';
        partyCounts[p] = (partyCounts[p] || 0) + 1;
    });
    const topParties = Object.entries(partyCounts)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 4);

    // Stats résumé
    $el.append(`
        <div class="flex gap-2 flex-wrap mb-2">
            ${topParties.map(([p, n]) => `
                <span class="inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full"
                      style="background:${partyColor(p)}22;color:${partyColor(p)}">
                    <span class="w-1.5 h-1.5 rounded-full inline-block" style="background:${partyColor(p)}"></span>
                    ${p} · ${n}
                </span>
            `).join('')}
            ${Object.keys(partyCounts).length > 4
                ? `<span class="text-[10px] text-slate-400 italic self-center">+${Object.keys(partyCounts).length - 4} partis</span>`
                : ''}
        </div>
    `);

    // Liste des candidats
    const container = $(`
        <div class="space-y-1 ${total > GROUP_THRESHOLD ? 'max-h-[180px] overflow-y-auto pr-1' : ''}"></div>
    `);

    list.forEach(g => {
        const color = partyColor(g.party);
        container.append(`
            <div class="flex items-center gap-2 p-1.5 bg-slate-50 rounded-lg border border-slate-100">
                <div class="w-5 h-5 rounded-full flex-shrink-0 flex items-center justify-center text-[9px] font-bold text-white"
                     style="background:${color}">${partyInitial(g.party)}</div>
                <div class="flex-1 min-w-0">
                    <div class="text-[11px] font-medium text-slate-700 truncate">${g.name}</div>
                    <div class="text-[9px] text-slate-400">${g.party || ''}</div>
                </div>
            </div>
        `);
    });

    $el.append(container);

    if (total > GROUP_THRESHOLD) {
        $el.append(`<div class="text-[10px] text-slate-400 text-center mt-1">${total} candidats au total</div>`);
    }
}

// ------------------------------------------------------------------ //
//  Place — localités                                                  //
// ------------------------------------------------------------------ //
const PLACE_THRESHOLD = 6;

function renderPlace(data) {
    if (data.state === 'not-started') return;

    const list = data.list || [];
    const $el  = $('#place-list');
    if (!$el.length) return;

    const existingCount = $el.find('[data-place]').length;
    const newItems      = list.slice(existingCount);

    // Ajouter les nouveaux items
    newItems.forEach(p => {
        const isDone    = p.state === 'done';
        const isPending = p.state === 'pending';
        $el.append(`
            <div class="flex items-center justify-between text-xs text-slate-600 px-2 py-1.5 border-l-2
                        ${isDone ? 'border-tertiary bg-tertiary/5' : 'border-slate-200'}"
                 data-place="${encodeURIComponent(p.name)}">
                <span class="truncate flex-1 mr-2 ${!isDone && !isPending ? 'text-slate-400' : ''}"
                      title="${p.name}">${p.name}${p.region ? ` <span class="text-slate-400">(${p.region})</span>` : ''}</span>
                <span class="material-symbols-outlined text-sm flex-shrink-0
                             ${isDone ? 'text-tertiary' : isPending ? 'text-amber-400 animate-spin' : 'text-slate-300'}">
                    ${isDone ? 'check_circle' : isPending ? 'sync' : 'hourglass_empty'}
                </span>
            </div>
        `);
    });

    // Mettre à jour les items existants
    list.slice(0, existingCount).forEach(p => {
        const $item = $el.find(`[data-place="${encodeURIComponent(p.name)}"]`);
        if (!$item.length) return;
        if (p.state === 'done' && !$item.hasClass('border-tertiary')) {
            $item.addClass('border-tertiary bg-tertiary/5').removeClass('border-slate-200');
            $item.find('.material-symbols-outlined')
                .text('check_circle')
                .removeClass('text-slate-300 animate-spin text-amber-400')
                .addClass('text-tertiary');
        }
    });

    // Appliquer scroll si dépasse le seuil
    if (list.length > PLACE_THRESHOLD && !$el.hasClass('max-h-applied')) {
        $el.addClass('max-h-[180px] overflow-y-auto max-h-applied');
    }

    // Compteur
    const done  = list.filter(p => p.state === 'done').length;
    const total = list.length;
    let $counter = $('#place-counter');
    if (!$counter.length) {
        $counter = $('<div id="place-counter" class="text-[10px] text-slate-400 mt-1"></div>');
        $el.after($counter);
    }
    $counter.text(`${done} / ${total} localités traitées`);
}

// ------------------------------------------------------------------ //
//  Database                                                           //
// ------------------------------------------------------------------ //
function renderDatabase(data) {
    const $el = $('#database-info');
    if (!$el.length) return;

    if (data.state === 'pending') {
        $el.html(`<p class="text-xs text-slate-400 mt-1 animate-pulse">Insertion en cours...</p>`);
    } else if (data.state === 'done') {
        $el.html(`<p class="text-xs text-slate-500 mt-1">
            ${data.inserted ? `<strong>${data.inserted.toLocaleString()}</strong> enregistrements insérés` : 'Synchronisation terminée'}
        </p>`);
    }
}

// ------------------------------------------------------------------ //
//  Logs terminal                                                      //
// ------------------------------------------------------------------ //
function appendLog(type, message) {
    const $logs = $('#engine-logs');
    if (!$logs.length) return;
    const colors = { OK: 'text-secondary', PROCESS: 'text-tertiary', ERR: 'text-red-400' };
    $logs.append(`<p><span class="${colors[type] || 'text-slate-500'}">[${type}]</span> ${message}</p>`);
    const $lines = $logs.children();
    if ($lines.length > 10) $lines.first().remove();
    $logs.scrollTop($logs[0].scrollHeight);
}

// ------------------------------------------------------------------ //
//  process_state — point d'entrée                                    //
// ------------------------------------------------------------------ //
function process_state(state) {
    if (!state) return;

    const steps = ['fingerprint', 'table', 'group', 'place', 'database'];

    steps.forEach(step => {
        const curr = state[step]?.state || 'not-started';
        const prev = _lastState[step]?.state;
        updateStepVisual(step, curr);
        if (prev !== curr) {
            if (curr === 'pending') appendLog('PROCESS', `${step} en cours...`);
            if (curr === 'done')    appendLog('OK',      `${step} terminé`);
            if (curr === 'error')   appendLog('ERR',     `Erreur sur ${step}`);
        }
    });

    if (state.fingerprint) renderFingerprint(state.fingerprint);
    if (state.table)       renderTable(state.table);
    if (state.group)       renderGroup(state.group);
    if (state.place)       renderPlace(state.place);
    if (state.database)    renderDatabase(state.database);

    _lastState = JSON.parse(JSON.stringify(state));
}
