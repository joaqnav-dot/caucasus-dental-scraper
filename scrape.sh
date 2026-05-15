#!/bin/bash

OUT="/Users/macbook/Desktop/caucasus-leads"
IMAGE="gosom/google-maps-scraper"

echo ">>> Starting Caucasus dental clinic scraper..."
echo ">>> Queries: $OUT/queries.txt"
echo ">>> Output:  $OUT/caucasus_dental_leads.csv"
echo ""

docker run --rm \
  -v "$OUT:/data" \
  "$IMAGE" \
  -input  "/data/queries.txt" \
  -results "/data/caucasus_dental_leads.csv" \
  -lang en \
  -email \
  -c 4

echo ""
if [ -f "$OUT/caucasus_dental_leads.csv" ]; then
  TOTAL=$(tail -n +2 "$OUT/caucasus_dental_leads.csv" | wc -l | tr -d ' ')
  echo "✓ Done! $TOTAL clinics saved to caucasus_dental_leads.csv"
else
  echo "✗ No output file found — check errors above."
fi
