#!/bin/bash
# ---------------------------------------------------------------------------
# Double-click this file to open the Atrium previews.
#
# It starts two small web servers on this Mac and opens your browser:
#
#   1. THE MERGED WIDGET - the listings map with the new Status filter
#      (Available Now / Entire Portfolio / Leased Only) and the Portfolio
#      filter (PG1-PG10 + the regional manager portfolios).
#   2. THE PORTFOLIO PAGES - the per-property pages with the LEASED banners.
#
# Nothing is published anywhere - this only works on this computer.
# To stop: close the Terminal window that opens, or press Control + C.
# ---------------------------------------------------------------------------

cd "$(dirname "$0")" || exit 1
PARENT="$(cd .. && pwd)"     # the Work/Claude folder holding both projects

if [ ! -d "site" ] || [ ! -f "$PARENT/atrium-listings/widget.html" ]; then
  echo "Could not find the preview folders."
  echo "Expected: $(pwd)/site  and  $PARENT/atrium-listings/widget.html"
  echo ""
  echo "Press any key to close."
  read -n 1 -s
  exit 1
fi

# Find two free ports rather than failing with an error nobody can act on.
free_port() {
  local p=$1
  while lsof -i :$p >/dev/null 2>&1; do
    p=$((p + 1))
    [ $p -gt $(($1 + 20)) ] && echo "" && return
  done
  echo $p
}
WPORT=$(free_port 8097)      # widget (serves the parent folder, so the widget
                             # can reach the portfolio data same-origin)
PPORT=$(free_port 8099)      # portfolio pages (site/ as the web root, so the
                             # pages' root-relative links keep working)
if [ -z "$WPORT" ] || [ -z "$PPORT" ]; then
  echo "Could not find free ports. Restarting your Mac will clear this up."
  echo ""
  echo "Press any key to close."
  read -n 1 -s
  exit 1
fi

PAGES=$(find site -name index.html | wc -l | tr -d ' ')

echo ""
echo "  ATRIUM - LOCAL PREVIEWS"
echo "  ------------------------------------------------------------------"
echo "  THE MERGED WIDGET (start here):"
echo "     http://localhost:$WPORT/atrium-listings/widget.html"
echo ""
echo "     Try: switch the 'Available Now' dropdown to 'Entire Portfolio'"
echo "     (gray pins = leased), then pick a portfolio - e.g. MF - Aaron Webb"
echo "     and search Champions Village."
echo ""
echo "  THE PORTFOLIO PAGES ($PAGES pages):"
echo "     The map .............. http://localhost:$PPORT/"
echo "     A leased home ........ http://localhost:$PPORT/homes/10414-andover-point-cir-orlando/"
echo "     A community .......... http://localhost:$PPORT/communities/coliseum-lofts-richmond/"
echo "     An Orlando city page . http://localhost:$PPORT/rentals/orlando-fl/"
echo ""
echo "  TO STOP: close this window, or press Control + C."
echo "  ------------------------------------------------------------------"
echo ""

# Give the servers a beat to bind before pointing the browser at them,
# otherwise Safari can land on a connection error and needs a manual reload.
( sleep 1.5; open "http://localhost:$WPORT/atrium-listings/widget.html" ) &

python3 -m http.server "$PPORT" --directory site >/dev/null 2>&1 &
PSRV=$!
trap 'kill $PSRV 2>/dev/null' EXIT

python3 -m http.server "$WPORT" --directory "$PARENT"
