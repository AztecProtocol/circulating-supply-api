#!/bin/bash

# Test script for Aztec Supply API

BASE_URL="${1:-https://supply.aztec.network}"

echo "🧪 Testing Aztec Supply API"
echo "Base URL: $BASE_URL"
echo "=============================="
echo ""

# Test 1: Full endpoint
echo "📊 Test 1: Full data (GET /)"
echo "----------------------------"
curl -s "$BASE_URL/" | jq '.' || echo "Failed"
echo ""
echo ""

# Test 2: Supply endpoint
echo "📊 Test 2: Supply endpoint (GET /supply)"
echo "----------------------------"
curl -s "$BASE_URL/supply" | jq '.' || echo "Failed"
echo ""
echo ""

# Test 3: Simple format
echo "📊 Test 3: Simple format (GET /simple)"
echo "----------------------------"
curl -s "$BASE_URL/simple" | jq '.' || echo "Failed"
echo ""
echo ""

# Test 4: Raw format
echo "📊 Test 4: Raw format (GET /raw)"
echo "----------------------------"
curl -s "$BASE_URL/raw"
echo ""
echo ""

# Test 5: Response time
echo "⏱️  Test 5: Response time"
echo "----------------------------"
TIME=$(curl -s -o /dev/null -w "%{time_total}" "$BASE_URL/")
echo "Response time: ${TIME}s"
echo ""

# Test 6: CORS headers
echo "🔐 Test 6: CORS headers"
echo "----------------------------"
curl -s -I "$BASE_URL/" | grep -i "access-control"
echo ""

echo "✅ Tests complete!"
