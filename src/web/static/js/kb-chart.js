function createBarChart({ id, data, orientation = 'horizontal', color = '#f97316', class_ = "" }) {

    const container = document.createElement('div');
    container.className = `w-full h-full min-h-[180px] flex-1 overflow-hidden ${class_}`;
    if (id) container.id = id;

    // ResizeObserver — observe le container directement, pas de getElementById
    const ro = new ResizeObserver(entries => {
        for (let entry of entries) {
            const { width, height } = entry.contentRect;
            if (width > 0 && height > 0) render(width, height);
        }
    });
    ro.observe(container);

    function render(width, height) {
        d3.select(container).selectAll("svg").remove();

        const margin = {
            top: 10,
            right: 20,
            bottom: orientation === 'vertical' ? 40 : 20,
            left: orientation === 'horizontal' ? 70 : 40
        };

        const svg = d3.select(container)
            .append("svg")
            .attr("width", width)
            .attr("height", height)
            .attr("class", "overflow-visible");

        if (orientation === 'horizontal') {
            const x = d3.scaleLinear()
                .domain([0, d3.max(data, d => d.value)])
                .range([margin.left, width - margin.right]);

            const y = d3.scaleBand()
                .domain(data.map(d => d.label))
                .range([margin.top, height - margin.bottom])
                .padding(0.3);

            svg.selectAll("rect")
                .data(data)
                .enter()
                .append("rect")
                .attr("x", margin.left)
                .attr("y", d => y(d.label))
                .attr("width", d => x(d.value) - margin.left)
                .attr("height", y.bandwidth())
                .attr("fill", color)
                .attr("rx", 4);

            svg.append("g")
                .attr("transform", `translate(${margin.left}, 0)`)
                .call(d3.axisLeft(y).tickSize(0).tickPadding(8))
                .attr("color", "#71717a")
                .selectAll("text")
                .attr("class", "text-[10px]")
                .style("font-family", "inherit");

        } else {
            const x = d3.scaleBand()
                .domain(data.map(d => d.label))
                .range([margin.left, width - margin.right])
                .padding(0.3);

            const y = d3.scaleLinear()
                .domain([0, d3.max(data, d => d.value)])
                .range([height - margin.bottom, margin.top]);

            svg.selectAll("rect")
                .data(data)
                .enter()
                .append("rect")
                .attr("x", d => x(d.label))
                .attr("y", d => y(d.value))
                .attr("width", x.bandwidth())
                .attr("height", d => (height - margin.bottom) - y(d.value))
                .attr("fill", color)
                .attr("rx", 4);

            const xAxis = svg.append("g")
                .attr("transform", `translate(0, ${height - margin.bottom})`)
                .call(d3.axisBottom(x).tickSize(0).tickPadding(8))
                .attr("color", "#71717a");

            if (width < 300) {
                xAxis.selectAll("text")
                    .attr("transform", "rotate(-45)")
                    .style("text-anchor", "end");
            }
        }

        svg.selectAll(".domain").remove();
    }

    return container;  // retourne toujours un element DOM
}

function createPieChart({ id, data, colorScheme = d3.schemeTableau10, class_ = "" }) {

    const container = document.createElement('div');
    container.className = `w-full h-full min-h-[200px] flex-1 overflow-hidden ${class_}`;
    if (id) container.id = id;

    const ro = new ResizeObserver(entries => {
        for (let entry of entries) {
            const { width, height } = entry.contentRect;
            if (width > 100 && height > 50) render(width, height);
        }
    });
    ro.observe(container);

    function render(width, height) {
        d3.select(container).selectAll("svg").remove();

        const radius = Math.min(width, height) / 2 - 10;
        const color = d3.scaleOrdinal(colorScheme);

        const svg = d3.select(container)
            .append("svg")
            .attr("width", width)
            .attr("height", height)
            .append("g")
            .attr("transform", `translate(${width / 2}, ${height / 2})`);

        const pie = d3.pie()
            .value(d => d.value)
            .sort(null);

        const arc = d3.arc()
            .innerRadius(radius * 0.5)
            .outerRadius(radius);

        const arcs = svg.selectAll("arc")
            .data(pie(data))
            .enter()
            .append("g");

        arcs.append("path")
            .attr("d", arc)
            .attr("fill", (d, i) => color(i))
            .attr("stroke", "#2f2f2f")
            .style("stroke-width", "2px");

        if (width > 200) {
            arcs.append("text")
                .attr("transform", d => `translate(${arc.centroid(d)})`)
                .attr("text-anchor", "middle")
                .attr("class", "fill-white text-[10px] font-medium pointer-events-none")
                .text(d => d.data.value > 5 ? d.data.label : "");
        }
    }

    return container;
}


function createDataCard({ title, icon, columns, rows, id, style, class_}) {
    const colCount = columns.length;
    // On définit la structure de la grille une seule fois pour la cohérence
    const gridStyle = `display: grid; grid-template-columns: 2fr ${'1fr '.repeat(colCount - 1)}; gap: 0.5rem; align-items: center;`;

    // Header
    const headerHtml = `
        <div style="${gridStyle}" class="text-[11px] border-b border-white/5 pb-1 text-zinc-600">
            ${columns.map((col, idx) => `
                <span class="truncate whitespace-nowrap ${idx > 0 ? 'text-right' : ''}" title="${col}">${col}</span>
            `).join('')}
        </div>`;

    // Lignes
    const rowsHtml = rows.map(row => `
        <div style="${gridStyle}" class="text-xs h-7">
            <span class="text-zinc-300 truncate whitespace-nowrap min-w-0" title="${row[0]}">
                ${row[0]}
            </span>
            ${row.slice(1).map(cell => `
                <span class="text-right font-medium text-zinc-400 truncate whitespace-nowrap min-w-0" title="${cell}">
                    ${cell}
                </span>
            `).join('')}
        </div>
    `).join('');

    return `
        <div ${style? ('style="'+style+'"'): ''} ${id? ('id="'+id+'"'): ''} class="${class_||""} group relative glass-card p-5 rounded-xl border border-white/5 hover:border-orange-500/30 transition-all duration-500 cursor-zoom-in overflow-hidden">
            <div class="flex items-center justify-between mb-4">
                <span class="text-[10px] font-bold text-zinc-500 uppercase tracking-widest truncate mr-2">${title}</span>
                <span class="material-symbols-outlined text-[16px] text-orange-500 shrink-0">${icon || 'table_chart'}</span>
            </div>
            <div class="space-y-1">
                ${headerHtml}
                <div class="pt-1.5">
                    ${rowsHtml}
                </div>
            </div>
            <!-- Hover Overlay -->
            <div class="absolute inset-0 bg-zinc-950/60 backdrop-blur-[2px] opacity-0 group-hover:opacity-100 flex items-center justify-center transition-opacity rounded-xl">
                <div class="flex flex-col items-center gap-2">
                    <span class="material-symbols-outlined text-white text-3xl">zoom_in</span>
                    <span class="text-[10px] font-bold uppercase tracking-widest text-white">Détails</span>
                </div>
            </div>
        </div>`;
}