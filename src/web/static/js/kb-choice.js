/**
 * renderClarification(options, bubble, onConfirm)
 *
 * Affiche un sélecteur de clarification dans la bulle AI.
 *
 * @param {Array}    options    [{tool_id, origin, category, suggestions: [{canonic_name, id, score}]}]
 * @param {Element}  bubble     élément DOM de la bulle ($currentAiBubble.get(0))
 * @param {Function} onConfirm  callback(resolved) où resolved = [{origin, category, id, canonic_name}]
 *
 * Intégration dans socket.on('chat_response') :
 *
 *   socket.on('chat_response', (response) => {
 *       $currentAiBubble = $(".message-pending");
 *       $currentAiBubble.removeClass("message-pending")
 *           .find('.typing-indicator').fadeOut(200, function() {
 *               $(this).remove();
 *
 *               if (response.intent === 'CLARIFICATION') {
 *                   renderClarification(
 *                       response.clarification,
 *                       $currentAiBubble.get(0),
 *                       (resolved) => {
 *                           // Envoyer la réponse avec les IDs résolus
 *                           socket.emit('chat_message', {
 *                               question:  response.pending_question,
 *                               resolved:  resolved,
 *                               session_id: currentSessionId,
 *                           });
 *                       }
 *                   );
 *                   return;
 *               }
 *               // ... traitement normal ...
 *           });
 *   });
 */

(function () {

    // Injecter les styles une seule fois
    if (!document.getElementById('clar-styles')) {
        const style = document.createElement('style');
        style.id = 'clar-styles';
        style.textContent = `
            .clar-wrap {
                padding: 4px 0 8px;
            }
            .clar-intro {
                font-size: 13px;
                color: var(--color-text-secondary, #555);
                margin-bottom: 14px;
                line-height: 1.5;
            }
            .clar-steps {
                display: flex;
                flex-direction: column;
                gap: 12px;
            }
            .clar-step {
                background: var(--color-background-primary, #fff);
                border: 0.5px solid var(--color-border-tertiary, #ddd);
                border-radius: 10px;
                padding: 12px 14px;
                transition: border-color .2s;
            }
            .clar-step.resolved {
                border-color: #1D9E75;
            }
            .step-header {
                display: flex;
                align-items: center;
                gap: 8px;
                margin-bottom: 10px;
            }
            .step-num {
                width: 20px;
                height: 20px;
                border-radius: 50%;
                background: var(--color-background-secondary, #f5f5f5);
                border: 0.5px solid var(--color-border-secondary, #ccc);
                font-size: 11px;
                font-weight: 500;
                color: var(--color-text-secondary, #555);
                display: flex;
                align-items: center;
                justify-content: center;
                flex-shrink: 0;
                transition: all .2s;
            }
            .step-num.done {
                background: #E1F5EE;
                border-color: #1D9E75;
                color: #0F6E56;
            }
            .step-origin {
                font-size: 12px;
                color: var(--color-text-secondary, #555);
                flex: 1;
            }
            .step-origin strong {
                color: var(--color-text-primary, #000);
                font-weight: 500;
            }
            .step-origin .cat {
                color: var(--color-text-tertiary, #999);
                font-size: 11px;
                margin-left: 4px;
            }
            .step-chosen {
                font-size: 12px;
                color: #0F6E56;
                font-weight: 500;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
                max-width: 160px;
            }
            .sugg-list {
                display: flex;
                flex-wrap: wrap;
                gap: 6px;
            }
            .sugg-btn {
                font-size: 12px;
                padding: 5px 12px;
                border-radius: 20px;
                border: 0.5px solid var(--color-border-secondary, #ccc);
                background: var(--color-background-primary, #fff);
                color: var(--color-text-secondary, #555);
                cursor: pointer;
                transition: all .15s;
                font-family: inherit;
                line-height: 1;
            }
            .sugg-btn:hover {
                border-color: #1D9E75;
                color: #0F6E56;
                background: #E1F5EE;
            }
            .sugg-btn.selected {
                border-color: #1D9E75;
                color: #0F6E56;
                background: #E1F5EE;
                font-weight: 500;
            }
            .clar-footer {
                margin-top: 14px;
                display: flex;
                align-items: center;
                gap: 10px;
            }
            .clar-confirm {
                font-size: 13px;
                padding: 7px 18px;
                border-radius: 20px;
                border: 0.5px solid #1D9E75;
                background: #E1F5EE;
                color: #0F6E56;
                cursor: pointer;
                font-weight: 500;
                font-family: inherit;
                transition: background .15s;
            }
            .clar-confirm:hover:not(:disabled) {
                background: #9FE1CB;
            }
            .clar-confirm:disabled {
                opacity: .4;
                cursor: not-allowed;
            }
            .clar-pending {
                font-size: 12px;
                color: var(--color-text-tertiary, #999);
            }
        `;
        document.head.appendChild(style);
    }

    window.renderClarification = function (options, bubble, onConfirm, has_history=false) {
        const resolved = new Array(options.length).fill(null);

        const wrap = document.createElement('div');
        wrap.className = 'clar-wrap';

        // Intro
        const intro = document.createElement('div');
        intro.className = 'clar-intro';
        intro.textContent = options.length > 1
            ? 'Plusieurs ambiguïtés détectées. Précisez vos choix :'
            : 'Précisez votre choix :';
        wrap.appendChild(intro);

        // Steps
        const stepsEl = document.createElement('div');
        stepsEl.className = 'clar-steps';

        // Footer (créé maintenant pour updateFooter)
        const confirmBtn = document.createElement('button');
        confirmBtn.className = 'clar-confirm';
        confirmBtn.textContent = 'Confirmer ↗';
        confirmBtn.disabled = true;

        const pendingLabel = document.createElement('span');
        pendingLabel.className = 'clar-pending';

        function updateFooter() {
            const done    = resolved.filter(Boolean).length;
            const total   = options.length;
            const allDone = done === total;
            confirmBtn.disabled = !allDone;
            pendingLabel.textContent = allDone
                ? ''
                : `${done} / ${total} sélectionné${done > 1 ? 's' : ''}`;
        }

        options.forEach((opt, idx) => {
            const step = document.createElement('div');
            step.className = 'clar-step';

            // Header
            const header = document.createElement('div');
            header.className = 'step-header';

            const num = document.createElement('div');
            num.className = 'step-num';
            num.textContent = idx + 1;

            const originEl = document.createElement('div');
            originEl.className = 'step-origin';
            originEl.innerHTML = `<strong>"${opt.origin}"</strong><span class="cat">· ${opt.category.toLowerCase()}</span>`;

            const chosenEl = document.createElement('div');
            chosenEl.className = 'step-chosen';

            header.append(num, originEl, chosenEl);
            step.appendChild(header);

            // Suggestions
            const suggList = document.createElement('div');
            suggList.className = 'sugg-list';

            opt.suggestions.forEach(s => {
                const btn = document.createElement('button');
                btn.className = 'sugg-btn';
                btn.textContent = s.canonic_name;

                btn.addEventListener('click', () => {
                    // Désélectionner tous les boutons de ce step
                    suggList.querySelectorAll('.sugg-btn')
                        .forEach(b => b.classList.remove('selected'));
                    btn.classList.add('selected');

                    // Marquer résolu
                    resolved[idx] = {
                        origin:       opt.origin,
                        tool_id:      opt.tool_id,
                        category:     opt.category,
                        id:           s.id,
                        canonic_name: s.canonic_name
                    };
                    step.classList.add('resolved');
                    num.classList.add('done');
                    num.textContent = '✓';
                    chosenEl.textContent = s.canonic_name;

                    updateFooter();
                });

                suggList.appendChild(btn);
            });

            step.appendChild(suggList);
            stepsEl.appendChild(step);
        });

        // Croix de fermeture
        const closeBtn = document.createElement('button');
        closeBtn.textContent = '×';
        closeBtn.style.cssText = `
            position: absolute;
            top: 8px;
            right: 10px;
            background: none;
            border: none;
            font-size: 16px;
            color: var(--color-text-tertiary, #999);
            cursor: pointer;
            line-height: 1;
            padding: 2px 4px;
            font-family: inherit;
        `;
        closeBtn.addEventListener('click', () => {
            wrap.remove();
            if (onClose) onClose();
        });

        wrap.style.position = 'relative';
        wrap.insertBefore(closeBtn, wrap.firstChild);

        wrap.appendChild(stepsEl);

        // Footer
        const footer = document.createElement('div');
        footer.className = 'clar-footer';

        confirmBtn.addEventListener('click', () => {
            // Désactiver le widget après confirmation
            wrap.style.opacity = '.5';
            wrap.style.pointerEvents = 'none';
            onConfirm(resolved);
        });

        footer.append(confirmBtn, pendingLabel);
        wrap.appendChild(footer);
        bubble.appendChild(wrap);

        updateFooter();
    };

})();