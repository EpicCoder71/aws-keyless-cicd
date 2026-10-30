"""Small, dependency-free Lambda API. Invoke with an HTTP API v2 event."""
import json
import os


def handler(event, context):
    event = event if isinstance(event, dict) else {}
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath", "/")
    if method != "GET":
        status, body = 405, {"error": "method not allowed"}
    elif path not in ("/", "/health"):
        status, body = 404, {"error": "not found"}
    else:
        status, body = 200, {"status": "ok", "service": "keyless-cicd", "environment": os.getenv("ENVIRONMENT", "local")}
    return {"statusCode": status, "headers": {"content-type": "application/json", "cache-control": "no-store"}, "body": json.dumps(body)}
