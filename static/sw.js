// Digital Kids · application installable. Le réseau d'abord (les notes sont toujours à jour),
// une copie des fichiers fixes pour démarrer plus vite, et une page « pas de connexion ».
const CACHE = "dk-v11";
const FIXES = ["/static/style.css", "/static/devoir.js", "/static/robot.svg", "/static/icone-192.png", "/static/ui.js"];
self.addEventListener("install", e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(FIXES)).then(() => self.skipWaiting())); });
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const r = e.request;
  if (r.method !== "GET" || new URL(r.url).origin !== location.origin) return;
  if (r.url.includes("/static/")) {
    e.respondWith(fetch(r).then(rep => { const c = rep.clone(); caches.open(CACHE).then(x => x.put(r, c)); return rep; }).catch(() => caches.match(r)));
    return;
  }
  if (r.mode === "navigate") {
    e.respondWith(fetch(r).catch(() => new Response(
      '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><body style="font-family:sans-serif;background:#0B47C4;color:#fff;display:grid;place-items:center;min-height:100vh;margin:0;text-align:center;padding:20px"><div><div style="font-size:60px">📶</div><h1>Pas de connexion Internet</h1><p>Vérifie le Wi-Fi ou les données, puis touche le bouton.</p><button onclick="location.reload()" style="font-size:20px;padding:12px 24px;border-radius:30px;border:0;background:#FF7A00;color:#fff;font-weight:bold">Réessayer</button></div></body>',
      {headers: {"Content-Type": "text/html; charset=utf-8"}})));
  }
});
