// Disliked cars for the dashboard (kept on the page, just marked): GET returns {dis: [VINs]}, PUT replaces it.
// Stored in the same KV namespace as favorites (FAVS binding), under its own key (dis:default).

const VIN = /^[A-HJ-NPR-Z0-9]{17}$/;
const MAX = 500;

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "cache-control": "no-store" } });

// ?p=jenna: another buyer's page keeps its own list (dis:jenna); Ross's page keeps dis:default
const keyFor = request => {
  const who = (request.headers.get("cf-access-authenticated-user-email") || "default").toLowerCase();
  const p = (new URL(request.url).searchParams.get("p") || "").toLowerCase();
  return /^[a-z]{1,20}$/.test(p) && p !== "ross" ? `dis:${p}${who === "default" ? "" : ":" + who}` : "dis:" + who;
};

export async function onRequestGet({ request, env }) {
  if (!env.FAVS) return json({ error: "sync not set up" }, 503);
  const saved = await env.FAVS.get(keyFor(request), "json");
  return json({ dis: Array.isArray(saved) ? saved : [] });
}

export async function onRequestPut({ request, env }) {
  if (!env.FAVS) return json({ error: "sync not set up" }, 503);
  let body;
  try { body = await request.json(); } catch { return json({ error: "bad JSON" }, 400); }
  if (!body || !Array.isArray(body.dis)) return json({ error: "expected {dis: [...]}" }, 400);
  const dis = [...new Set(body.dis.map(v => String(v).toUpperCase()).filter(v => VIN.test(v)))].slice(0, MAX);
  await env.FAVS.put(keyFor(request), JSON.stringify(dis));
  return json({ dis });
}
