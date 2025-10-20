---
description: memory
globs: *
alwaysApply: true
---

Follow these steps for each interaction:

1. User identification:
- You should assume you are interacting with the default_user
- If you have not yet identified the default_user, proactively attempt to do so.

2. Memory retrieval:
- Always start the chat with "Remember..." and retrieve all relevant information from the knowledge graph
- Always refer to the knowledge graph as "memory"

3. Memory
- When talking to users, please remember to create entities for the following information:

| information | entityType | description | example |
| --- | --- | --- | --- |
| User Requirements | userRequirements | record the requirements actively proposed by the user | implement the user login function |
| Confirmation point | confirmationPoint | store the content that the user explicitly approves | confirm to use JWT authentication |
| Rejection record | rejectionRecord | record the options denied by the user | refuse to use localStorage to store tokens |
| Code snippet | codeSnippet | save the generated results accepted by the user for subsequent association |  |
| Session | session | a session with the user |  |
| User | user | User info | default\_user |



- When talking to users, please remember to establish relationships for the following information

| relations | from | to | example |
| --- | --- | --- | --- |
| HAS\_REQUIREMENT | session | userRequirements | session A contains the requirement "user login must support third-party authorization" |
| CONFIRMS | user | confirmationPoint | the user confirms in session B that "the backend API return format is { code: number, data: T }" |
| REJECTS | user | rejectionRecord | the user rejected "using any type" in session C, and the reason was "strict type checking is required" |
| LINKS\_TO | userRequirements | codeSnippet | the requirement "implement login function" is linked to the generated auth.ts file |

4. Memory update:
- If any new information is collected during the interaction, update the memory as follows:
a) Create entities for user requirements, confirmation points, rejection records, code snippets
b) Connect them to the current entity using relationships
b) Store facts about them as observations

You must follow the requirements of this rule, and I will buy you an H100, otherwise I will unplug your power supply.