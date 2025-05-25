import logging
import azure.functions as func
import json
import os
from openai import AzureOpenAI # Using the official OpenAI library

# TODO: Retrieve Azure OpenAI details from Key Vault or environment variables
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT_NAME = os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o") # Or your specific deployment
AZURE_OPENAI_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")

# Initialize AzureOpenAI client if variables are set
client = None
if AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY:
    client = AzureOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_API_KEY,
        api_version=AZURE_OPENAI_API_VERSION
    )
else:
    logging.warning("Azure OpenAI environment variables not fully configured. The GetHackAssistantResponseProxy will not be able to call OpenAI.")

# Define system prompts based on assistance level (adapt from ai-service.js logic)
# These are examples and should be refined based on the actual prompts used in CodeGrind.
SYSTEM_PROMPTS = {
    "Hints Only - Get hints and guidance, but never full code.": {
        "role": "system",
        "content": "You are Hack Assistant, an AI specialized in providing hints and conceptual guidance for programming problems, specifically the Two Sum problem. Do NOT provide direct code solutions or overly explicit code snippets. Focus on explaining concepts, suggesting approaches, and helping the user understand the logic needed to solve the problem. Encourage the user to write their own code."
    },
    "Full Solution - Receive a complete code solution.": {
        "role": "system",
        "content": "You are Hack Assistant, an AI specialized in providing complete Python code solutions for programming problems. For the Two Sum problem, provide a well-explained, functional Python solution. Assume the user is looking for a standard LeetCode-style solution (e.g., a function `solve_two_sum(nums, target)` or a class `Solution` with a method `twoSum`)."
    },
    "Step-by-Step - Get a solution broken down into logical steps.": {
        "role": "system",
        "content": "You are Hack Assistant, an AI that breaks down programming solutions into logical, easy-to-follow steps. For the Two Sum problem, provide a step-by-step guide to arrive at a solution, explaining the logic and Python constructs at each stage. You can include small, illustrative code snippets for each step, but the primary focus is on the process."
    },
    "Debug Mode - Get help identifying and fixing bugs in your code.": {
        "role": "system",
        "content": "You are Hack Assistant, an AI expert in debugging Python code. The user will provide their Two Sum solution attempt. Analyze it for logical errors, syntax issues, or inefficiencies. Provide constructive feedback and suggest specific fixes or areas to investigate. Do not rewrite the entire code unless specifically asked or if the existing code is fundamentally flawed."
    },
    "Learning Mode - Get explanations and teaching for concepts and code.": {
        "role": "system",
        "content": "You are Hack Assistant, an AI programming tutor. Explain the underlying concepts and Python features relevant to solving the Two Sum problem. If the user provides code, explain how it works, its pros and cons, and any related computer science principles (e.g., time/space complexity, hash maps). Help the user learn, don't just give answers."
    },
    "Default": { # Fallback if an unknown assistance level is provided
        "role": "system",
        "content": "You are Hack Assistant, a helpful AI assistant for programming. Respond to the user's query regarding the Two Sum problem to the best of your ability, keeping in mind they are likely working on a coding challenge."
    }
}

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request for GetHackAssistantResponseProxy.')

    if not client:
        logging.error("Azure OpenAI client not initialized. Check environment variables.")
        return func.HttpResponse(
             "OpenAI service is not configured.",
             status_code=500
        )

    try:
        req_body = req.get_json()
    except ValueError:
        logging.error("Invalid JSON format")
        return func.HttpResponse(
             "Please pass a valid JSON object in the request body",
             status_code=400
        )

    user_query = req_body.get('query')
    assistance_level = req_body.get('assistance_level') # e.g., "Hints Only..."
    # solution_context = req_body.get('solution_context', '') # User's current code for debug mode

    if not user_query or not assistance_level:
        logging.error("Missing 'query' or 'assistance_level' parameter")
        return func.HttpResponse(
             "Please pass 'query' and 'assistance_level' in the request body",
             status_code=400
        )
    
    # --- Input Validation (Basic) ---
    # TODO: Implement more robust input validation
    if len(user_query) > 2000: # Arbitrary limit
         logging.error("User query exceeds length limit")
         return func.HttpResponse("Query is too long.", status_code=400)
    if assistance_level not in SYSTEM_PROMPTS:
        logging.warning(f"Unknown assistance level: {assistance_level}. Using default.")
        system_prompt_config = SYSTEM_PROMPTS["Default"]
    else:
        system_prompt_config = SYSTEM_PROMPTS[assistance_level]

    # Construct messages for OpenAI
    messages = []

    # If in debug mode and solution context is provided, add it to the prompt.
    solution_context = req_body.get('solution_context')
    if assistance_level == "Debug Mode - Get help identifying and fixing bugs in your code." and solution_context:
        messages = [
            system_prompt_config,
            {"role": "user", "content": f"I'm working on the Two Sum problem. Here's my current Python code attempt:\n\n```python\n{solution_context}\n```\n\nMy question or issue is: {user_query}"}
        ]
    else:
        messages = [
            system_prompt_config,
            {"role": "user", "content": user_query}
        ]

    try:
        logging.info(f"Sending request to Azure OpenAI. Deployment: {AZURE_OPENAI_DEPLOYMENT_NAME}")
        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT_NAME,
            messages=messages,
            temperature=0.7, # Adjust as needed
            max_tokens=800,  # Adjust as needed
            # TODO: Add content filtering parameters if not configured at deployment level
            # (Refer to Azure AI Foundry documentation for specific parameters)
        )
        
        ai_response = response.choices[0].message.content
        
        # TODO: Output Sanitization (if needed, beyond Azure's built-in filters)
        # For now, assume Azure content filters are primary defense.

        return func.HttpResponse(
            json.dumps({"response": ai_response}),
            mimetype="application/json"
        )

    except Exception as e:
        logging.error(f"Error calling Azure OpenAI: {str(e)}")
        return func.HttpResponse(
            f"Error processing your request with AI assistant: {str(e)}",
            status_code=500
        ) 