# blog-interactive-elements

This repository contains the Azure Functions powering the interactive coding elements ("Two Sum" solver and Hack Assistant) for the [rivie13.github.io](https://rivie13.github.io) blog.

## Overview

- **Stateless, secure, and Python-only**: All code execution is handled via Judge0, and all problem/test data is hardcoded in the Azure Functions.
- **No dependency on CodeGrind backend**: These functions do not call or require the CodeGrind backend. This ensures isolation, security, and simplicity.
- **No user data or authentication**: No userId is required or stored. All interactions are anonymous and stateless.
- **Security best practices**: CORS is restricted to the blog domain, all secrets (e.g., Azure OpenAI API keys) are stored in Azure Key Vault, and rate limiting is enforced.
- **Frontend integration**: The blog post at `_posts/codegrind/2025-05-21-enhancing-codegrind-ai-capabilities.md` calls these Azure Functions to power the interactive demo and Hack Assistant chat.

## Architecture

- **Azure Function: `ExecuteTwoSumSolutionProxy`**
  - Accepts user-submitted Python code for the Two Sum problem.
  - Wraps the code in a test harness and runs it against hardcoded test cases using Judge0.
  - Returns formatted results to the frontend.

- **Azure Function: `GetHackAssistantResponseProxy`**
  - Accepts user queries and assistance level for the Hack Assistant.
  - Builds the appropriate prompt and calls Azure OpenAI (API key from Key Vault).
  - Returns the AI's response to the frontend.

## Security

- **CORS**: Only allows requests from `https://rivie13.github.io`.
- **Key Vault**: All secrets are stored and accessed securely.
- **Input validation**: All user input is validated and sanitized.
- **Rate limiting**: Enforced per IP/session to prevent abuse.
- **No user data**: No userId, authentication, or persistent data.

## Usage (for developers)

1. Deploy the Azure Functions to your Azure environment.
2. Configure CORS and Key Vault access as described above.
3. Update the blog frontend to call the deployed function endpoints.

See `docfiles/blog_interactive_elements_detailed_plan.md` for a full technical and security plan.