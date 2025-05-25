import logging
import azure.functions as func
import json
import os
import requests # Assuming Judge0 will be called via HTTP
import re
import time
from azure.data.tables import TableServiceClient, UpdateMode
from datetime import datetime, timedelta

# TODO: Retrieve Judge0 API details from Key Vault or environment variables
JUDGE0_API_URL = os.environ.get("JUDGE0_API_URL", "YOUR_JUDGE0_API_ENDPOINT") # Replace with your Judge0 endpoint
JUDGE0_API_KEY = os.environ.get("JUDGE0_API_KEY", "YOUR_JUDGE0_API_KEY") # If Judge0 requires an API key

# Hardcoded test cases and expected outputs for Two Sum
# Example: nums = [2, 7, 11, 15], target = 9, expected = [0, 1] or [1, 0]
TWO_SUM_TEST_CASES = [
    {"nums": [2, 7, 11, 15], "target": 9, "expected_indices_options": [[0, 1], [1, 0]]},
    {"nums": [3, 2, 4], "target": 6, "expected_indices_options": [[1, 2], [2, 1]]},
    {"nums": [3, 3], "target": 6, "expected_indices_options": [[0, 1], [1, 0]]},
    # Add more diverse test cases
]

# --- VM Wake-up Logic ---
START_VM_URL = os.environ.get("START_VM_FUNCTION_URL")
GET_VM_STATUS_URL = os.environ.get("GET_VM_STATUS_FUNCTION_URL")

# Helper to ensure VM is running before Judge0 call
def ensure_vm_running(timeout=300, poll_interval=10):
    if not START_VM_URL or not GET_VM_STATUS_URL:
        logging.error("VM control URLs not set in environment variables.")
        return False
    try:
        requests.post(START_VM_URL, timeout=10)
    except Exception as e:
        logging.error(f"Failed to call StartVmHttpTrigger: {e}")
        return False
    elapsed = 0
    while elapsed < timeout:
        try:
            resp = requests.get(GET_VM_STATUS_URL, timeout=10)
            data = resp.json()
            if data.get("status") == "PowerState/running":
                return True
        except Exception as e:
            logging.warning(f"Polling VM status failed: {e}")
        time.sleep(poll_interval)
        elapsed += poll_interval
    return False

# Function to scrub IP addresses from error messages
def scrub_ip_addresses(text):
    # Match IPv4 addresses
    ipv4_pattern = r'\b(?:\d{1,3}\.){3}\d{1,3}\b'
    # Match IPv6 addresses
    ipv6_pattern = r'\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b'
    
    # Replace IP addresses with [REDACTED]
    text = re.sub(ipv4_pattern, '[REDACTED]', text)
    text = re.sub(ipv6_pattern, '[REDACTED]', text)
    return text

RATE_LIMIT = 10  # max requests
WINDOW_SECONDS = 60  # per 60 seconds

def is_rate_limited(ip: str) -> bool:
    conn_str = os.environ["DEPLOYMENT_STORAGE_CONNECTION_STRING"]
    table_name = "RateLimit"
    now = datetime.utcnow()
    window_start = now - timedelta(seconds=WINDOW_SECONDS)
    partition_key = ip.replace('.', '-').replace(':', '-')  # sanitize for Table Storage

    # Connect to Table Storage
    service = TableServiceClient.from_connection_string(conn_str)
    table = service.get_table_client(table_name)
    try:
        entity = table.get_entity(partition_key=partition_key, row_key="rate")
        count = entity["Count"]
        last_reset = datetime.strptime(entity["LastReset"], "%Y-%m-%dT%H:%M:%S.%f")
        if last_reset < window_start:
            # Reset window
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
        # Entity does not exist, create it
        entity = {
            "PartitionKey": partition_key,
            "RowKey": "rate",
            "Count": 1,
            "LastReset": now.isoformat()
        }
        table.upsert_entity(entity)
        return False

def main(req: func.HttpRequest) -> func.HttpResponse:
    ip = req.headers.get('X-Forwarded-For', req.headers.get('X-Client-IP', req.remote_addr))
    if is_rate_limited(ip):
        return func.HttpResponse("Too many requests. Please slow down.", status_code=429)
    logging.info('Python HTTP trigger function processed a request for ExecuteTwoSumSolutionProxy.')

    # --- Ensure VM is running before proceeding ---
    if not ensure_vm_running():
        return func.HttpResponse(
            "Judge0 VM is not ready. Please try again in a moment.",
            status_code=503
        )

    try:
        req_body = req.get_json()
    except ValueError:
        logging.error("Invalid JSON format")
        return func.HttpResponse(
             "Please pass a valid JSON object in the request body",
             status_code=400
        )

    user_code = req_body.get('code')
    if not user_code:
        logging.error("Missing 'code' parameter")
        return func.HttpResponse(
             "Please pass 'code' in the request body",
             status_code=400
        )

    # --- Input Validation (Basic) ---
    # TODO: Implement more robust input validation (e.g., length, allowed characters/modules)
    if len(user_code) > 10000: # Arbitrary limit to prevent overly long submissions
        logging.error("User code exceeds length limit")
        return func.HttpResponse("Submitted code is too long.", status_code=400)

    results = []
    all_passed = True

    for i, test_case in enumerate(TWO_SUM_TEST_CASES):
        nums_str = str(test_case["nums"])
        target_str = str(test_case["target"])

        # --- Python Test Harness ---
        # This harness will define a function signature that the user's code should implement.
        # For "Two Sum", let's assume the user code defines a function `solve_two_sum(nums, target)`
        # that returns a list of two indices.
        
        # We will wrap the user's code and the test case execution in a try-except block
        # to catch runtime errors in the user's code.

        harness_code = f"""
import json

# User's submitted code:
{user_code}

# Test harness execution:
try:
    # Assuming the user defines a function like: solve_two_sum(nums, target)
    # Or a class Solution with a method twoSum(self, nums, target)
    # For simplicity, let's assume a function `solve_two_sum`
    
    # Try to find a Solution class first (common in LeetCode)
    if 'class Solution' in globals() and hasattr(Solution, 'twoSum') and callable(Solution.twoSum):
        solver = Solution()
        result = solver.twoSum({nums_str}, {target_str})
    elif 'solve_two_sum' in globals() and callable(solve_two_sum):
        result = solve_two_sum({nums_str}, {target_str})
    else:
        # If neither is found, this is a problem with the user's submission structure
        # This error won't be caught by the try-except below for runtime errors.
        # We need to handle this case specifically.
        print(json.dumps({{"status": "error", "message": "Code structure error: Ensure you have a 'solve_two_sum(nums, target)' function or a 'Solution' class with a 'twoSum' method."}}))
        exit() # Exit to ensure this is the only output

    # Validate result format (must be a list of 2 integers)
    if not isinstance(result, list) or len(result) != 2 or not all(isinstance(x, int) for x in result):
        print(json.dumps({{"status": "error", "message": "Output format error: Must return a list of two integers."}}))
    else:
        # Sort the result to allow comparison with expected_indices_options
        # (since the order of indices doesn't matter for Two Sum)
        result.sort()
        print(json.dumps({{"status": "success", "output": result}}))

except Exception as e:
    print(json.dumps({{"status": "error", "message": f"Runtime error: {{str(e)}}"}}))
"""
        # --- Call Judge0 (or a similar execution service) ---
        # For this stateless demo, we're running Python within Python.
        # In a real scenario with Judge0, you'd send `harness_code` to Judge0.
        # Here, we'll simulate the execution and result parsing.
        
        # This is a simplified local execution for now.
        # Replace with actual Judge0 call.
        try:
            # Using a dictionary to capture local variables from exec
            local_scope = {}
            # Redirect stdout to capture print statements from the harness
            import io
            import sys
            old_stdout = sys.stdout
            sys.stdout = captured_output = io.StringIO()
            
            exec(harness_code, globals(), local_scope)
            
            sys.stdout = old_stdout # Reset stdout
            output_str = captured_output.getvalue()
            
            # Parse the JSON output from the harness
            try:
                execution_result = json.loads(output_str.strip())
            except json.JSONDecodeError:
                # This means the harness itself had an issue or did not print valid JSON
                execution_result = {
                    "status": "error", 
                    "message": "Internal harness error or invalid output from executed code."
                }

        except Exception as e:
            # This catches errors in the exec call itself, though harness_code should catch user code errors.
            sys.stdout = old_stdout # Ensure stdout is reset even if exec fails
            error_message = str(e)
            # Scrub any IP addresses from the error message
            error_message = scrub_ip_addresses(error_message)
            execution_result = {"status": "error", "message": f"Error executing harness: {error_message}"}


        test_passed = False
        if execution_result.get("status") == "success":
            user_output = execution_result.get("output")
            # The user_output should already be sorted by the harness
            if user_output in test_case["expected_indices_options"]:
                test_passed = True
        
        results.append({
            "test_case": i + 1,
            "nums": test_case["nums"],
            "target": test_case["target"],
            "passed": test_passed,
            "output": execution_result.get("output", None) if test_passed else None,
            "error": execution_result.get("message", None) if execution_result.get("status") == "error" else None,
            "raw_judge0_output": execution_result # Or the full Judge0 response if using it
        })

        if not test_passed:
            all_passed = False

    return func.HttpResponse(
        json.dumps({"all_passed": all_passed, "results": results}),
        mimetype="application/json"
    ) 