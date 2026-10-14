/* Raio-X dos Combustíveis: o mapa 3D. Cada estado vira uma coluna:
   altura = preço mediano do mês (a partir do zero, na mesma escala em toda a série, para a subida e a descida serem reais);
   cor = quanto o estado estava acima ou abaixo da mediana do Brasil naquele mês.
   Lê os dados e os filtros do app.js (window.RaioX) e não guarda estado próprio além do mês e da animação. */
import * as THREE from "./vendor/three.module.min.js";
import { OrbitControls } from "./vendor/OrbitControls.js";

const $ = (id) => document.getElementById(id);
const ALTURA_MAX = 3.2; // unidades da cena para o maior preço da série
const LIMITE_DESVIO = 0.12; // ±12% da mediana do Brasil já é cor cheia
const MS_POR_MES = 140; // série de 2004 até hoje em ~40 s
const reduzirMovimento = matchMedia("(prefers-reduced-motion: reduce)").matches;

let X = null; // window.RaioX
let renderer, cena, camera, controles, grupo, raycaster;
const blocos = new Map(); // sigla -> { mesh, bordas, alvo, atual, linha }
let meses = []; // meses com dado do produto no Brasil
let iMes = 0;
let escalaAltura = 1;
let tocando = null;
let visivel = false;
let ultimoProduto = null;
let ultimoReal = null;

/* ---------- cores (sempre das variáveis CSS, para seguir o tema) ---------- */

const css = (nome) => getComputedStyle(document.documentElement).getPropertyValue(nome).trim();
let cores = {};
function lerCores() {
  cores = {
    barato: new THREE.Color(css("--series-1")),
    caro: new THREE.Color(css("--series-2")),
    neutro: new THREE.Color(css("--neutral")),
    vazio: new THREE.Color(css("--surface-2")),
    borda: new THREE.Color(css("--surface")),
    destaque: new THREE.Color(css("--ink")),
  };
}
function corDoDesvio(d) {
  if (d == null) return cores.vazio;
  const t = Math.max(-1, Math.min(1, d / LIMITE_DESVIO));
  return cores.neutro.clone().lerp(t < 0 ? cores.barato : cores.caro, Math.abs(t));
}

/* ---------- geometria ---------- */

/** Projeção equiretangular corrigida pela latitude média do Brasil: suficiente para um mapa deste tamanho. */
const COS = Math.cos((-15 * Math.PI) / 180);
const CENTRO = [-53.5, -14.5];
const ESCALA_GEO = 0.55;
const projetar = ([lon, lat]) => new THREE.Vector2((lon - CENTRO[0]) * COS * ESCALA_GEO, (lat - CENTRO[1]) * ESCALA_GEO);

function formas(geometria) {
  const poligonos = geometria.type === "MultiPolygon" ? geometria.coordinates : [geometria.coordinates];
  return poligonos.map(([externo, ...buracos]) => {
    const forma = new THREE.Shape(externo.map(projetar));
    forma.holes = buracos.map((b) => new THREE.Path(b.map(projetar)));
    return forma;
  });
}

function montarCena(el) {
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  el.appendChild(renderer.domElement);
  renderer.domElement.setAttribute("role", "img");

  cena = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(35, 1, 0.1, 500);
  camera.position.set(0, 22, 17);


  grupo = new THREE.Group();
  grupo.rotation.x = -Math.PI / 2; // a extrusão (z) vira altura (y); o norte fica ao fundo
  cena.add(grupo);

  for (const f of X.geo.features) {
    const geometria = new THREE.ExtrudeGeometry(formas(f.geometry), { depth: 1, bevelEnabled: false });
    // ExtrudeGeometry separa tampa (grupo 0) e parede (grupo 1). Sem luz: a tampa fica exatamente na cor da legenda.
    const mesh = new THREE.Mesh(geometria, [new THREE.MeshBasicMaterial(), new THREE.MeshBasicMaterial()]);
    mesh.userData.sigla = f.properties.sigla;
    // Contorno só na tampa (z = 1 na geometria, acompanha a altura); nas laterais ele só riscaria a parede.
    const bordas = new THREE.Group();
    const materialBorda = new THREE.LineBasicMaterial();
    for (const forma of formas(f.geometry)) {
      for (const anel of [forma, ...forma.holes]) {
        const pts = anel.getPoints().map((v) => new THREE.Vector3(v.x, v.y, 1.001));
        bordas.add(new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(pts), materialBorda));
      }
    }
    bordas.material = materialBorda;
    mesh.add(bordas);
    mesh.scale.z = 0.02;
    grupo.add(mesh);
    blocos.set(f.properties.sigla, { mesh, bordas, alvo: 0.02, atual: 0.02, linha: null });
  }

  controles = new OrbitControls(camera, renderer.domElement);
  controles.target.set(0, 0.5, 1);
  controles.enableZoom = false; // a roda do mouse continua rolando a página
  controles.enablePan = false;
  controles.enableDamping = true;
  controles.minPolarAngle = 0.25;
  controles.maxPolarAngle = 1.25;
  controles.minAzimuthAngle = -1.1;
  controles.maxAzimuthAngle = 1.1;
  // No celular, arrastar o dedo sobre o mapa tem que rolar a página; girar fica só para mouse.
  if (matchMedia("(pointer: coarse)").matches) {
    controles.enabled = false;
    renderer.domElement.style.touchAction = "pan-y";
  }
  controles.update();

  raycaster = new THREE.Raycaster();
}

/* ---------- dados ---------- */

function prepararSerie() {
  const prod = X.estado.produto;
  meses = X.linhas("BR", prod).map((l) => l[X.I.periodo]);
  let max = 0;
  for (const uf of Object.keys(X.R.ufs)) for (const l of X.linhas(uf, prod)) max = Math.max(max, X.valor(l));
  escalaAltura = max ? ALTURA_MAX / max : 1;
  const slider = $("f-mes3d");
  slider.max = Math.max(0, meses.length - 1);
  if (prod !== ultimoProduto) iMes = meses.length - 1; // produto novo começa no mês mais recente
  iMes = Math.min(iMes, meses.length - 1);
  slider.value = iMes;
  ultimoProduto = prod;
  ultimoReal = X.estado.real;
}

function aplicarMes(instantaneo) {
  const prod = X.estado.produto;
  const p = meses[iMes];
  if (!p) return;
  const br = X.linhaDoMes("BR", prod, p);
  const vBR = br && X.valor(br);
  for (const [uf, b] of blocos) {
    const l = X.linhaDoMes(uf, prod, p);
    b.linha = l || null;
    const v = l ? X.valor(l) : null;
    b.alvo = v ? v * escalaAltura : 0.02;
    if (instantaneo || reduzirMovimento) b.atual = b.alvo;
    const cor = corDoDesvio(v && vBR ? v / vBR - 1 : null);
    b.mesh.material[0].color.copy(cor);
    b.mesh.material[1].color.copy(cor).multiplyScalar(0.62); // parede mais escura dá o volume
    const sel = uf === X.estado.uf;
    b.bordas.material.color.copy(sel ? cores.destaque : cores.borda);
  }
  $("mes3d").textContent = X.mesLongo(p);
  $("br3d").textContent = vBR ? `Brasil: ${X.brl.format(vBR)} (${X.unidade(prod)})` : "";
  renderer.domElement.setAttribute(
    "aria-label",
    `Mapa 3D do Brasil: preço mediano de ${X.PRODUTOS[prod]} por estado em ${X.mesLongo(p)}. A tabela do mapa acima traz os valores do mês mais recente.`
  );
}

/* ---------- interação ---------- */

function ufSobPonteiro(ev) {
  const r = renderer.domElement.getBoundingClientRect();
  const ponto = new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
  raycaster.setFromCamera(ponto, camera);
  const hit = raycaster.intersectObjects([...blocos.values()].map((b) => b.mesh), false)[0];
  return hit ? hit.object.userData.sigla : null;
}

function ligarPonteiro() {
  const c = renderer.domElement;
  let arrastou = false;
  c.addEventListener("pointerdown", () => (arrastou = false));
  controles.addEventListener("change", () => (arrastou = true));
  c.addEventListener("pointermove", (ev) => {
    const uf = ufSobPonteiro(ev);
    c.style.cursor = uf ? "pointer" : "grab";
    if (!uf) return X.esconderTip();
    const prod = X.estado.produto;
    const p = meses[iMes];
    const l = blocos.get(uf).linha;
    const br = X.linhaDoMes("BR", prod, p);
    const v = l && X.valor(l);
    X.mostrarTip(ev, `${X.nomeUF(uf)} · ${X.mesCurto(p)}`, [
      { valor: v ? X.brl.format(v) : "—", rotulo: X.PRODUTOS[prod] },
      { valor: v && br ? X.pct.format(v / X.valor(br) - 1) : "—", rotulo: "em relação ao Brasil" },
      { valor: l ? l[X.I.postos] : "—", rotulo: X.quem(prod) },
    ]);
  });
  c.addEventListener("pointerleave", () => X.esconderTip());
  c.addEventListener("click", (ev) => {
    if (arrastou) return; // girar o mapa não seleciona estado
    const uf = ufSobPonteiro(ev);
    if (uf) X.definirUF(uf);
  });
}

function pausar() {
  clearInterval(tocando);
  tocando = null;
  $("play3d").textContent = "▶ Tocar";
  $("play3d").setAttribute("aria-pressed", "false");
}
function tocar() {
  if (iMes >= meses.length - 1) iMes = 0; // no fim, recomeça de 2004
  $("play3d").textContent = "❚❚ Pausar";
  $("play3d").setAttribute("aria-pressed", "true");
  tocando = setInterval(() => {
    iMes++;
    $("f-mes3d").value = iMes;
    aplicarMes(false);
    if (iMes >= meses.length - 1) pausar();
  }, MS_POR_MES);
}

/* ---------- laço de desenho ---------- */

function redimensionar() {
  const el = $("g-mapa3d");
  const largura = el.clientWidth;
  const altura = Math.round(Math.min(Math.max(largura * 0.7, 320), 560));
  renderer.setSize(largura, altura);
  camera.aspect = largura / altura;
  // Em tela estreita o mapa precisa de mais distância para caber inteiro.
  camera.position.sub(controles.target).setLength(largura < 600 ? 40 : 31).add(controles.target);
  camera.updateProjectionMatrix();
}

function quadro() {
  requestAnimationFrame(quadro);
  if (!visivel) return;
  for (const b of blocos.values()) {
    b.atual += (b.alvo - b.atual) * 0.18;
    b.mesh.scale.z = Math.max(0.02, b.atual);
  }
  controles.update();
  renderer.render(cena, camera);
}

/* ---------- início ---------- */

function iniciar() {
  X = window.RaioX;
  const el = $("g-mapa3d");
  try {
    lerCores();
    montarCena(el);
  } catch (e) {
    el.textContent = "Seu navegador não conseguiu abrir o mapa em 3D (WebGL desligado ou indisponível). Os mesmos dados estão no mapa e nos gráficos desta página.";
    $("controles3d").hidden = true;
    return;
  }
  prepararSerie();
  aplicarMes(true);
  ligarPonteiro();

  $("f-mes3d").addEventListener("input", (e) => {
    pausar();
    iMes = +e.target.value;
    aplicarMes(false);
  });
  $("play3d").addEventListener("click", () => (tocando ? pausar() : tocar()));
  document.addEventListener("raiox:mudou", () => {
    X.esconderTip(); // o tooltip aberto seria do produto ou mês anterior
    if (X.estado.produto !== ultimoProduto || X.estado.real !== ultimoReal) {
      pausar();
      prepararSerie();
    }
    aplicarMes(false);
  });
  // Troca de tema (botão da página ou do sistema): recolore sem redesenhar a cena.
  const recolorir = () => {
    lerCores();
    aplicarMes(true);
  };
  new MutationObserver(recolorir).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", recolorir);

  new ResizeObserver(redimensionar).observe(el);
  redimensionar();
  // Só desenha quando o mapa está na tela, para não gastar bateria rolando o resto da página.
  new IntersectionObserver(([e]) => {
    visivel = e.isIntersecting;
    if (!visivel) pausar();
  }).observe(el);
  quadro();
}

if (window.RaioX) iniciar();
else document.addEventListener("raiox:pronto", iniciar, { once: true });
