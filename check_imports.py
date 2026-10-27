import sys
import os

# Add project root to path
sys.path.insert(0, "C:\\Autodesk\\New folder\\Teacher Assistant")

# Import app and lesson_routes to verify they compile/load
import app
import lesson_routes

print("SUCCESS: app and lesson_routes imported without errors")
print("app routes:", [str(r) for r in app.app.url_map.iter_rules()])
