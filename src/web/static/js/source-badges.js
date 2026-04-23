/**
 * source-badges.js
 *
 * Utilisation :
 *   1. Inclure ce fichier dans votre HTML
 *   2. Appeler renderSource(source, container) après réception de la réponse
 *
 * Exemple :
 *   socket.on('chat_response', (response) => {
 *       // ... votre code existant ...
 *       if (response.source) {
 *           renderSource(response.source, $currentAiBubble.get(0));
 *       }
 *   });
 */

(function () {

    // ------------------------------------------------------------------ //
    //  Tooltip singleton                                                   //
    // ------------------------------------------------------------------ //

    const tt = document.createElement('div');
    tt.id = 'src-tooltip';
    tt.style.cssText = `
        display: none;
        position: fixed;
        z-index: 9999;
        transform: translateX(-50%);
        pointer-events: auto;
    `;
    document.body.appendChild(tt);

    let hideTimer = null;

    function cancelHide() {
        clearTimeout(hideTimer);
    }

    function scheduleHide() {
        hideTimer = setTimeout(() => {
            tt.style.display = 'none';
        }, 150);
    }

    // La tooltip elle-même annule le hide quand on la survole
    tt.addEventListener('mouseenter', cancelHide);
    tt.addEventListener('mouseleave', scheduleHide);

    function showTooltip(badge, content) {
        cancelHide();
        tt.innerHTML = '';
        tt.appendChild(content);
        tt.style.display = 'block';
        positionTooltip(badge);
    }

    function positionTooltip(badge) {
        const r   = badge.getBoundingClientRect();
        const ttW = tt.offsetWidth  || 200;
        const ttH = tt.offsetHeight || 150;
        let left  = r.left + r.width / 2;
        let top   = r.top - ttH - 8;
        if (top < 8) top = r.bottom + 8;
        left = Math.max(ttW / 2 + 8, Math.min(left, window.innerWidth - ttW / 2 - 8));
        tt.style.left = left + 'px';
        tt.style.top  = top  + 'px';
    }

    // ------------------------------------------------------------------ //
    //  Styles injectés une seule fois                                      //
    // ------------------------------------------------------------------ //

    if (!document.getElementById('src-badge-styles')) {
        const style = document.createElement('style');
        style.id = 'src-badge-styles';
        style.textContent = `
            .source-row {
                display: flex;
                align-items: center;
                gap: 6px;
                flex-wrap: wrap;
                margin-bottom: 10px;
            }
            .src-label {
                font-size: 11px;
                color: var(--color-text-tertiary, #888);
                text-transform: uppercase;
                letter-spacing: .06em;
                font-weight: 500;
                margin-right: 2px;
            }
            .src-badge {
                position: relative;
                display: inline-flex;
                align-items: center;
                gap: 5px;
                font-size: 12px;
                padding: 3px 10px;
                border-radius: 20px;
                border: 0.5px solid var(--color-border-secondary, #ccc);
                background: var(--color-background-primary, #fff);
                color: var(--color-text-secondary, #555);
                cursor: pointer;
                user-select: none;
                transition: border-color .15s, color .15s;
            }
            .src-badge:hover {
                border-color: var(--color-border-primary, #999);
                color: var(--color-text-primary, #000);
            }
            .src-dot {
                width: 6px;
                height: 6px;
                border-radius: 50%;
                flex-shrink: 0;
            }
            .dot-circ  { background: #1D9E75; }
            .dot-cand  { background: #7F77DD; }
            .dot-doc   { background: #378ADD; }
            .dot-pages { background: #BA7517; }

            /* Tooltip contents */
            #src-tooltip {
                filter: drop-shadow(0 4px 12px rgba(0,0,0,.12));
            }
            .tt-crop {
                background: var(--color-background-primary, #fff);
                border: 0.5px solid var(--color-border-secondary, #ccc);
                border-radius: 8px;
                overflow: hidden;
                width: 180px;
            }
            .tt-crop img {
                width: 100%;
                height: 120px;
                object-fit: cover;
                display: block;
                background: var(--color-background-secondary, #f5f5f5);
            }
            .tt-crop .tt-name {
                font-size: 11px;
                color: var(--color-text-secondary, #555);
                padding: 5px 8px;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            .tt-pages, .tt-doc {
                background: var(--color-background-primary, #fff);
                border: 0.5px solid var(--color-border-secondary, #ccc);
                border-radius: 8px;
                padding: 10px 12px;
                width: 210px;
            }
            .tt-title {
                font-size: 12px;
                font-weight: 500;
                color: var(--color-text-primary, #000);
                margin-bottom: 7px;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            .tt-pills {
                display: flex;
                flex-wrap: wrap;
                gap: 4px;
            }
            .tt-pill {
                font-size: 11px;
                padding: 2px 7px;
                border-radius: 20px;
                background: var(--color-background-secondary, #f5f5f5);
                color: var(--color-text-secondary, #555);
                border: 0.5px solid var(--color-border-tertiary, #ddd);
                cursor: pointer;
                text-decoration: none;
                transition: background .1s;
            }
            .tt-pill:hover {
                background: var(--color-background-tertiary, #eee);
            }
            .tt-sub {
                font-size: 11px;
                color: var(--color-text-tertiary, #999);
                margin-top: 4px;
            }
            .tt-open {
                font-size: 11px;
                color: var(--color-text-info, #378ADD);
                margin-top: 6px;
                display: block;
            }
        `;
        document.head.appendChild(style);
    }

    // ------------------------------------------------------------------ //
    //  Builders de contenu tooltip                                        //
    // ------------------------------------------------------------------ //

    function makeCropTooltip(item) {
        const d    = document.createElement('div');
        d.className = 'tt-crop';
        const img  = document.createElement('img');
        img.src    = item.url;
        img.alt    = item.name || '';
        img.onerror = () => { img.style.height = '40px'; };
        const n    = document.createElement('div');
        n.className = 'tt-name';
        n.textContent = item.name || (item.type === 'circ' ? 'Circonscription' : 'Candidat') + ' #' + item.id;
        d.append(img, n);
        return d;
    }

    function makePagesTooltip(source) {
        const d   = document.createElement('div');
        d.className = 'tt-pages';
        const t   = document.createElement('div');
        t.className = 'tt-title';
        t.textContent = source.url ? source.url.split('/').pop() : 'Document';
        const pills = document.createElement('div');
        pills.className = 'tt-pills';
        source.pages.forEach(p => {
            const a = document.createElement('a');
            a.className   = 'tt-pill';
            a.textContent = 'p.' + (p + 1);
            a.href        = source.url + '#page=' + (p + 1);
            a.target      = '_blank';
            pills.appendChild(a);
        });
        d.append(t, pills);
        return d;
    }

    function makeDocTooltip(source) {
        const d   = document.createElement('div');
        d.className = 'tt-doc';
        const t   = document.createElement('div');
        t.className = 'tt-title';
        t.textContent = source.url ? source.url.split('/').pop() : 'Document complet';
        const sub = document.createElement('div');
        sub.className = 'tt-sub';
        sub.textContent = 'Document complet';
        const open = document.createElement('span');
        open.className = 'tt-open';
        open.textContent = '↗ Cliquer pour ouvrir';
        d.append(t, sub, open);
        return d;
    }

    // ------------------------------------------------------------------ //
    //  Création d'un badge                                                //
    // ------------------------------------------------------------------ //

    function makeBadge({ dotClass, label, tooltipFn, onClick }) {
        const badge = document.createElement('span');
        badge.className = 'src-badge';

        const dot = document.createElement('span');
        dot.className = 'src-dot ' + dotClass;

        const text = document.createElement('span');
        text.textContent = label;

        badge.append(dot, text);

        badge.addEventListener('mouseenter', () => showTooltip(badge, tooltipFn()));
        badge.addEventListener('mouseleave', scheduleHide);
        badge.addEventListener('click', onClick);

        return badge;
    }

    // ------------------------------------------------------------------ //
    //  API publique                                                        //
    // ------------------------------------------------------------------ //

    /**
     * renderSource(source, container)
     *
     * source   : objet retourné par compile_source() du backend
     * container: élément DOM dans lequel insérer les badges (en haut)
     */
    window.renderSource = function (source, container) {
        if (!source) return;

        const row = document.createElement('div');
        row.className = 'source-row';

        const lbl = document.createElement('span');
        lbl.className = 'src-label';
        lbl.textContent = 'Source';
        row.appendChild(lbl);

        if (source.type === 'crops') {
            source.items.forEach(item => {
                row.appendChild(makeBadge({
                    dotClass:  item.type === 'circ' ? 'dot-circ' : 'dot-cand',
                    label:     item.name || (item.type === 'circ' ? 'Circ.' : 'Candidat') + ' #' + item.id,
                    tooltipFn: () => makeCropTooltip(item),
                    onClick:   () => window.open(item.url, '_blank'),
                }));
            });

        } else if (source.type === 'pages') {
            row.appendChild(makeBadge({
                dotClass:  'dot-pages',
                label:     source.pages.length + ' page' + (source.pages.length > 1 ? 's' : ''),
                tooltipFn: () => makePagesTooltip(source),
                onClick:   () => window.open(source.url + '#page=' + (source.pages[0] + 1), '_blank'),
            }));

        } else if (source.type === 'document') {
            row.appendChild(makeBadge({
                dotClass:  'dot-doc',
                label:     source.url ? source.url.split('/').pop().replace('.pdf', '') : 'Document',
                tooltipFn: () => makeDocTooltip(source),
                onClick:   () => window.open(source.url, '_blank'),
            }));
        }

        container.prepend(row);
    };

})();