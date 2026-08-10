#!/bin/bash
# ---------------------------------------------------------------------------
# Double-click this file to open the Atrium Portfolio preview.
#
# It starts a small web server on this Mac that serves the pages in the "site"
# folder, then opens them in your browser. Nothing is published anywhere - this
# only works on this computer.
#
# To stop it: close the Terminal window that opens, or press Control + C.
# ---------------------------------------------------------------------------

cd "$(dirname "$0")" || exit 1

if [ ! -d "site" ]; then
  echo "Could not find the 'site' folder next to this file."
  echo "Expected it here: $(pwd)/site"
  echo ""
  echo "Press any key to close."
  read -n 1 -s
  exit 1
fi

# 8099 is the usual port. If something else is already using it (an old copy of
# this preview that never shut down, say), step forward until we find a free one
# rather than failing with an error nobody can act on.
PORT=8099
while lsof -i :$PORT >/dev/null 2>&1; do
  PORT=$((PORT + 1))
  if [ $PORT -gt 8120 ]; then
    echo "Could not find a free port between 8099 and 8120."
    echo "Restarting your Mac will clear this up."
    echo ""
    echo "Press any key to close."
    read -n 1 -s
    exit 1
  fi
done

PAGES=$(find site -name index.html | wc -l | tr -d ' ')

echo ""
echo "  ATRIUM PORTFOLIO - LOCAL PREVIEW"
echo "  ---------------------------------------------------------"
echo "  Serving $PAGES pages at:  http://localhost:$PORT"
echo ""
echo "  Your browser should open in a moment."
echo "  If it doesn't, type that address into it yourself."
echo ""
echo "  Worth showing:"
echo "    The map .............. http://localhost:$PORT/"
echo "    A leased home ........ http://localhost:$PORT/homes/10414-andover-point-cir-orlando/"
echo "    A community .......... http://localhost:$PORT/communities/coliseum-lofts-richmond/"
echo "    An Orlando city page . http://localhost:$PORT/rentals/orlando-fl/"
echo ""
echo "  TO STOP: close this window, or press Control + C."
echo "  ---------------------------------------------------------"
echo ""

# Give the server a beat to bind the port before pointing the browser at it,
# otherwise Safari can land on a connection error and needs a manual reload.
( sleep 1.5; open "http://localhost:$PORT" ) &

python3 -m http.server "$PORT" --directory site
