import logging
import azure.functions as func
import os
import json
from azure.data.tables import TableServiceClient, UpdateMode
from datetime import datetime, timedelta

RATE_LIMIT = 5  # max requests
WINDOW_SECONDS = 60 * 3  # per 3 minutes

def is_rate_limited(ip: str) -> bool:
    conn_str = os.environ["DEPLOYMENT_STORAGE_CONNECTION_STRING"]
    table_name = "RateLimit"
    now = datetime.utcnow()
    window_start = now - timedelta(seconds=WINDOW_SECONDS)
    partition_key = ip.replace('.', '-').replace(':', '-')  # sanitize for Table Storage

    service = TableServiceClient.from_connection_string(conn_str)
    table = service.get_table_client(table_name)
    try:
        entity = table.get_entity(partition_key=partition_key, row_key="oldmethod")
        count = entity["Count"]
        last_reset = datetime.strptime(entity["LastReset"], "%Y-%m-%dT%H:%M:%S.%f")
        if last_reset < window_start:
            entity["Count"] = 1
            entity["LastReset"] = now.isoformat()
            table.update_entity(entity, mode=UpdateMode.REPLACE)
            return False
        elif count >= RATE_LIMIT:
            return True
        else:
            entity["Count"] = count + 1
            table.update_entity(entity, mode=UpdateMode.REPLACE)
            return False
    except Exception:
        entity = {
            "PartitionKey": partition_key,
            "RowKey": "oldmethod",
            "Count": 1,
            "LastReset": now.isoformat()
        }
        table.upsert_entity(entity)
        return False

def main(req: func.HttpRequest) -> func.HttpResponse:
    ip = req.headers.get('X-Forwarded-For', req.headers.get('X-Client-IP', req.remote_addr))
    if is_rate_limited(ip):
        return func.HttpResponse("Too many requests. Please slow down.", status_code=429)
    logging.info('Python HTTP trigger function processed a request for OldMethodProxy.')
    # TODO: Implement the old method logic here
    return func.HttpResponse(json.dumps({"message": "Old method stub."}), mimetype="application/json") 