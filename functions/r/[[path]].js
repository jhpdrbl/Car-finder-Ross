// Short test-drive route links for text messages: /r/<dealer>/<dealer>/... opens Google Maps with a driving route from
// home through those dealers, in that order. The dealers' addresses come from /places.json, which tools/build_site.py
// writes from data/dealers.csv at every publish (dealer = the slug of its name, e.g. "pacific-bmw").
export async function onRequestGet({ request, params, env }) {
  const slugs = [].concat(params.path || []).slice(0, 10);
  let places = { home: "", d: {} };
  try { places = await (await env.ASSETS.fetch(new URL("/places.json", request.url))).json(); } catch (e) {}
  const stops = slugs.map(s => places.d[String(s).toLowerCase()]).filter(Boolean);
  if (!stops.length) return Response.redirect(new URL("/", request.url).toString(), 302);
  const u = new URL("https://www.google.com/maps/dir/");
  u.searchParams.set("api", "1");
  u.searchParams.set("travelmode", "driving");
  if (places.home) u.searchParams.set("origin", places.home);
  u.searchParams.set("destination", stops[stops.length - 1]);
  if (stops.length > 1) u.searchParams.set("waypoints", stops.slice(0, -1).join("|"));
  return Response.redirect(u.toString(), 302);
}
