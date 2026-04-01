#!/bin/bash

# Coffee Oracle System Test Script
echo "🚀 Starting Coffee Oracle System Tests"
echo "=================================================="

# Admin credentials
AUTH="admin:secret_pass"
BASE_URL="http://localhost:8000"

# Test function
test_endpoint() {
    local endpoint="$1"
    local description="$2"
    local expected_status="${3:-200}"
    
    echo -n "Testing $description... "
    
    response=$(curl -s -u "$AUTH" -w "%{http_code}" -o /tmp/response.json "$BASE_URL$endpoint")
    status_code="${response: -3}"
    
    if [ "$status_code" = "$expected_status" ]; then
        echo "✅ OK (HTTP $status_code)"
        return 0
    else
        echo "❌ FAILED (HTTP $status_code)"
        return 1
    fi
}

# Test HTML page
test_html_page() {
    local endpoint="$1"
    local description="$2"
    local search_text="$3"
    
    echo -n "Testing $description... "
    
    response=$(curl -s -u "$AUTH" -w "%{http_code}" "$BASE_URL$endpoint")
    status_code="${response: -3}"
    
    if [ "$status_code" = "200" ] && echo "$response" | grep -q "$search_text"; then
        echo "✅ OK (HTTP $status_code)"
        return 0
    else
        echo "❌ FAILED (HTTP $status_code or missing content)"
        return 1
    fi
}

# Run tests
passed=0
total=0

# API Tests
tests=(
    "/health|Health Check"
    "/api/dashboard|Dashboard Stats"
    "/api/users|Users API"
    "/api/predictions|Predictions API"
    "/api/analytics?period=24h|Analytics API (24h)"
    "/api/analytics?period=7d|Analytics API (7d)"
    "/api/retention|Retention Stats"
)

for test in "${tests[@]}"; do
    IFS='|' read -r endpoint description <<< "$test"
    if test_endpoint "$endpoint" "$description"; then
        ((passed++))
    fi
    ((total++))
done

# HTML Page Test
if test_html_page "/" "Dashboard HTML Page" "Coffee Oracle Admin Dashboard"; then
    ((passed++))
fi
((total++))

# Show sample data
echo ""
echo "📊 Sample Data:"
echo "Dashboard Stats:"
curl -s -u "$AUTH" "$BASE_URL/api/dashboard" | python3 -m json.tool | head -10

echo ""
echo "Users Count:"
curl -s -u "$AUTH" "$BASE_URL/api/users" | python3 -c "import sys, json; data=json.load(sys.stdin); print(f'Found {len(data)} users')"

echo ""
echo "Predictions Count:"
curl -s -u "$AUTH" "$BASE_URL/api/predictions" | python3 -c "import sys, json; data=json.load(sys.stdin); print(f'Found {len(data)} predictions')"

# Summary
echo ""
echo "=================================================="
if [ "$passed" -eq "$total" ]; then
    echo "🎉 ALL TESTS PASSED! ($passed/$total)"
    echo "✨ Coffee Oracle System is fully operational!"
    echo "🌐 Admin Panel: http://localhost:8000"
    echo "🔐 Login: admin / secret_pass"
    exit 0
else
    echo "❌ SOME TESTS FAILED: $passed/$total passed"
    exit 1
fi