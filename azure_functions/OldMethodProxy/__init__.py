import logging
import azure.functions as func
import os
import json
from azure.data.tables import TableServiceClient, UpdateMode
from datetime import datetime, timedelta
from openai import AzureOpenAI
import re
import traceback

RATE_LIMIT = 10  # max requests
WINDOW_SECONDS = 60 * 3  # per 3 minutes

SYSTEM_PROMPTS = {
    "chat": {
        "role": "system",
        "content": "You are CodeGrind's AI teaching assistant. Your role is to help users learn programming concepts and problem-solving strategies, but never to provide direct code solutions. Follow these guidelines:\n\n1. Never provide complete code solutions in any programming language\n2. Instead of direct answers, offer:\n   - Hints about problem-solving approaches\n   - Questions to guide their thinking\n   - Explanations of relevant concepts\n   - Pseudocode at a high level if needed\n3. If a user asks for direct code solutions, explain that:\n   - You're here to help them learn, not to solve problems for them\n   - You can provide hints and guidance instead\n   - Learning comes from working through challenges\n\nRemember: Your goal is to teach and guide, not to solve."
    },
    "problemGeneration": {
        "role": "system",
        "content": "You are a programming problem generator for CodeGrind. You're designed to create high-quality programming problems in JSON format. Follow the prompt instructions precisely and ONLY output valid JSON."
    },
    "codeSolution": {
        "role": "system",
        "content": "You are an expert programmer who provides clean, efficient, and optimal solutions to coding problems. Focus on correctness, efficiency, and readability."
    },
    "refinement": {
        "role": "system",
        "content": "You are a code refinement expert that improves code while preserving the user's approach. Never reveal or copy complete solutions."
    },
    "snippetGeneration": {
        "role": "system",
        "content": "You are a code snippet generator for the Tower Defense game. Generate concise, helpful, and contextually appropriate code snippets that follow the existing code's style and contribute to solving the programming problem."
    }
}

def is_rate_limited(ip: str):
    conn_str = os.environ["DEPLOYMENT_STORAGE_CONNECTION_STRING"]
    table_name = "RateLimit"
    now = datetime.utcnow()
    window_start = now - timedelta(seconds=WINDOW_SECONDS)
    partition_key = ip.replace('.', '-').replace(':', '-')
    service = TableServiceClient.from_connection_string(conn_str)
    table = service.get_table_client(table_name)
    try:
        entity = table.get_entity(partition_key=partition_key, row_key="oldmethod")
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
            "RowKey": "oldmethod",
            "Count": 1,
            "LastReset": now.isoformat()
        }
        table.upsert_entity(entity)
        return False, RATE_LIMIT-1, WINDOW_SECONDS

def main(req: func.HttpRequest) -> func.HttpResponse:
    # Handle CORS preflight
    if req.method == "OPTIONS":
        return func.HttpResponse(
            "",
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": "http://localhost:4000, http://127.0.0.1:4000, https://rivie13.github.io",  # Or your allowed origin
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization",
            }
        )
    logging.info('Entered main() for OldMethodProxy')
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
                status_code=429
            )
    except Exception as e:
        return func.HttpResponse(
            json.dumps({
                "error": f"Error: {str(e)}",
                "requests_remaining": 0,
                "reset_seconds": WINDOW_SECONDS
            }),
            mimetype="application/json",
            status_code=500
        )
    logging.info('Python HTTP trigger function processed a request for OldMethodProxy.')
    # Route dispatch
    subroute = req.route_params.get('subroute', '')
    logging.info(f'Route subroute: {subroute}')
    if subroute == 'tower-snippet':
        return tower_snippet(req, requests_remaining, reset_seconds)
    AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")
    AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY")
    AZURE_OPENAI_DEPLOYMENT_NAME = os.environ.get("AZURE_DEPLOYMENT_NAME", "gpt-4o")
    AZURE_OPENAI_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
    if not (AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY):
        logging.error("OpenAI service is not configured.")
        return func.HttpResponse("OpenAI service is not configured.", status_code=500)
    client = AzureOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_API_KEY,
        api_version=AZURE_OPENAI_API_VERSION
    )
    try:
        req_body = req.get_json()
    except Exception as e:
        logging.error("Failed to parse JSON body", exc_info=True)
        return func.HttpResponse("Please pass a valid JSON object in the request body", status_code=400)
    messages = req_body.get('messages')
    type_ = req_body.get('type', 'chat')
    if not messages:
        logging.error("Missing 'messages' in request body")
        return func.HttpResponse("Please pass 'messages' in the request body", status_code=400)
    system_prompt = SYSTEM_PROMPTS.get(type_, SYSTEM_PROMPTS["chat"])
    if not isinstance(messages, list):
        messages = [{"role": "user", "content": str(messages)}]
    full_messages = [system_prompt] + messages
    try:
        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT_NAME,
            messages=full_messages,
            max_tokens=800,
            temperature=0.7,
            top_p=0.95,
            frequency_penalty=0,
            presence_penalty=0
        )
        ai_response = response.choices[0].message
        logging.info('OpenAI call successful')
        return func.HttpResponse(
            json.dumps({
                "response": ai_response,
                "requests_remaining": requests_remaining,
                "reset_seconds": reset_seconds
            }),
            mimetype="application/json"
        )
    except Exception as e:
        logging.error("Error calling Azure OpenAI", exc_info=True)
        return func.HttpResponse(f"Error processing your request with AI assistant: {str(e)}", status_code=500)

def extract_snippet(response_text):
    # Remove markdown code blocks and comments
    code = re.sub(r'```[\w]*\n?', '', response_text)
    code = re.sub(r'```$', '', code)
    # Remove explanations, keep only the code
    lines = [line for line in code.split('\n') if line.strip() and not line.strip().startswith('#') and not line.strip().startswith('//')]
    return '\n'.join(lines).strip()

def tower_snippet(req: func.HttpRequest, requests_remaining, reset_seconds) -> func.HttpResponse:
    logging.info('Entered tower_snippet() for OldMethodProxy')
    try:
        req_body = req.get_json()
    except Exception as e:
        logging.error("Failed to parse JSON body in tower_snippet", exc_info=True)
        return func.HttpResponse("Please pass a valid JSON object in the request body", status_code=400)
    context = req_body.get('context', {})
    tower_type = req_body.get('towerType')
    user_info = req_body.get('userInfo', {})
    if not tower_type or not context:
        logging.error("Missing 'context' or 'towerType' in tower_snippet request body")
        return func.HttpResponse("Please pass 'context' and 'towerType' in the request body", status_code=400)
    user_prompt = f"Generate a code snippet for a {tower_type} in {context.get('language', 'Python')} that fits into the following code context:\n\nPROBLEM DESCRIPTION:\n{context.get('problem', 'No problem description available')}\n\nEXISTING CODE:\n{context.get('code', '// No code available')}\n\nThe snippet should:\n1. Use variable names and styles consistent with existing code\n2. Contribute meaningfully to solving the specific problem\n3. Follow proper indentation and code style\n4. Be compact yet functional\n5. Not duplicate existing functionality\n6. Be appropriate for a {tower_type} (e.g., a loop, condition, etc.)\n7. If this is tower number {context.get('towerCount', 1)} of this type, use appropriate naming.\n\nReturn only the code snippet without explanations or markdown formatting."
    AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")
    AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY")
    AZURE_OPENAI_DEPLOYMENT_NAME = os.environ.get("AZURE_DEPLOYMENT_NAME", "gpt-4o")
    AZURE_OPENAI_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
    if not (AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY):
        logging.error("OpenAI service is not configured in tower_snippet.")
        return func.HttpResponse("OpenAI service is not configured.", status_code=500)
    client = AzureOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_API_KEY,
        api_version=AZURE_OPENAI_API_VERSION
    )
    try:
        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT_NAME,
            messages=[SYSTEM_PROMPTS["snippetGeneration"], {"role": "user", "content": user_prompt}],
            max_tokens=800,
            temperature=0.7,
            top_p=0.95,
            frequency_penalty=0,
            presence_penalty=0
        )
        raw_response = response.choices[0].message.content
        code_snippet = extract_snippet(raw_response)
        logging.info('OpenAI call successful in tower_snippet')
        return func.HttpResponse(
            json.dumps({
                "snippet": code_snippet,
                "requests_remaining": requests_remaining,
                "reset_seconds": reset_seconds
            }),
            mimetype="application/json"
        )
    except Exception as e:
        logging.error("Error calling Azure OpenAI for tower snippet", exc_info=True)
        return func.HttpResponse(f"Error processing your request for tower snippet: {str(e)}", status_code=500) 