/**
 * ATRIUM PORTFOLIO - Cloudflare Worker
 * ------------------------------------
 * Serves the generated portfolio pages from meetatrium.com itself instead of a
 * subdomain, WITHOUT moving the marketing site off Squarespace.
 *
 * Why this exists
 * ---------------
 * Google treats a subdomain as substantially its own site. Pages on
 * portfolio.meetatrium.com have to earn authority from zero, while pages on
 * meetatrium.com/homes/... inherit every backlink the brand domain already has.
 * atriummanagement.com ranked because the listing pages lived ON the main
 * domain - this restores that arrangement.
 *
 * Squarespace cannot host 1,200 generated pages and cannot reverse-proxy a
 * subfolder, so this Worker sits in front of the domain and splits traffic by
 * path: our prefixes come from the static origin, everything else falls through
 * to Squarespace untouched.
 *
 * SETUP
 * 1. Move meetatrium.com DNS to Cloudflare (free plan is enough).
 *    Keep the existing Squarespace records exactly as they are - proxied.
 * 2. Workers & Pages -> Create Worker -> paste this file.
 * 3. Add these routes to the Worker (Settings -> Triggers -> Routes):
 *        meetatrium.com/homes/*
 *        meetatrium.com/communities/*
 *        meetatrium.com/rentals/*
 *        meetatrium.com/portfolio.json
 *        meetatrium.com/portfolio-sitemap.xml
 *    Nothing else is routed here, so the rest of the site is untouched.
 * 4. Set ORIGIN below to wherever the built site/ folder is published.
 * 5. Set PORTFOLIO_BASE_URL=https://meetatrium.com and rebuild, so canonicals,
 *    og:url and the sitemap all point at the main domain.
 * 6. Submit https://meetatrium.com/portfolio-sitemap.xml in Search Console.
 *
 * NOTE ON THE SITEMAP PATH: Squarespace already serves /sitemap.xml and we must
 * not shadow it, so ours is published as /portfolio-sitemap.xml and referenced
 * from robots.txt. Both can be submitted independently.
 */

const ORIGIN = "https://dariusking69.github.io/atrium-portfolio";

// Only these prefixes are ours. Anything else must reach Squarespace unchanged -
// a greedy match here would take down the marketing site.
const OWNED = ["/homes/", "/communities/", "/rentals/"];
const OWNED_EXACT = ["/portfolio.json", "/portfolio-sitemap.xml"];

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const path = url.pathname;

    const isOurs =
      OWNED.some((p) => path.startsWith(p)) || OWNED_EXACT.includes(path);

    // Defensive: if a route is ever configured too broadly, fall through rather
    // than serve a 404 from our origin over a real Squarespace page.
    if (!isOurs) return fetch(request);

    // Pretty URLs -> the static file the build actually wrote.
    let originPath = path;
    if (path === "/portfolio-sitemap.xml") {
      originPath = "/sitemap.xml";
    } else if (path.endsWith("/")) {
      originPath = path + "index.html";
    } else if (!path.includes(".")) {
      // /homes/123-main-st-orlando -> canonical form has the trailing slash
      return Response.redirect(url.origin + path + "/", 301);
    }

    const originReq = new Request(ORIGIN + originPath, {
      method: "GET",
      headers: { "User-Agent": request.headers.get("User-Agent") || "" },
    });

    let res = await fetch(originReq, {
      cf: { cacheEverything: true, cacheTtl: 900 },
    });

    if (res.status === 404) {
      // A stale link to a property we no longer manage. Send it to the city hub
      // if we can work one out, otherwise the portfolio map - never a dead end,
      // and never a soft 404 that Google keeps in the index.
      const m = path.match(/^\/(?:homes|communities)\/[^/]*?-([a-z-]+)\/?$/);
      const fallback = m ? `/rentals/${m[1]}/` : "/";
      return Response.redirect(url.origin + fallback, 302);
    }

    res = new Response(res.body, res);
    res.headers.set("Cache-Control", "public, max-age=600, s-maxage=900");
    res.headers.set("X-Content-Type-Options", "nosniff");
    res.headers.delete("X-GitHub-Request-Id");
    return res;
  },
};
