#!/bin/bash
# Diagnose Gamma API slug query issues

SLUG="will-sabrina-carpenter-perform-during-the-super-bowl-lx-halftime-show"

echo "Testing Gamma API slug query for: $SLUG"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Test 1: Check headers and response
echo ""
echo "Test 1: Fetching with headers saved to /tmp/gamma_headers.txt"
curl -sSL -D /tmp/gamma_headers.txt -o /tmp/gamma_body.txt \
  -H 'accept: application/json' \
  -H 'user-agent: curl/8.0' \
  "https://gamma-api.polymarket.com/markets?slug=$SLUG"

echo ""
echo "---- RESPONSE HEADERS ----"
cat /tmp/gamma_headers.txt

echo ""
echo "---- RESPONSE BODY (first 500 chars) ----"
head -c 500 /tmp/gamma_body.txt
echo ""

echo ""
echo "---- FILE TYPE ----"
file /tmp/gamma_body.txt

echo ""
echo "---- BODY SIZE ----"
wc -c /tmp/gamma_body.txt

# Test 2: Try without slug (should work)
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Test 2: Fetch markets without slug filter (should return array)"
curl -sSL -H 'accept: application/json' \
  "https://gamma-api.polymarket.com/markets?limit=1" | head -c 300
echo ""

# Test 3: Try with different slug
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Test 3: Try a simpler slug"
SIMPLE_SLUG="btc-above-100k"
curl -sSL -H 'accept: application/json' \
  "https://gamma-api.polymarket.com/markets?slug=$SIMPLE_SLUG&limit=1" | head -c 300
echo ""

# Test 4: Check if it needs to be exact match
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Test 4: Search in question field instead"
curl -sSL -H 'accept: application/json' \
  "https://gamma-api.polymarket.com/markets?_q=sabrina+carpenter&limit=3" | python3 -m json.tool 2>&1 | head -40
echo ""

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Summary:"
echo "- If body is empty or HTML, it's WAF/blocking"
echo "- If body is JSON but empty array [], slug doesn't exist or is wrong"
echo "- If Test 4 works, use search (_q parameter) instead of slug"
