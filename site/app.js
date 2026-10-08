/* Raio-X dos Combustíveis: lê os JSONs gerados pelo pipeline e desenha a página.
   Cores sempre por variável CSS (style, não atributo), para a troca de tema não exigir redesenho. */
(function () {
  "use strict";

  const PRODUTOS = {
    gasolina: "Gasolina comum",
    etanol: "Etanol",
    diesel_s10: "Diesel S10",
    diesel: "Diesel comum",
    gasolina_aditivada: "Gasolina aditivada",
    gnv: "GNV",
  };
  const I = { periodo: 0, mediana: 1, p10: 2, p90: 3, minimo: 4, maximo: 5, postos: 6 };
  const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
  const MESES_LONGOS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
  const LIMIAR_ETANOL = 0.7;
  const MIN_POSTOS_CAPITAL = 5;

  const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
  const pct = new Intl.NumberFormat("pt-BR", { style: "percent", maximumFractionDigits: 1, signDisplay: "exceptZero" });
  const razao = new Intl.NumberFormat("pt-BR", { style: "percent", maximumFractionDigits: 0 });
  // Uma casa decimal perto do limiar: 70,1% não pode aparecer como "70%" e parecer que compensa.
  const razao1 = new Intl.NumberFormat("pt-BR", { style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1 });

  const estado = { produto: "gasolina", real: true, uf: "BA", municipio: null };
  let R = null; // resumo.json
  const cacheMunicipios = {};

  const $ = (id) => document.getElementById(id);
  const unidade = (p) => (p === "gnv" ? "R$/m³" : "R$/litro");
  const mesCurto = (p) => `${MESES[+p.slice(5) - 1]}/${p.slice(2, 4)}`;
  const mesLongo = (p) => `${MESES_LONGOS[+p.slice(5) - 1]} de ${p.slice(0, 4)}`;
  const data = (p) => new Date(+p.slice(0, 4), +p.slice(5) - 1, 1);
  const fator = (p) => (estado.real ? R.ipca.fatores[p] || 1 : 1);
  const ultimo = () => R.periodos[R.periodos.length - 1];
  const nomeUF = (uf) => R.ufs[uf] || uf;
  const titulo = (s) => s.toLowerCase().replace(/(^|\s|-)(\p{L})/gu, (m, a, b) => a + b.toUpperCase()).replace(/\b(De|Da|Do|Das|Dos|E)\b/g, (w) => w.toLowerCase());

  /* ---------- dados ---------- */

  function linhas(codigo, produto, fonte) {
    const s = (fonte || R.series)[codigo];
    return (s && s[produto]) || [];
  }
  function linhaDoMes(codigo, produto, periodo, fonte) {
    return linhas(codigo, produto, fonte).find((l) => l[I.periodo] === periodo);
  }
  function valor(l, campo = "mediana") {
    return l ? l[I[campo]] * fator(l[I.periodo]) : null;
  }
  /** Todos os meses do intervalo, inclusive os que a ANP não publicou (viram buraco na linha). */
  function eixoMeses() {
    return [...new Set([...R.periodos, ...R.meses_faltando])].sort();
  }
  function serieCompleta(codigo, produto, fonte, campo = "mediana") {
    const mapa = new Map(linhas(codigo, produto, fonte).map((l) => [l[I.periodo], l]));
    return eixoMeses().map((p) => ({ p, d: data(p), v: mapa.has(p) ? valor(mapa.get(p), campo) : null, l: mapa.get(p) }));
  }

  /* ---------- utilidades de UI ---------- */

  const tip = $("tooltip");
  function mostrarTip(evento, tituloTxt, itens) {
    tip.replaceChildren();
    const t = document.createElement("div");
    t.className = "t-titulo";
    t.textContent = tituloTxt;
    tip.appendChild(t);
    for (const it of itens) {
      const linha = document.createElement("div");
      linha.className = "t-linha";
      if (it.cor) {
        const i = document.createElement("i");
        i.style.background = it.cor;
        linha.appendChild(i);
      }
      const b = document.createElement("b");
      b.textContent = it.valor;
      const s = document.createElement("span");
      s.textContent = it.rotulo;
      linha.append(b, s);
      tip.appendChild(linha);
    }
    const x = evento.pageX + 14;
    const y = evento.pageY + 14;
    tip.style.opacity = 1;
    const largura = tip.offsetWidth;
    tip.style.left = `${Math.min(x, window.scrollX + document.documentElement.clientWidth - largura - 8)}px`;
    tip.style.top = `${y}px`;
  }
  function esconderTip() {
    tip.style.opacity = 0;
  }

  function tabela(container, cabecalho, linhasTabela) {
    const t = document.createElement("table");
    const thead = t.createTHead().insertRow();
    cabecalho.forEach((c, i) => {
      const th = document.createElement("th");
      th.textContent = c;
      if (i > 0) th.className = "num";
      thead.appendChild(th);
    });
    const tbody = t.createTBody();
    for (const l of linhasTabela) {
      const tr = tbody.insertRow();
      l.forEach((c, i) => {
        const td = tr.insertCell();
        td.textContent = c;
        if (i > 0) td.className = "num";
      });
    }
    container.replaceChildren(t);
  }

  function legenda(container, itens) {
    container.replaceChildren(
      ...itens.map((it) => {
        const s = document.createElement("span");
        const i = document.createElement("i");
        if (it.bloco) i.className = "bloco";
        i.style.background = it.cor;
        if (it.opacidade) i.style.opacity = it.opacidade;
        s.append(i, document.createTextNode(it.rotulo));
        return s;
      })
    );
  }

  function svgEm(container, largura, altura) {
    container.replaceChildren();
    return d3.select(container).append("svg").attr("viewBox", `0 0 ${largura} ${altura}`).attr("role", "img");
  }
  const larguraDe = (el) => Math.max(300, Math.floor(el.clientWidth));
  const fmtValor = (v) => (v == null ? "—" : brl.format(v));

  /* ---------- seções ---------- */

  function renderIndicadores() {
    const p = ultimo();
    const prod = estado.produto;
    const br = linhaDoMes("BR", prod, p);
    const anoAntes = `${+p.slice(0, 4) - 1}${p.slice(4)}`;
    const brAntes = linhaDoMes("BR", prod, anoAntes);
    const ufs = Object.keys(R.ufs)
      .map((uf) => ({ uf, l: linhaDoMes(uf, prod, p) }))
      .filter((x) => x.l)
      .sort((a, b) => b.l[I.mediana] - a.l[I.mediana]);
    // Todos os valores pelo mesmo seletor (com ou sem inflação) que o resto da página
    const caro = ufs[0];
    const barato = ufs[ufs.length - 1];
    const compensa = razoesEtanol(p).filter((r) => r.razao <= LIMIAR_ETANOL);

    $("lead-agora").textContent =
      `${PRODUTOS[prod]} em ${mesLongo(p)}, preço mediano dos postos pesquisados pela ANP (${unidade(prod)}).`;

    const tiles = [
      {
        rotulo: "Preço mediano no Brasil",
        valor: br ? brl.format(valor(br)) : "—",
        detalhe: br ? `${br[I.postos].toLocaleString("pt-BR")} postos pesquisados` : "sem dado no mês",
      },
      {
        rotulo: `Em 12 meses (${estado.real ? "já descontada a inflação" : "sem descontar a inflação"})`,
        valor: br && brAntes ? pct.format(valor(br) / valor(brAntes) - 1) : "—",
        classe: br && brAntes ? (valor(br) > valor(brAntes) ? "sobe" : "desce") : "",
        detalhe: brAntes ? `${mesCurto(anoAntes)}: ${brl.format(valor(brAntes))} → ${mesCurto(p)}: ${brl.format(valor(br))}` : "série começa em jan/23",
      },
      {
        rotulo: "Diferença entre estados",
        valor: caro && barato ? brl.format(valor(caro.l) - valor(barato.l)) : "—",
        detalhe: caro ? `${caro.uf} ${brl.format(valor(caro.l))} · ${barato.uf} ${brl.format(valor(barato.l))}` : "",
      },
      {
        rotulo: "Estados onde o etanol compensa",
        valor: `${compensa.length} de ${razoesEtanol(p).length}`,
        detalhe: "etanol abaixo de 70% da gasolina",
      },
    ];
    $("tiles").replaceChildren(
      ...tiles.map((t) => {
        const c = document.createElement("div");
        c.className = "cartao tile";
        const a = document.createElement("div");
        a.className = "rotulo";
        a.textContent = t.rotulo;
        const v = document.createElement("div");
        v.className = `valor ${t.classe || ""}`;
        v.textContent = t.valor;
        const d = document.createElement("div");
        d.className = "detalhe";
        d.textContent = t.detalhe;
        c.append(a, v, d);
        return c;
      })
    );
  }

  let geo = null;
  function renderMapa() {
    const el = $("g-mapa");
    const p = ultimo();
    const prod = estado.produto;
    const valores = new Map(
      Object.keys(R.ufs)
        .map((uf) => [uf, linhaDoMes(uf, prod, p)])
        .filter(([, l]) => l)
        .map(([uf, l]) => [uf, l])
    );
    const largura = larguraDe(el);
    const altura = Math.round(largura * 0.95);
    const svg = svgEm(el, largura, altura);
    svg.attr("aria-label", `Mapa do Brasil com o preço mediano de ${PRODUTOS[prod]} por estado`);
    const proj = d3.geoMercator().fitSize([largura, altura], geo);
    const caminho = d3.geoPath(proj);
    const vs = [...valores.values()].map((l) => valor(l));
    const passos = 7;
    const escala = d3.scaleQuantize().domain(d3.extent(vs)).range(d3.range(passos));

    svg
      .append("g")
      .selectAll("path")
      .data(geo.features)
      .join("path")
      .attr("d", caminho)
      .attr("tabindex", 0)
      .style("cursor", "pointer")
      .style("fill", (f) => (valores.has(f.properties.sigla) ? `var(--seq-${escala(valor(valores.get(f.properties.sigla)))})` : "var(--surface-2)"))
      .style("stroke", (f) => (f.properties.sigla === estado.uf ? "var(--ink)" : "var(--surface)"))
      .style("stroke-width", (f) => (f.properties.sigla === estado.uf ? 2.5 : 1))
      .on("pointermove focus", function (ev, f) {
        const l = valores.get(f.properties.sigla);
        d3.select(this).style("opacity", 0.85);
        const alvo = ev.type === "focus" ? { pageX: this.getBoundingClientRect().left + window.scrollX, pageY: this.getBoundingClientRect().top + window.scrollY } : ev;
        mostrarTip(alvo, f.properties.nome, [
          { valor: fmtValor(l && valor(l)), rotulo: PRODUTOS[prod] },
          { valor: l ? l[I.postos] : "—", rotulo: "postos" },
        ]);
      })
      .on("pointerleave blur", function () {
        d3.select(this).style("opacity", null);
        esconderTip();
      })
      .on("click keydown", (ev, f) => {
        if (ev.type === "keydown" && ev.key !== "Enter") return;
        definirUF(f.properties.sigla);
      });

    // Escala: 7 faixas da rampa sequencial, com os extremos em reais
    const [mn, mx] = d3.extent(vs);
    const barra = document.createElement("div");
    barra.className = "barra";
    for (let i = 0; i < passos; i++) {
      const c = document.createElement("i");
      c.style.background = `var(--seq-${i})`;
      barra.appendChild(c);
    }
    const a = document.createElement("span");
    a.textContent = brl.format(mn);
    const b = document.createElement("span");
    b.textContent = brl.format(mx);
    $("escala-mapa").replaceChildren(a, barra, b);

    tabela(
      $("t-mapa"),
      ["Estado", `Mediana (${unidade(prod)})`, "10% mais baratos até", "10% mais caros a partir de", "Postos"],
      [...valores.entries()]
        .sort((x, y) => y[1][I.mediana] - x[1][I.mediana])
        .map(([uf, l]) => [nomeUF(uf), brl.format(valor(l)), brl.format(valor(l, "p10")), brl.format(valor(l, "p90")), l[I.postos]])
    );
  }

  function renderRanking() {
    const el = $("g-ranking");
    const p = ultimo();
    const prod = estado.produto;
    const dados = Object.keys(R.ufs)
      .map((uf) => ({ uf, l: linhaDoMes(uf, prod, p) }))
      .filter((d) => d.l)
      .map((d) => ({ ...d, v: valor(d.l) }))
      .sort((a, b) => b.v - a.v);
    const br = linhaDoMes("BR", prod, p);
    $("sub-ranking").textContent = `${PRODUTOS[prod]}, ${mesLongo(p)} · Brasil: ${fmtValor(br && valor(br))}`;

    const largura = larguraDe(el);
    const linha = 18;
    const m = { t: 8, r: 72, b: 24, l: 34 };
    const altura = m.t + m.b + dados.length * linha;
    const svg = svgEm(el, largura, altura);
    svg.attr("aria-label", `Estados ordenados pelo preço de ${PRODUTOS[prod]}`);
    const x = d3.scaleLinear().domain(d3.extent(dados, (d) => d.v)).nice().range([m.l, largura - m.r]);
    const y = d3.scaleBand().domain(dados.map((d) => d.uf)).range([m.t, altura - m.b]);

    svg
      .append("g")
      .attr("class", "grade")
      .selectAll("line")
      .data(x.ticks(4))
      .join("line")
      .attr("x1", x)
      .attr("x2", x)
      .attr("y1", m.t)
      .attr("y2", altura - m.b);
    svg.append("g").attr("class", "eixo").attr("transform", `translate(0,${altura - m.b})`).call(d3.axisBottom(x).ticks(4).tickFormat((v) => brl.format(v)).tickSize(0).tickPadding(8));
    if (br) {
      svg.append("line").attr("x1", x(valor(br))).attr("x2", x(valor(br))).attr("y1", m.t).attr("y2", altura - m.b).style("stroke", "var(--ink-2)").style("stroke-width", 1);
      svg.append("text").attr("x", x(valor(br)) + 4).attr("y", m.t + 8).text("Brasil");
    }
    const g = svg.append("g").selectAll("g").data(dados).join("g").attr("transform", (d) => `translate(0,${y(d.uf) + y.bandwidth() / 2})`);
    g.append("text").attr("x", m.l - 8).attr("dy", "0.35em").attr("text-anchor", "end").attr("class", (d) => (d.uf === estado.uf ? "rotulo-forte" : null)).text((d) => d.uf);
    g.append("circle")
      .attr("cx", (d) => x(d.v))
      .attr("r", (d) => (d.uf === estado.uf ? 6 : 4.5))
      .style("fill", (d) => (d.uf === estado.uf ? "var(--series-1)" : "var(--neutral)"))
      .style("stroke", "var(--surface)")
      .style("stroke-width", 2);
    g.filter((d) => d.uf === estado.uf || d === dados[0] || d === dados[dados.length - 1])
      .append("text")
      .attr("x", (d) => x(d.v) + 10)
      .attr("dy", "0.35em")
      .attr("class", "rotulo-forte")
      .text((d) => brl.format(d.v));
    g.append("rect")
      .attr("x", 0)
      .attr("y", -linha / 2)
      .attr("width", largura)
      .attr("height", linha)
      .style("fill", "transparent")
      .style("cursor", "pointer")
      .on("pointermove", (ev, d) => mostrarTip(ev, nomeUF(d.uf), [{ valor: brl.format(d.v), rotulo: PRODUTOS[prod] }, { valor: d.l[I.postos], rotulo: "postos" }]))
      .on("pointerleave", esconderTip)
      .on("click", (ev, d) => definirUF(d.uf));
  }

  function razoesEtanol(p) {
    return Object.keys(R.ufs)
      .map((uf) => {
        const e = linhaDoMes(uf, "etanol", p);
        const g = linhaDoMes(uf, "gasolina", p);
        return e && g ? { uf, razao: e[I.mediana] / g[I.mediana], e: e[I.mediana], g: g[I.mediana] } : null;
      })
      .filter(Boolean)
      .sort((a, b) => a.razao - b.razao);
  }

  function renderEtanol() {
    const el = $("g-etanol");
    const p = ultimo();
    const dados = razoesEtanol(p);
    legenda($("leg-etanol"), [
      { cor: "var(--series-1)", bloco: true, rotulo: "Etanol compensa (abaixo de 70%)" },
      { cor: "var(--neutral)", bloco: true, rotulo: "Gasolina compensa" },
    ]);
    const largura = larguraDe(el);
    const linha = 20;
    const m = { t: 18, r: 16, b: 26, l: 34 };
    const altura = m.t + m.b + dados.length * linha;
    const svg = svgEm(el, largura, altura);
    svg.attr("aria-label", "Preço do etanol como percentual da gasolina, por estado");
    const x = d3.scaleLinear().domain([0, Math.max(1, d3.max(dados, (d) => d.razao))]).range([m.l, largura - m.r]);
    const y = d3.scaleBand().domain(dados.map((d) => d.uf)).range([m.t, altura - m.b]).paddingInner(0.25);
    const espessura = Math.min(14, y.bandwidth());

    svg.append("g").attr("class", "grade").selectAll("line").data(x.ticks(5)).join("line").attr("x1", x).attr("x2", x).attr("y1", m.t).attr("y2", altura - m.b);
    svg.append("g").attr("class", "eixo").attr("transform", `translate(0,${altura - m.b})`).call(d3.axisBottom(x).ticks(5).tickFormat((v) => razao.format(v)).tickSize(0).tickPadding(8));

    const g = svg.append("g").selectAll("g").data(dados).join("g").attr("transform", (d) => `translate(0,${y(d.uf) + (y.bandwidth() - espessura) / 2})`);
    // barra com ponta arredondada só no fim (base reta, no zero)
    g.append("path")
      .attr("d", (d) => {
        const w = Math.max(0, x(d.razao) - x(0));
        const r = Math.min(4, w, espessura / 2);
        return `M${x(0)},0h${w - r}a${r},${r} 0 0 1 ${r},${r}v${espessura - 2 * r}a${r},${r} 0 0 1 -${r},${r}h-${w - r}z`;
      })
      .style("fill", (d) => (d.razao <= LIMIAR_ETANOL ? "var(--series-1)" : "var(--neutral)"));
    g.append("text")
      .attr("x", m.l - 8)
      .attr("y", espessura / 2)
      .attr("dy", "0.35em")
      .attr("text-anchor", "end")
      .attr("class", (d) => (d.uf === estado.uf ? "rotulo-forte" : null))
      .text((d) => d.uf);
    g.filter((d) => d.uf === estado.uf)
      .append("text")
      .attr("x", (d) => x(d.razao) + 6)
      .attr("y", espessura / 2)
      .attr("dy", "0.35em")
      .attr("class", "rotulo-forte")
      .text((d) => razao1.format(d.razao));
    g.append("rect")
      .attr("x", 0)
      .attr("y", -(linha - espessura) / 2)
      .attr("width", largura)
      .attr("height", linha)
      .style("fill", "transparent")
      .on("pointermove", (ev, d) =>
        mostrarTip(ev, nomeUF(d.uf), [
          { valor: razao1.format(d.razao), rotulo: "do preço da gasolina" },
          { valor: brl.format(d.e), rotulo: "etanol" },
          { valor: brl.format(d.g), rotulo: "gasolina" },
        ])
      )
      .on("pointerleave", esconderTip);
    // linha dos 70%: a única referência do gráfico, em tinta (não em cor de dado)
    svg.append("line").attr("x1", x(LIMIAR_ETANOL)).attr("x2", x(LIMIAR_ETANOL)).attr("y1", m.t - 6).attr("y2", altura - m.b).style("stroke", "var(--ink)").style("stroke-width", 1.5);
    svg.append("text").attr("x", x(LIMIAR_ETANOL) + 4).attr("y", m.t - 6).attr("class", "rotulo-forte").text("70%");

    tabela(
      $("t-etanol"),
      ["Estado", "Etanol ÷ gasolina", "Etanol", "Gasolina", "Compensa"],
      dados.map((d) => [nomeUF(d.uf), razao1.format(d.razao), brl.format(d.e), brl.format(d.g), d.razao <= LIMIAR_ETANOL ? "etanol" : "gasolina"])
    );
  }

  /** Gráfico de linhas genérico com crosshair. series: [{rotulo, cor, pontos:[{p,d,v}], faixa?}] */
  function linhasNoTempo(el, series, rotuloAria) {
    const largura = larguraDe(el);
    const altura = Math.max(240, Math.round(largura * 0.42));
    const m = { t: 12, r: 86, b: 28, l: 64 };
    const svg = svgEm(el, largura, altura);
    svg.attr("aria-label", rotuloAria);
    const todos = series.flatMap((s) => s.pontos.concat(s.faixa ? s.faixa.flatMap((f) => [f.lo, f.hi].map((v) => ({ ...f, v }))) : []));
    const x = d3.scaleTime().domain(d3.extent(series[0].pontos, (d) => d.d)).range([m.l, largura - m.r]);
    const ext = d3.extent(todos.filter((d) => d.v != null), (d) => d.v);
    const y = d3.scaleLinear().domain([ext[0] * 0.95, ext[1] * 1.03]).nice().range([altura - m.b, m.t]);

    svg.append("g").attr("class", "grade").selectAll("line").data(y.ticks(5)).join("line").attr("x1", m.l).attr("x2", largura - m.r).attr("y1", y).attr("y2", y);
    svg.append("g").attr("class", "eixo").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(5).tickFormat((v) => brl.format(v)).tickSize(0).tickPadding(8));
    svg.append("g").attr("class", "eixo").attr("transform", `translate(0,${altura - m.b})`).call(d3.axisBottom(x).ticks(largura < 600 ? 4 : 8).tickFormat((d) => `${MESES[d.getMonth()]}/${String(d.getFullYear()).slice(2)}`).tickSize(0).tickPadding(8));

    for (const s of series) {
      if (s.faixa) {
        const area = d3.area().defined((d) => d.lo != null).x((d) => x(d.d)).y0((d) => y(d.lo)).y1((d) => y(d.hi));
        svg.append("path").attr("d", area(s.faixa)).style("fill", s.cor).style("opacity", 0.1);
      }
      const linha = d3.line().defined((d) => d.v != null).x((d) => x(d.d)).y((d) => y(d.v)).curve(d3.curveMonotoneX);
      svg.append("path").attr("d", linha(s.pontos)).style("fill", "none").style("stroke", s.cor).style("stroke-width", 2).style("stroke-linejoin", "round").style("stroke-linecap", "round");
    }

    // rótulo no fim de cada linha, afastando os que colidem
    const fins = series
      .map((s) => {
        const ultimoPonto = [...s.pontos].reverse().find((d) => d.v != null);
        return ultimoPonto ? { s, d: ultimoPonto, y: y(ultimoPonto.v) } : null;
      })
      .filter(Boolean)
      .sort((a, b) => a.y - b.y);
    for (let i = 1; i < fins.length; i++) if (fins[i].y - fins[i - 1].y < 15) fins[i].y = fins[i - 1].y + 15;
    for (const f of fins) {
      svg.append("circle").attr("cx", x(f.d.d)).attr("cy", y(f.d.v)).attr("r", 4).style("fill", f.s.cor).style("stroke", "var(--surface)").style("stroke-width", 2);
      svg.append("text").attr("x", x(f.d.d) + 8).attr("y", f.y).attr("dy", "0.35em").attr("class", "rotulo-forte").text(brl.format(f.d.v));
    }

    // crosshair: acha o mês mais próximo do ponteiro e lista todas as séries
    const cruz = svg.append("line").attr("y1", m.t).attr("y2", altura - m.b).style("stroke", "var(--axis)").style("opacity", 0);
    const meses = series[0].pontos.map((d) => d.d);
    svg
      .append("rect")
      .attr("x", m.l)
      .attr("y", m.t)
      .attr("width", largura - m.l - m.r)
      .attr("height", altura - m.t - m.b)
      .style("fill", "transparent")
      .on("pointermove", (ev) => {
        const [px] = d3.pointer(ev);
        const i = d3.minIndex(meses, (d) => Math.abs(x(d) - px));
        cruz.attr("x1", x(meses[i])).attr("x2", x(meses[i])).style("opacity", 1);
        const p = series[0].pontos[i].p;
        const faltou = R.meses_faltando.includes(p);
        mostrarTip(
          ev,
          faltou ? `${mesCurto(p)} · a ANP não publicou este mês` : mesCurto(p),
          series.map((s) => ({ cor: s.cor, valor: fmtValor(s.pontos[i].v), rotulo: s.rotulo }))
        );
      })
      .on("pointerleave", () => {
        cruz.style("opacity", 0);
        esconderTip();
      });
  }

  function renderEvolucao() {
    const prod = estado.produto;
    const uf = estado.uf;
    const sUF = serieCompleta(uf, prod);
    const sBR = serieCompleta("BR", prod);
    const lo = serieCompleta(uf, prod, null, "p10");
    const hi = serieCompleta(uf, prod, null, "p90");
    const faixa = sUF.map((d, i) => ({ d: d.d, lo: lo[i].v, hi: hi[i].v }));
    $("lead-evolucao").textContent = estado.real
      ? `${PRODUTOS[prod]}, preço mediano por mês em reais de ${mesLongo(R.ipca.base)} (corrigido pelo IPCA). Assim dá para ver se o combustível ficou mais caro de verdade, ou só acompanhou a inflação.`
      : `${PRODUTOS[prod]}, preço mediano por mês, no valor cobrado na época (sem correção pela inflação).`;
    legenda($("leg-evolucao"), [
      { cor: "var(--series-1)", rotulo: nomeUF(uf) },
      { cor: "var(--series-2)", rotulo: "Brasil" },
      { cor: "var(--series-1)", bloco: true, opacidade: 0.25, rotulo: `Faixa de 80% dos postos em ${uf}` },
    ]);
    linhasNoTempo(
      $("g-evolucao"),
      [
        { rotulo: nomeUF(uf), cor: "var(--series-1)", pontos: sUF, faixa },
        { rotulo: "Brasil", cor: "var(--series-2)", pontos: sBR },
      ],
      `Evolução do preço de ${PRODUTOS[prod]} em ${nomeUF(uf)} e no Brasil`
    );
    const aviso = $("aviso-falta");
    if (R.meses_faltando.length) {
      aviso.hidden = false;
      aviso.textContent = `A ANP não publicou os dados de ${R.meses_faltando.map(mesLongo).join(", ")}; o buraco na linha é esse mês, não um erro.`;
    }
    tabela(
      $("t-evolucao"),
      ["Mês", nomeUF(uf), "Brasil"],
      sUF.map((d, i) => [mesCurto(d.p), fmtValor(d.v), fmtValor(sBR[i].v)]).reverse()
    );
  }

  function renderCapitais() {
    const el = $("g-capitais");
    const p = ultimo();
    const prod = estado.produto;
    const dados = Object.entries(R.capitais)
      .map(([uf, nome]) => ({ uf, nome: R.nomes_capitais[`${uf}|${nome}`] || titulo(nome), l: linhaDoMes(`${uf}|${nome}`, prod, p) }))
      .filter((d) => d.l && d.l[I.postos] >= MIN_POSTOS_CAPITAL)
      .map((d) => ({ ...d, min: valor(d.l, "minimo"), max: valor(d.l, "maximo"), p10: valor(d.l, "p10"), p90: valor(d.l, "p90"), med: valor(d.l) }))
      .map((d) => ({ ...d, dif: d.p90 - d.p10 }))
      .sort((a, b) => b.dif - a.dif);
    legenda($("leg-capitais"), [
      { cor: "var(--series-1)", rotulo: "Faixa de 80% dos postos (sem os 10% mais baratos e os 10% mais caros)" },
      { cor: "var(--ink)", bloco: true, rotulo: "Mediana da cidade" },
    ]);
    const largura = larguraDe(el);
    const linha = 22;
    const m = { t: 8, r: 70, b: 26, l: largura < 520 ? 110 : 150 };
    const altura = m.t + m.b + dados.length * linha;
    const svg = svgEm(el, largura, altura);
    svg.attr("aria-label", `Diferença entre o posto mais barato e o mais caro de ${PRODUTOS[prod]} em cada capital`);
    const x = d3.scaleLinear().domain([d3.min(dados, (d) => d.p10), d3.max(dados, (d) => d.p90)]).nice().range([m.l, largura - m.r]);
    const y = d3.scaleBand().domain(dados.map((d) => d.uf)).range([m.t, altura - m.b]);

    svg.append("g").attr("class", "grade").selectAll("line").data(x.ticks(5)).join("line").attr("x1", x).attr("x2", x).attr("y1", m.t).attr("y2", altura - m.b);
    svg.append("g").attr("class", "eixo").attr("transform", `translate(0,${altura - m.b})`).call(d3.axisBottom(x).ticks(5).tickFormat((v) => brl.format(v)).tickSize(0).tickPadding(8));
    const g = svg.append("g").selectAll("g").data(dados).join("g").attr("transform", (d) => `translate(0,${y(d.uf) + y.bandwidth() / 2})`);
    const destaque = (d) => d.uf === estado.uf;
    g.append("text").attr("x", m.l - 10).attr("dy", "0.35em").attr("text-anchor", "end").attr("class", (d) => (destaque(d) ? "rotulo-forte" : null)).text((d) => `${d.nome} (${d.uf})`);
    g.append("line").attr("x1", (d) => x(d.p10)).attr("x2", (d) => x(d.p90)).style("stroke", "var(--series-1)").style("stroke-width", 4).style("stroke-linecap", "round").style("opacity", (d) => (destaque(d) ? 1 : 0.55));
    g.append("rect").attr("x", (d) => x(d.med) - 1.5).attr("y", -7).attr("width", 3).attr("height", 14).attr("rx", 1.5).style("fill", "var(--ink)");
    g.append("text").attr("x", (d) => x(d.p90) + 8).attr("dy", "0.35em").attr("class", (d) => (destaque(d) ? "rotulo-forte" : null)).text((d) => brl.format(d.dif));
    g.append("rect")
      .attr("x", 0)
      .attr("y", -linha / 2)
      .attr("width", largura)
      .attr("height", linha)
      .style("fill", "transparent")
      .on("pointermove", (ev, d) =>
        mostrarTip(ev, `${d.nome} (${d.uf})`, [
          { valor: brl.format(d.dif), rotulo: "de diferença na faixa de 80%" },
          { valor: `${brl.format(d.p10)} a ${brl.format(d.p90)}`, rotulo: "faixa de 80%" },
          { valor: brl.format(d.med), rotulo: "mediana" },
          { valor: `${brl.format(d.min)} a ${brl.format(d.max)}`, rotulo: "mais barato a mais caro" },
          { valor: d.l[I.postos], rotulo: "postos pesquisados" },
        ])
      )
      .on("pointerleave", esconderTip);

    tabela(
      $("t-capitais"),
      ["Capital", "Mais barato", "10% mais baratos até", "Mediana", "10% mais caros a partir de", "Mais caro", "Diferença na faixa de 80%", "Postos"],
      dados.map((d) => [`${d.nome} (${d.uf})`, brl.format(d.min), brl.format(d.p10), brl.format(d.med), brl.format(d.p90), brl.format(d.max), brl.format(d.dif), d.l[I.postos]])
    );
  }

  async function municipiosDa(uf) {
    if (!cacheMunicipios[uf]) {
      const r = await fetch(`data/municipios/${uf}.json`);
      cacheMunicipios[uf] = r.ok ? await r.json() : {};
    }
    return cacheMunicipios[uf];
  }

  async function renderMunicipio() {
    const uf = estado.uf;
    const arquivo = await municipiosDa(uf);
    const dados = arquivo.series || {};
    const bonito = (n) => (arquivo.nomes && arquivo.nomes[n]) || titulo(n);
    const nomes = Object.keys(dados).sort((a, b) => bonito(a).localeCompare(bonito(b), "pt-BR"));
    const sel = $("f-municipio");
    if (!nomes.includes(estado.municipio)) estado.municipio = nomes.includes(R.capitais[uf]) ? R.capitais[uf] : nomes[0];
    sel.replaceChildren(
      ...nomes.map((n) => {
        const o = document.createElement("option");
        o.value = n;
        o.textContent = `${bonito(n)} (${uf})`;
        o.selected = n === estado.municipio;
        return o;
      })
    );
    const mun = estado.municipio;
    const fonte = { [mun]: dados[mun] || {} };
    // Três primeiros espaços da paleta validada (seguros juntos para daltonismo)
    const series = [
      { prod: "gasolina", cor: "var(--series-1)" },
      { prod: "etanol", cor: "var(--series-2)" },
      { prod: "diesel_s10", cor: "var(--series-3)" },
    ]
      .map((s) => ({ ...s, rotulo: PRODUTOS[s.prod], pontos: serieCompleta(mun, s.prod, fonte) }))
      .filter((s) => s.pontos.some((d) => d.v != null));
    legenda($("leg-municipio"), series.map((s) => ({ cor: s.cor, rotulo: s.rotulo })));
    if (!series.length) {
      $("g-municipio").textContent = "Sem dados de gasolina, etanol ou diesel S10 para este município.";
      $("t-municipio").replaceChildren();
      return;
    }
    linhasNoTempo($("g-municipio"), series, `Preços em ${bonito(mun)}`);
    tabela(
      $("t-municipio"),
      ["Mês", ...series.map((s) => s.rotulo)],
      series[0].pontos.map((d, i) => [mesCurto(d.p), ...series.map((s) => fmtValor(s.pontos[i].v))]).reverse()
    );
  }

  function renderMetodo() {
    const q = Object.values(R.qualidade || {});
    const linhasTotal = q.reduce((a, b) => a + b.linhas, 0);
    const descartadas = q.reduce((a, b) => a + b.descartadas_faixa, 0);
    const el = $("texto-metodo");
    const ul = document.createElement("ul");
    const itens = [
      `Fonte: Série Histórica de Preços de Combustíveis da ANP (levantamento semanal nos postos), arquivos mensais de ${mesLongo(R.periodos[0])} a ${mesLongo(ultimo())}. São ${linhasTotal.toLocaleString("pt-BR")} coletas no total.`,
      "Preço de cada posto no mês = mediana das coletas daquele posto. Assim um posto visitado várias vezes não pesa mais que um visitado uma vez. Os números de estado, capital e Brasil são a mediana desses preços por posto.",
      `Correção pela inflação: IPCA do IBGE (tabela 1737), levando todos os meses a reais de ${mesLongo(R.ipca.base)}. Meses mais recentes que o último IPCA divulgado ficam no valor nominal até o índice sair.`,
      `Preços fora da faixa de R$ 0,30 a R$ 15 são tratados como erro de digitação e descartados: ${descartadas.toLocaleString("pt-BR")} coletas até agora.`,
      R.meses_faltando.length ? `A ANP não publicou os arquivos de ${R.meses_faltando.map(mesLongo).join(", ")}.` : "Nenhum mês faltando no período.",
      "A pesquisa da ANP é uma amostra (cerca de 400 municípios e 6 mil postos por mês), não um censo. Ela não traz o preço de compra pelo posto, então não dá para calcular margem.",
      "Regra dos 70%: é uma aproximação. O rendimento real do etanol em relação à gasolina varia com o carro e o jeito de dirigir.",
    ];
    for (const t of itens) {
      const li = document.createElement("li");
      li.textContent = t;
      ul.appendChild(li);
    }
    el.replaceChildren(ul);
  }

  /* ---------- estado e controles ---------- */

  function renderTudo() {
    renderIndicadores();
    renderMapa();
    renderRanking();
    renderEtanol();
    renderEvolucao();
    renderCapitais();
    renderMunicipio();
  }

  function definirUF(uf) {
    if (!R.ufs[uf] || uf === estado.uf) return;
    estado.uf = uf;
    estado.municipio = null;
    $("f-uf").value = uf;
    renderMapa();
    renderRanking();
    renderEtanol();
    renderEvolucao();
    renderCapitais();
    renderMunicipio();
  }

  function montarControles() {
    const prods = Object.keys(PRODUTOS).filter((p) => linhas("BR", p).length);
    $("f-produto").replaceChildren(
      ...prods.map((p) => {
        const o = document.createElement("option");
        o.value = p;
        o.textContent = PRODUTOS[p];
        return o;
      })
    );
    $("f-produto").addEventListener("change", (e) => {
      estado.produto = e.target.value;
      renderTudo();
    });
    $("f-uf").replaceChildren(
      ...Object.entries(R.ufs)
        .sort((a, b) => a[1].localeCompare(b[1], "pt-BR"))
        .map(([uf, nome]) => {
          const o = document.createElement("option");
          o.value = uf;
          o.textContent = nome;
          o.selected = uf === estado.uf;
          return o;
        })
    );
    $("f-uf").addEventListener("change", (e) => definirUF(e.target.value));
    $("f-municipio").addEventListener("change", (e) => {
      estado.municipio = e.target.value;
      renderMunicipio();
    });
    const alternarReal = (real) => {
      estado.real = real;
      $("f-real").setAttribute("aria-pressed", String(real));
      $("f-nominal").setAttribute("aria-pressed", String(!real));
      renderTudo();
    };
    $("f-real").addEventListener("click", () => alternarReal(true));
    $("f-nominal").addEventListener("click", () => alternarReal(false));

    const btn = $("btn-tema");
    const temaAtual = () =>
      document.documentElement.getAttribute("data-theme") || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const desenharBotao = () => {
      const escuro = temaAtual() === "dark";
      btn.textContent = escuro ? "☀" : "☾";
      btn.setAttribute("aria-label", escuro ? "Mudar para o modo claro" : "Mudar para o modo escuro");
    };
    btn.addEventListener("click", () => {
      const novo = temaAtual() === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", novo);
      try {
        localStorage.setItem("tema", novo);
      } catch (e) {
        /* sem storage, vale só nesta visita */
      }
      desenharBotao();
    });
    desenharBotao();

    let espera;
    window.addEventListener("resize", () => {
      clearTimeout(espera);
      espera = setTimeout(renderTudo, 150);
    });
  }

  async function iniciar() {
    try {
      const [resumo, malha] = await Promise.all([fetch("data/resumo.json").then((r) => r.json()), fetch("data/ufs.geojson").then((r) => r.json())]);
      R = resumo;
      geo = malha;
    } catch (erro) {
      $("selo").textContent = "Não foi possível carregar os dados. Tente recarregar a página.";
      throw erro;
    }
    $("selo").textContent = `Dados até ${mesLongo(ultimo())} · atualizado em ${R.atualizado_em.split("-").reverse().join("/")}`;
    $("f-real").textContent = `Corrigidos pela inflação (R$ de ${mesCurto(R.ipca.base)})`;
    $("rodape-atualizado").textContent = `Atualizado em ${R.atualizado_em.split("-").reverse().join("/")}`;
    montarControles();
    renderMetodo();
    renderTudo();
  }

  iniciar();
})();
