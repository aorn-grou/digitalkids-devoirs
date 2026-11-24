/* Digital Kids · exercices interactifs. Chaque type renvoie {get: () => réponse}. */
(function () {
  "use strict";
  const D = window.DEVOIR, FAITS = window.FAITS || {};
  const el = (tag, attrs, ...kids) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k === "html") n.innerHTML = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v);
    }
    kids.flat().forEach(c => c != null && n.append(c.nodeType ? c : document.createTextNode(c)));
    return n;
  };
  const melange = (arr, graine) => {
    const a = arr.slice(); let s = 0;
    for (const ch of graine) s = (s * 31 + ch.charCodeAt(0)) >>> 0;
    for (let i = a.length - 1; i > 0; i--) { s = (s * 1103515245 + 12345) >>> 0; const j = s % (i + 1); [a[i], a[j]] = [a[j], a[i]]; }
    return a;
  };
  const boutonsChoix = (options, valeur, onChange) => {
    const box = el("div", { class: "opts" });
    options.forEach((o, i) => {
      const b = el("button", { type: "button", class: "choix-btn" + (valeur === i ? " on" : ""), text: o });
      b.addEventListener("click", () => { box.querySelectorAll(".choix-btn").forEach(x => x.classList.remove("on")); b.classList.add("on"); onChange(i); });
      box.append(b);
    });
    return box;
  };

  const T = {};

  // ---------------------------------------------------------------- relier
  T.relier = (zone, ex, prev) => {
    const rep = Object.assign({}, prev || {});
    ex.data.gauche.forEach((g, i) => {
      const sel = el("select", { "aria-label": g }, el("option", { value: "", text: "— choisis —" }), ex.data.droite.map(d => el("option", { value: d, text: d })));
      sel.value = rep[g] || "";
      sel.addEventListener("change", () => { rep[g] = sel.value; });
      const coul = (ex.data.couleurs || [])[i];
      zone.append(el("div", { class: "ligne-rel" }, coul ? el("span", { class: "blk " + coul, text: g }) : el("span", { class: "etiq", text: g }), el("span", { text: "→" }), sel));
    });
    return { get: () => rep };
  };

  // ---------------------------------------------------------------- classer
  T.classer = (zone, ex, prev) => {
    const rep = Object.assign({}, prev || {});
    let choisi = null;
    const reserve = el("div", { class: "jetons" });
    const cols = {};
    const grille = el("div", { class: "colonnes" });
    ex.data.categories.forEach(c => {
      const zoneJ = el("div", { class: "jetons" });
      const col = el("div", { class: "col", role: "button", tabindex: "0" }, el("h4", { text: c }), zoneJ);
      const poser = () => { if (choisi) { rep[choisi] = c; dessiner(); choisi = null; } };
      col.addEventListener("click", poser);
      col.addEventListener("keydown", e => { if (e.key === "Enter") poser(); });
      cols[c] = zoneJ; grille.append(col);
    });
    const dessiner = () => {
      reserve.replaceChildren(); Object.values(cols).forEach(z => z.replaceChildren());
      ex.data.items.forEach(it => {
        const j = el("button", { type: "button", class: "jeton" + (choisi === it ? " sel" : ""), text: it });
        j.addEventListener("click", e => {
          e.stopPropagation();
          if (choisi && choisi !== it && rep[it]) { rep[choisi] = rep[it]; choisi = null; dessiner(); return; } // poser le mot choisi dans cette colonne
          choisi = it; if (rep[it]) { delete rep[it]; } dessiner();
        });
        (rep[it] ? cols[rep[it]] : reserve).append(j);
      });
    };
    zone.append(el("p", { class: "aide", text: "Clique sur un mot, puis sur la bonne colonne." }), reserve, grille);
    dessiner();
    return { get: () => rep };
  };

  // ---------------------------------------------------------------- vrai / faux
  T.vraifaux = (zone, ex, prev) => {
    const rep = (prev || []).slice();
    ex.data.items.forEach((q, i) => {
      const box = el("div", { class: "vf" });
      [["Vrai", true], ["Faux", false]].forEach(([t, v]) => {
        const b = el("button", { type: "button", class: "choix-btn" + (rep[i] === v ? " on" : ""), text: t });
        b.addEventListener("click", () => { rep[i] = v; box.querySelectorAll("button").forEach(x => x.classList.remove("on")); b.classList.add("on"); });
        box.append(b);
      });
      zone.append(el("div", { class: "ligne-rel", style: "justify-content:space-between" }, el("span", { style: "font-weight:700;flex:1;min-width:200px", text: q }), box));
    });
    return { get: () => rep };
  };

  // ---------------------------------------------------------------- texte à trous
  T.trous = (zone, ex, prev) => {
    const p = el("div", { class: "texte-trous" });
    let k = 0;
    p.innerHTML = ex.data.texte.replace(/\[\]/g, () => `<input class="trou" type="text" data-i="${k++}" maxlength="3" autocomplete="off" spellcheck="false">`);
    zone.append(p);
    const ins = [...p.querySelectorAll("input")];
    (prev || []).forEach((v, i) => { if (ins[i]) ins[i].value = v; });
    return { get: () => ins.map(i => i.value) };
  };

  // ---------------------------------------------------------------- quiz (champs et choix)
  T.quiz = (zone, ex, prev) => {
    const rep = (prev || []).slice();
    if (ex.data.html) zone.append(el("div", { html: ex.data.html }));
    ex.data.items.forEach((it, i) => {
      const q = el("div", { class: "q" }, el("div", { style: "font-weight:800", text: it.q }));
      if (it.kind === "choix") {
        q.append(boutonsChoix(it.options, rep[i], v => { rep[i] = v; }));
      } else {
        const inp = el("input", { type: "text", placeholder: it.placeholder || "ta réponse", autocomplete: "off", style: "margin-top:6px;width:min(260px,100%)" });
        inp.value = rep[i] || "";
        inp.addEventListener("input", () => { rep[i] = inp.value; });
        q.append(inp);
      }
      zone.append(q);
    });
    return { get: () => rep };
  };

  // ---------------------------------------------------------------- ordre (numéroter)
  T.ordre = (zone, ex, prev) => {
    const rep = Object.assign({}, prev || {});
    const n = ex.data.items.length;
    ex.data.items.forEach(it => {
      const sel = el("select", { "aria-label": it }, el("option", { value: "", text: "n°" }), Array.from({ length: n }, (_, i) => el("option", { value: String(i + 1), text: String(i + 1) })));
      sel.value = rep[it] ? String(rep[it]) : "";
      sel.addEventListener("change", () => { rep[it] = sel.value; });
      zone.append(el("div", { class: "ligne-rel" }, sel, el("span", { style: "font-weight:700", text: it })));
    });
    return { get: () => rep };
  };

  // ---------------------------------------------------------------- blocs Scratch
  T.blocs = (zone, ex, prev) => {
    let prog = (prev || []).slice();
    const reserve = el("div", { class: "reserve" }), zoneProg = el("div", { class: "prog-blocs" });
    const dessiner = () => {
      reserve.replaceChildren(el("div", { class: "aide", text: "Les blocs : clique pour les ajouter" }));
      zoneProg.replaceChildren(el("div", { class: "aide", text: "Mon programme : clique sur un bloc pour l'enlever" }));
      ex.data.blocs.forEach(b => {
        if (prog.includes(b.t)) return;
        reserve.append(el("button", { type: "button", class: "blk " + b.c, text: b.t, onclick: () => { prog.push(b.t); dessiner(); } }));
      });
      prog.forEach((t, i) => {
        const b = ex.data.blocs.find(x => x.t === t) || { c: "ct" };
        zoneProg.append(el("button", { type: "button", class: "blk " + b.c, style: `margin-left:${Math.min(i, 4) * 0}px`, text: (i + 1) + ". " + t, onclick: () => { prog.splice(i, 1); dessiner(); } }));
      });
    };
    zone.append(el("div", { class: "deux" }, reserve, zoneProg));
    dessiner();
    return { get: () => prog };
  };

  // ---------------------------------------------------------------- clic sur une case
  T.grille_clic = (zone, ex, prev) => {
    let rep = prev || "";
    const { plateau, cols, rows, pion } = ex.data;
    const g = el("div", { class: "plateau", style: `grid-template-columns:24px repeat(${cols.length},52px)` });
    g.append(el("span"));
    cols.split("").forEach(c => g.append(el("span", { style: "color:#fff;text-align:center;font-weight:800", text: c })));
    plateau.forEach((row, i) => {
      g.append(el("span", { style: "color:#fff;font-weight:800;align-self:center;text-align:center", text: rows[i] }));
      row.forEach((c, j) => {
        const nom = cols[j] + rows[i];
        const b = el("button", { type: "button", class: "case" + (c ? "" : " clic"), text: c || (rep === nom ? pion : ""), "aria-label": nom });
        if (!c) b.addEventListener("click", () => { rep = nom; g.querySelectorAll(".case.clic").forEach(x => { x.textContent = ""; x.classList.remove("choisi"); }); b.textContent = pion; b.classList.add("choisi"); info.textContent = "Tu as choisi la case " + nom + "."; });
        if (rep === nom) b.classList.add("choisi");
        g.append(b);
      });
    });
    const info = el("p", { class: "aide", text: rep ? "Tu as choisi la case " + rep + "." : "Clique sur une case vide." });
    zone.append(g, info);
    return { get: () => rep };
  };

  // ---------------------------------------------------------------- texte libre
  T.texte = (zone, ex, prev) => {
    const t = el("textarea", { rows: ex.data.lignes || 5, placeholder: ex.data.placeholder || "", spellcheck: "false" });
    t.value = prev || "";
    zone.append(t);
    return { get: () => t.value };
  };

  // ---------------------------------------------------------------- chemin du robot
  T.chemin = (zone, ex, prev) => {
    const G = ex.data.grille; let prog = (prev || []).slice();
    const fl = { H: "↑", B: "↓", G: "←", D: "→" }, pas = { H: [-1, 0], B: [1, 0], G: [0, -1], D: [0, 1] };
    const plateau = el("div", { class: "plateau", style: `grid-template-columns:repeat(${G[0].length},52px)` });
    const cases = G.map(row => row.map(c => { const b = el("div", { class: "case" + (c === "#" ? " mur" : "") }); plateau.append(b); return b; }));
    const depart = (() => { for (let i = 0; i < G.length; i++) for (let j = 0; j < G[0].length; j++) if (G[i][j] === "R") return [i, j]; })();
    const progBox = el("div", { class: "programme", "aria-live": "polite" });
    const msg = el("p", { class: "aide" });
    const dessiner = (jusqua) => {
      G.forEach((row, i) => row.forEach((c, j) => { const b = cases[i][j]; b.classList.remove("robot", "trace"); b.textContent = c === "D" ? "🚩" : ""; }));
      let [i, j] = depart; const n = jusqua == null ? 0 : jusqua;
      for (let k = 0; k < n; k++) { const [di, dj] = pas[prog[k]]; const ni = i + di, nj = j + dj; if (ni < 0 || nj < 0 || ni >= G.length || nj >= G[0].length || G[ni][nj] === "#") { msg.textContent = "Oups ! Le robot se cogne au pas " + (k + 1) + "."; break; } cases[i][j].classList.add("trace"); i = ni; j = nj; }
      cases[i][j].classList.add("robot"); cases[i][j].textContent = "🤖";
      progBox.textContent = prog.map(m => fl[m]).join(" ") || " ";
    };
    const boutons = el("div", { class: "fleches" },
      ["H", "B", "G", "D"].map(m => el("button", { type: "button", "aria-label": fl[m], text: fl[m], onclick: () => { prog.push(m); msg.textContent = ""; dessiner(0); } })),
      el("button", { type: "button", style: "width:auto;padding:0 14px;font-size:16px;background:#E5392B", text: "Effacer", onclick: () => { prog.pop(); dessiner(0); } }),
      el("button", { type: "button", style: "width:auto;padding:0 14px;font-size:16px;background:#1FA34A", text: "▶ Tester", onclick: () => {
        msg.textContent = ""; let k = 0; const step = () => { dessiner(k); if (k < prog.length && !msg.textContent) { k++; setTimeout(step, 280); } else if (!msg.textContent) { const [ii, jj] = (() => { let [a, b] = depart; for (const m of prog) { a += pas[m][0]; b += pas[m][1]; } return [a, b]; })(); msg.textContent = (G[ii] && G[ii][jj] === "D") ? "Bravo ! Le robot est arrivé. Tu peux valider." : "Le robot n'est pas encore sur le drapeau."; } }; step();
      } }));
    zone.append(el("div", { style: "display:flex;gap:18px;flex-wrap:wrap;align-items:flex-start" }, plateau, el("div", { style: "flex:1;min-width:220px" }, el("b", { text: "Mon programme :" }), progBox, boutons, msg)));
    dessiner(0);
    return { get: () => prog };
  };

  // ---------------------------------------------------------------- fenêtre
  T.fenetre = (zone, ex) => {
    const journal = []; let etat = "normale";
    const noms = { agrandir: "1. Agrandir", reduire: "2. Réduire", restaurer: "3. Faire revenir", fermer: "4. Fermer" };
    const etapes = el("div", { class: "etapes" }, ex.data.etapes.map(e => el("span", { "data-e": e, text: noms[e] || e })));
    const ecran = el("div", { class: "ecran" });
    const fen = el("div", { class: "fen" });
    const tache = el("div", { class: "tache-barre" });
    const icone = el("button", { type: "button", text: "🗑 Corbeille", hidden: "" });
    const noter = a => { journal.push(a); let k = 0; journal.forEach(x => { if (ex.data.etapes[k] === x) k++; }); etapes.querySelectorAll("span").forEach((s, i) => s.classList.toggle("ok", i < k)); };
    const bMin = el("button", { type: "button", title: "Réduire", text: "—", onclick: () => { fen.hidden = true; icone.hidden = false; etat = "reduite"; noter("reduire"); } });
    const bMax = el("button", { type: "button", title: "Agrandir", text: "□", onclick: () => { fen.classList.toggle("max"); noter(fen.classList.contains("max") ? "agrandir" : "retrecir"); } });
    const bX = el("button", { type: "button", class: "x", title: "Fermer", text: "✕", onclick: () => { fen.hidden = true; icone.hidden = true; etat = "fermee"; noter("fermer"); fin.hidden = false; } });
    icone.addEventListener("click", () => { fen.hidden = false; icone.hidden = true; etat = "normale"; noter("restaurer"); });
    fen.append(el("div", { class: "fen-barre" }, el("span", { text: "🗑 Corbeille" }), el("span", {}, bMin, bMax, bX)), el("div", { class: "fen-corps", text: "La Corbeille est vide." }));
    tache.append(el("span", { style: "color:#fff;font-weight:800", text: "⊞" }), icone);
    const fin = el("div", { class: "fen-corps", style: "position:absolute;inset:0 0 38px 0;color:#fff", hidden: "" });
    const rouvrir = el("button", { type: "button", class: "btn petit gris", text: "Recommencer", onclick: () => { journal.length = 0; fen.hidden = false; fen.classList.remove("max"); icone.hidden = true; fin.hidden = true; noter("debut"); journal.length = 0; etapes.querySelectorAll("span").forEach(s => s.classList.remove("ok")); } });
    fin.append(el("div", { style: "text-align:center" }, el("p", { text: "Fenêtre fermée." }), rouvrir));
    ecran.append(fen, fin, tache);
    zone.append(ecran, etapes);
    return { get: () => journal.slice() };
  };

  // ---------------------------------------------------------------- affiche
  T.affiche = (zone, ex, prev) => {
    const s = Object.assign({ titre: ex.data.titre || "", taille: 18, gras: false, couleur: "#062A78", align: "left", image: "", texte: "" }, prev || {});
    const ap = el("div", { class: "apercu" });
    const majApercu = () => {
      ap.replaceChildren(
        el("div", { class: "t", style: `font-size:${s.taille * 0.9}px;font-weight:${s.gras ? 800 : 500};color:${s.couleur};text-align:${s.align}`, text: s.titre || "Titre" }),
        s.image ? el("div", { class: "img", style: `text-align:${s.align}`, text: s.image }) : el("div"),
        el("div", { class: "p", style: `text-align:${s.align}`, text: s.texte }));
    };
    const titre = el("input", { type: "text", value: s.titre, maxlength: "40", "aria-label": "Titre" });
    titre.addEventListener("input", () => { s.titre = titre.value; majApercu(); });
    const taille = el("select", { "aria-label": "Taille du titre" }, [12, 18, 24, 28, 36, 48].map(t => el("option", { value: t, text: "Taille " + t })));
    taille.value = String(s.taille); taille.addEventListener("change", () => { s.taille = +taille.value; majApercu(); });
    const bG = el("button", { type: "button", class: "outil" + (s.gras ? " on" : ""), text: "G", style: "font-weight:900", onclick: () => { s.gras = !s.gras; bG.classList.toggle("on", s.gras); majApercu(); } });
    const aligns = el("span", { class: "rang" }, [["left", "⇤ Gauche"], ["center", "≡ Centrer"], ["right", "Droite ⇥"]].map(([v, t]) => {
      const b = el("button", { type: "button", class: "outil" + (s.align === v ? " on" : ""), text: t });
      b.addEventListener("click", () => { s.align = v; aligns.querySelectorAll(".outil").forEach(x => x.classList.remove("on")); b.classList.add("on"); majApercu(); });
      return b;
    }));
    const couls = el("span", { class: "rang" }, ["#062A78", "#0B47C4", "#FF7A00", "#E5392B", "#1FA34A", "#7B3FE4"].map(c => {
      const b = el("button", { type: "button", class: "pastille-c" + (s.couleur === c ? " on" : ""), style: `background:${c}`, "aria-label": "couleur " + c });
      b.addEventListener("click", () => { s.couleur = c; couls.querySelectorAll("button").forEach(x => x.classList.remove("on")); b.classList.add("on"); majApercu(); });
      return b;
    }));
    const imgs = el("span", { class: "rang" }, ["", "🏫", "⚽", "🏀", "📚", "🐢", "🌴", "🎨"].map(i => {
      const b = el("button", { type: "button", class: "outil" + (s.image === i ? " on" : ""), text: i || "aucune" });
      b.addEventListener("click", () => { s.image = i; imgs.querySelectorAll(".outil").forEach(x => x.classList.remove("on")); b.classList.add("on"); majApercu(); });
      return b;
    }));
    const texte = el("textarea", { rows: 3, maxlength: "300", placeholder: "1 ou 2 phrases courtes", "aria-label": "Texte" });
    texte.value = s.texte; texte.addEventListener("input", () => { s.texte = texte.value; majApercu(); });
    zone.append(el("div", { class: "atelier" },
      el("div", { class: "outils" }, el("label", { text: "Titre" }), titre, el("div", { class: "rang" }, taille, bG), el("label", { text: "Couleur du titre" }), couls, el("label", { text: "Alignement" }), aligns, el("label", { text: "Image" }), imgs, el("label", { text: "Texte" }), texte),
      ap));
    majApercu();
    return { get: () => Object.assign({}, s) };
  };

  // ---------------------------------------------------------------- frappe
  T.frappe = (zone, ex, prev) => {
    const duree = ex.data.duree || 120; let reste = duree, tic = null, fini = !!prev;
    const chrono = el("span", { class: "chrono", text: fini ? "Terminé" : fmt(reste) });
    const zoneT = el("textarea", { rows: 6, disabled: "", spellcheck: "false", placeholder: "Clique sur Commencer, puis tape ici…" });
    if (prev) zoneT.value = prev.texte || "";
    const go = el("button", { type: "button", class: "btn bleu petit", text: "▶ Commencer", onclick: () => {
      if (tic || fini) return; zoneT.disabled = false; zoneT.focus(); go.disabled = true;
      tic = setInterval(() => { reste--; chrono.textContent = fmt(reste); if (reste <= 0) { clearInterval(tic); zoneT.disabled = true; fini = true; chrono.textContent = "Temps écoulé ! Clique sur Valider."; } }, 1000);
    } });
    zoneT.addEventListener("paste", e => e.preventDefault());
    zone.append(el("div", { class: "modele", text: ex.data.texte }), el("div", { style: "display:flex;gap:14px;align-items:center;margin:10px 0;flex-wrap:wrap" }, go, chrono), zoneT,
      el("p", { class: "aide", text: "Le copier-coller est désactivé : tape avec tes doigts !" }));
    return { get: () => ({ texte: zoneT.value }) };
    function fmt(s) { return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); }
  };

  // ---------------------------------------------------------------- ordinateur simulé
  T.dossiers = (zone, ex) => {
    const arbre = JSON.parse(JSON.stringify(ex.data.arbre));
    const corbeille = JSON.parse(JSON.stringify(ex.data.corbeille || {})); // nom -> chemin d'origine
    let chemin = ["Bureau"], sel = null, dansCorbeille = false;
    const noeud = (ch) => ch.reduce((n, p) => n[p], arbre);
    const estDossier = v => v !== null && typeof v === "object";
    const barre = el("div", { class: "explo-barre" });
    const fil = el("div", { class: "chemin" }), items = el("div", { class: "items" }), msg = el("div", { class: "explo-msg" }), form = el("div", { class: "mini-form", hidden: "" });
    const dire = t => { msg.textContent = t; };
    const demander = (texte, valeurInit, ok) => {
      form.hidden = false; form.replaceChildren();
      const inp = el("input", { type: "text", value: valeurInit, maxlength: "30", "aria-label": texte });
      const valider = () => { const v = inp.value.trim(); if (!v) return; form.hidden = true; ok(v); };
      inp.addEventListener("keydown", e => { if (e.key === "Enter") valider(); });
      form.append(el("b", { text: texte }), inp, el("button", { type: "button", class: "btn petit", text: "OK", onclick: valider }), el("button", { type: "button", class: "btn petit gris", text: "Annuler", onclick: () => { form.hidden = true; } }));
      inp.focus(); inp.select();
    };
    const choisirDossier = (ok) => {
      const liste = [];
      const parcours = (n, ch) => { for (const [k, v] of Object.entries(n)) if (estDossier(v)) { liste.push(ch.concat(k)); parcours(v, ch.concat(k)); } };
      parcours(arbre, []);
      form.hidden = false; form.replaceChildren();
      const s = el("select", { "aria-label": "Dossier de destination" }, liste.map(c => el("option", { value: c.join("/"), text: c.join(" › ") })));
      form.append(el("b", { text: "Déplacer vers :" }), s, el("button", { type: "button", class: "btn petit", text: "Déplacer", onclick: () => { form.hidden = true; ok(s.value.split("/")); } }), el("button", { type: "button", class: "btn petit gris", text: "Annuler", onclick: () => { form.hidden = true; } }));
    };
    const B = (t, f) => el("button", { type: "button", text: t, onclick: f });
    barre.append(
      B("← Retour", () => { if (dansCorbeille) { dansCorbeille = false; } else if (chemin.length > 1) chemin.pop(); sel = null; dessiner(); }),
      B("📁 Nouveau dossier", () => { if (dansCorbeille) return dire("On ne crée pas de dossier dans la Corbeille."); demander("Nom du dossier :", "Nouveau dossier", v => { const n = noeud(chemin); if (n[v] !== undefined) return dire("Ce nom existe déjà ici."); n[v] = {}; sel = v; dire("Dossier « " + v + " » créé."); dessiner(); }); }),
      B("✏️ Renommer", () => { if (!sel || dansCorbeille) return dire("Clique d'abord sur un fichier ou un dossier."); const ext = (!estDossier(noeud(chemin)[sel]) && sel.includes(".")) ? sel.slice(sel.lastIndexOf(".")) : ""; demander("Nouveau nom :", ext ? sel.slice(0, -ext.length) : sel, v => { const n = noeud(chemin); const nv = ext && !v.endsWith(ext) ? v + ext : v; if (n[nv] !== undefined) return dire("Ce nom existe déjà."); n[nv] = n[sel]; delete n[sel]; sel = nv; dire("Renommé en « " + nv + " »."); dessiner(); }); }),
      B("➡️ Déplacer vers…", () => { if (!sel || dansCorbeille) return dire("Clique d'abord sur un fichier ou un dossier."); choisirDossier(dest => { const n = noeud(chemin), d = noeud(dest); if (d === n[sel]) return dire("Impossible de le mettre dans lui-même."); if (d[sel] !== undefined) return dire("Il y a déjà ce nom là-bas."); d[sel] = n[sel]; delete n[sel]; dire("« " + sel + " » est maintenant dans " + dest.join(" › ") + "."); sel = null; dessiner(); }); }),
      B("🗑 Supprimer", () => { if (!sel || dansCorbeille) return dire("Clique d'abord sur un fichier ou un dossier."); const n = noeud(chemin); corbeille[sel] = { origine: chemin.join("/"), contenu: n[sel] }; delete n[sel]; dire("« " + sel + " » est dans la Corbeille."); sel = null; dessiner(); }),
      B("🗑 Ouvrir la Corbeille", () => { dansCorbeille = true; sel = null; dessiner(); }),
      B("♻️ Restaurer", () => { if (!dansCorbeille || !sel) return dire("Ouvre la Corbeille et clique sur le fichier à récupérer."); const c = corbeille[sel]; const orig = typeof c === "string" ? c : c.origine; const contenu = typeof c === "string" ? null : c.contenu; try { const d = orig.split("/").reduce((n, p) => n[p], arbre); d[sel] = contenu; delete corbeille[sel]; dire("« " + sel + " » est revenu dans " + orig.split("/").join(" › ") + "."); sel = null; dessiner(); } catch (e) { dire("Le dossier d'origine n'existe plus."); } })
    );
    const dessiner = () => {
      items.replaceChildren();
      if (dansCorbeille) {
        fil.textContent = "🗑 Corbeille";
        const noms = Object.keys(corbeille);
        if (!noms.length) items.append(el("span", { class: "aide", text: "La Corbeille est vide." }));
        noms.forEach(nm => items.append(el("button", { type: "button", class: "item" + (sel === nm ? " sel" : ""), onclick: () => { sel = nm; dessiner(); } }, el("span", { class: "ic", text: nm.includes(".") ? "📄" : "📁" }), el("span", { text: nm }))));
        return;
      }
      fil.textContent = "📂 " + chemin.join(" › ");
      const n = noeud(chemin);
      const noms = Object.keys(n);
      if (!noms.length) items.append(el("span", { class: "aide", text: "Ce dossier est vide." }));
      noms.forEach(nm => {
        const v = n[nm];
        const it = el("button", { type: "button", class: "item" + (sel === nm ? " sel" : "") }, el("span", { class: "ic", text: estDossier(v) ? "📁" : (nm.endsWith(".png") ? "🖼" : "📄") }), el("span", { text: nm }));
        it.addEventListener("click", () => { sel = nm; dessiner(); });
        it.addEventListener("dblclick", () => { if (estDossier(v)) { chemin.push(nm); sel = null; dessiner(); } });
        items.append(it);
      });
    };
    zone.append(el("p", { class: "aide", text: "Double-clic sur un dossier pour l'ouvrir. Un clic pour choisir un fichier ou un dossier." }), el("div", { class: "explo" }, barre, fil, items, form, msg));
    dessiner();
    return { get: () => ({ arbre }) };
  };

  // ---------------------------------------------------------------- moteur
  const etats = {};
  const classeNote = n => n >= 14 ? "" : (n >= 10 ? " n-moy" : " n-faible");
  const montrerResultat = (id, note, corrige) => {
    const res = document.getElementById("res-" + id);
    res.replaceChildren(el("span", { class: "note-ronde" + classeNote(note) }, String(note).replace(".", ","), el("small", { text: "/20" })),
      el("div", { class: "corr" }, el("b", { text: "CORRIGÉ" }), el("span", { text: corrige || "" })));
    res.hidden = false;
    const sec = document.getElementById("exo-" + id);
    sec.classList.add("verrou");
    const bt = sec.querySelector(".valider"); bt.disabled = true; bt.textContent = "Validé ✓";
  };
  const majSuivi = (faits, total, moy) => {
    document.getElementById("suivi-txt").textContent = `${faits} / ${total} exercices validés`;
    document.getElementById("suivi-barre").style.width = Math.round(100 * faits / total) + "%";
    document.getElementById("suivi-moy").textContent = moy == null ? "–" : String(moy).replace(".", ",");
    if (faits === total) { const f = document.getElementById("fin"); f.hidden = false; document.getElementById("fin-moy").textContent = String(moy).replace(".", ","); }
  };

  D.exercices.forEach(ex => {
    const zone = document.getElementById("zone-" + ex.id);
    const f = T[ex.type];
    if (!f) { zone.textContent = "Type d'exercice inconnu."; return; }
    const fait = FAITS[ex.id];
    etats[ex.id] = f(zone, ex, fait ? fait.reponse : undefined);
    if (fait) montrerResultat(ex.id, fait.note, fait.corrige);
    if (window.APERCU) {
      const res = document.getElementById("res-" + ex.id);
      res.replaceChildren(el("div", { class: "corr" }, el("b", { text: "CORRIGÉ (visible seulement par l'animateur)" }), el("span", { text: window.CORRIGES[ex.id] || "" })));
      res.hidden = false;
    }
  });
  const notes = Object.values(FAITS).map(x => x.note);
  majSuivi(notes.length, D.exercices.length, notes.length ? Math.round(10 * notes.reduce((a, b) => a + b, 0) / notes.length) / 10 : null);

  document.querySelectorAll(".valider").forEach(bt => bt.addEventListener("click", async () => {
    const id = bt.dataset.id;
    if (window.APERCU) { bt.textContent = "Aperçu : pas de note"; return; }
    if (bt.dataset.confirme !== "1") { bt.dataset.confirme = "1"; bt.textContent = "Sûr ? Clique encore pour valider"; setTimeout(() => { if (!bt.disabled) { bt.dataset.confirme = ""; bt.textContent = "Valider ✓"; } }, 4000); return; }
    bt.disabled = true; bt.textContent = "Correction…";
    try {
      const r = await fetch(window.URL_VALIDER, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ devoir: D.id, ex: id, reponse: etats[id].get() }) });
      const j = await r.json();
      if (!r.ok) throw new Error(j.erreur || "Erreur");
      montrerResultat(id, j.note, j.corrige);
      majSuivi(j.faits, j.total, j.moyenne);
    } catch (e) {
      bt.disabled = false; bt.dataset.confirme = ""; bt.textContent = "Valider ✓";
      const res = document.getElementById("res-" + id);
      res.replaceChildren(el("div", { class: "corr", text: "La note n'a pas pu être envoyée. Vérifie internet et réessaie." })); res.hidden = false;
    }
  }));
})();
