// Bouton « Installer l'application » : raccourci sur l'écran du PC, application sur la tablette.
(function () {
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  const seul = matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  const boutons = document.querySelectorAll("[data-installer]");
  if (seul) { boutons.forEach(b => b.hidden = true); return; }
  let invite = null;
  addEventListener("beforeinstallprompt", e => { e.preventDefault(); invite = e; });
  addEventListener("appinstalled", () => boutons.forEach(b => b.hidden = true));
  boutons.forEach(b => {
    b.hidden = false;
    b.addEventListener("click", async ev => {
      if (!invite) return; // pas d'invitation du navigateur : le lien ouvre la page d'aide
      ev.preventDefault();
      invite.prompt();
      const r = await invite.userChoice;
      invite = null;
      if (r.outcome === "accepted") boutons.forEach(x => x.hidden = true);
    });
  });
})();
