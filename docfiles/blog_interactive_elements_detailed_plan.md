# Planning Document: Blog Interactive Elements (Stateless Python Demo)

## 1. Goal

Enable secure, stateless, interactive coding elements ("Two Sum" solver and Hack Assistant) for the rivie13.github.io blog, without any dependency on the CodeGrind backend or user data.

## 2. Core Principles

- **Stateless and secure**: No userId, no persistent data, no authentication.
- **Python-only**: All code execution is in Python, using Judge0.
- **No backend dependency**: All problem/test data is hardcoded in the Azure Functions.
- **Security best practices**: CORS, Key Vault, input validation, and rate limiting.

## 3. Architecture Overview

- **Azure Function: `ExecuteTwoSumSolutionProxy`**
  - Receives user-submitted Python code for the Two Sum problem.
  - Wraps the code in a Python test harness (adapted from CodeGrind's server.js logic).
  - Runs the code against hardcoded test cases and expected outputs using Judge0.
  - Returns formatted results (pass/fail, output, errors) to the frontend.

- **Azure Function: `GetHackAssistantResponseProxy`**
  - Receives user queries and selected assistance level from the Hack Assistant UI.
  - Builds the appropriate system/user prompt (using logic adapted from ai-service.js).
  - Calls Azure OpenAI (API key securely retrieved from Key Vault).
  - Returns the AI's response to the frontend.

- **Frontend Integration**
  - The blog post at `_posts/codegrind/2025-05-21-enhancing-codegrind-ai-capabilities.md` calls these Azure Functions via `fetch`.
  - No userId or authentication is required or sent.

## 4. Security Practices

- **CORS**: Only allow requests from `https://rivie13.github.io`.
- **Key Vault**: All secrets (e.g., Azure OpenAI API key) are stored and accessed securely.
- **Input validation**: All user input is validated and sanitized in the Azure Functions.
- **Rate limiting**: Enforced per IP/session to prevent abuse.
- **No user data**: No userId, authentication, or persistent data is collected or stored.
- **HTTPS enforced**: All API calls and frontend assets are served over HTTPS.

## 5. Rationale for This Approach

- **Security**: No risk of exposing backend endpoints, user data, or secrets.
- **Simplicity**: No need to keep backend and blog demo in sync; easy to maintain and update.
- **Isolation**: Blog demo is fully isolated from production systems.
- **Compliance**: Fully aligns with the security guidelines in `docfiles/SECURITY_FOR_INTERACTIVE_BLOG_ELEMENTS.md`.

## 6. Next Steps

1. Implement the Azure Functions as described above.
2. Update the blog frontend to call the new endpoints.
3. Test end-to-end functionality and security.
4. Monitor and refine as needed. 