import logging
import azure.functions as func
import json
import os
from azure.data.tables import TableServiceClient, UpdateMode
from datetime import datetime, timedelta

# Rate limiting configuration
RATE_LIMIT = 10  # max requests
WINDOW_SECONDS = 60 * 3 # per 3 minutes

def is_rate_limited(ip: str):
    conn_str = os.environ["DEPLOYMENT_STORAGE_CONNECTION_STRING"]
    table_name = "RateLimit"
    now = datetime.utcnow()
    window_start = now - timedelta(seconds=WINDOW_SECONDS)
    partition_key = ip.replace('.', '-').replace(':', '-')
    service = TableServiceClient.from_connection_string(conn_str)
    table = service.get_table_client(table_name)
    try:
        entity = table.get_entity(partition_key=partition_key, row_key="execute")
        count = entity["Count"]
        last_reset = datetime.strptime(entity["LastReset"], "%Y-%m-%dT%H:%M:%S.%f")
        now = datetime.utcnow()
        if last_reset < window_start:
            entity["Count"] = 1
            entity["LastReset"] = now.isoformat()
            table.update_entity(entity, mode=UpdateMode.REPLACE)
            return False, RATE_LIMIT-1, WINDOW_SECONDS
        elif count >= RATE_LIMIT:
            reset_seconds = int((last_reset + timedelta(seconds=WINDOW_SECONDS) - now).total_seconds())
            return True, 0, max(reset_seconds, 0)
        else:
            entity["Count"] = count + 1
            table.update_entity(entity, mode=UpdateMode.REPLACE)
            return False, RATE_LIMIT - (count + 1), int((last_reset + timedelta(seconds=WINDOW_SECONDS) - now).total_seconds())
    except Exception:
        entity = {
            "PartitionKey": partition_key,
            "RowKey": "execute",
            "Count": 1,
            "LastReset": now.isoformat()
        }
        table.upsert_entity(entity)
        return False, RATE_LIMIT-1, WINDOW_SECONDS

def main(req: func.HttpRequest) -> func.HttpResponse:
    # Define CORS headers
    cors_headers = {
        "Access-Control-Allow-Origin": "https://rivie13.github.io, http://127.0.0.1:4000, http://localhost:4000",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
    }
    
    # Handle CORS preflight
    if req.method == "OPTIONS":
        return func.HttpResponse(
            "",
            status_code=204,
            headers=cors_headers
        )
    
    logging.info('Code execution endpoint has been disabled.')
    
    # Get IP for rate limiting (keeping this for consistency)
    ip = req.headers.get('X-Forwarded-For') or req.headers.get('X-Client-IP') or 'unknown'
    logging.info(f'Received request from IP: {ip}')
    
    try:
        is_limited, requests_remaining, reset_seconds = is_rate_limited(ip)
        if is_limited:
            return func.HttpResponse(
                json.dumps({
                    "error": "Too many requests. Please slow down.",
                    "requests_remaining": requests_remaining,
                    "reset_seconds": reset_seconds
                }),
                mimetype="application/json",
                status_code=429,
                headers=cors_headers
            )
    except Exception as e:
        return func.HttpResponse(
            json.dumps({
                "error": f"Error: {str(e)}",
                "requests_remaining": 0,
                "reset_seconds": WINDOW_SECONDS
            }),
            mimetype="application/json",
            status_code=500,
            headers=cors_headers
        )
    
    # Return a message indicating that code execution is disabled
    return func.HttpResponse(
        json.dumps({
            "error": "Code execution has been disabled. Please use the AI assistant for code help instead.",
            "requests_remaining": requests_remaining,
            "reset_seconds": reset_seconds
        }),
        mimetype="application/json",
        status_code=503,
        headers=cors_headers
    ) 