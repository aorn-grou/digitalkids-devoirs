// Digital Kids · petites animations de l'interface (aucune n'est nécessaire au fonctionnement).
(function () {
  const calme = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Onde au clic sur les boutons
  document.addEventListener("pointerdown", e => {
    const b = e.target.closest(".btn, .btn-installer");
    if (!b || calme) return;
    const r = b.getBoundingClientRect(), d = Math.max(r.width, r.height);
    const o = document.createElement("span");
    o.className = "onde";
    o.style.cssText = `width:${d}px;height:${d}px;left:${e.clientX - r.left - d / 2}px;top:${e.clientY - r.top - d / 2}px`;
    b.appendChild(o);
    setTimeout(() => o.remove(), 650);
  });

  // Les chiffres du tableau de bord montent de 0 à leur valeur
  if (!calme) document.querySelectorAll(".kpi .v").forEach(el => {
    const m = el.textContent.trim().match(/^(\d+(?:[.,]\d+)?)(.*)$/);
    if (!m) return;
    const fin = parseFloat(m[1].replace(",", ".")), dec = (m[1].split(/[.,]/)[1] || "").length, suite = m[2];
    const t0 = performance.now(), duree = 900;
    const pas = t => {
      const k = Math.min(1, (t - t0) / duree), v = fin * (1 - Math.pow(1 - k, 3));
      el.textContent = v.toFixed(dec) + suite;
      if (k < 1) requestAnimationFrame(pas);
    };
    requestAnimationFrame(pas);
  });

  // Les messages verts/jaunes disparaissent seuls après 8 secondes
  document.querySelectorAll(".flash").forEach(f => setTimeout(() => {
    f.classList.add("part");
    setTimeout(() => f.remove(), 400);
  }, 8000));

  // Touche « / » : aller dans la recherche (espace animateur)
  document.addEventListener("keydown", e => {
    const c = document.querySelector(".cherche input");
    if (e.key === "/" && c && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) { e.preventDefault(); c.focus(); }
  });
})();
// Menu latéral : se ferme avec Échap ou quand on choisit une page (tablette / téléphone)
document.addEventListener("keydown", e => { if (e.key === "Escape") document.body.classList.remove("menu-ouvert"); });
document.querySelectorAll(".sidebar a").forEach(a => a.addEventListener("click", () => document.body.classList.remove("menu-ouvert")));
