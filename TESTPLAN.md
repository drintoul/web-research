# Web Research UI — Manual Test Plan

This plan assumes the stack is running, the UI is open in a browser (by default `http://127.0.0.1:${GATEWAY_PORT}/`), and an Ollama/SearXNG service is reachable if the test case uses local search or an LLM.

## Global health check

1. Wait for the page to load.
2. Look at the status line / health indicator at the top of the page.
3. **Expected result:** All backend services show healthy/ready (`firecrawl`, `extract`, `interact`, `mcp`, etc.).

---

## 1. Search tab

1. Click the **Search** tab in the top navigation.
2. **Expected result:** The Search panel appears (`POST /v1/search`).
3. Enter a query in **Query** (e.g. `Renaissance Faires in Canada`).
4. Set **Limit** to `3`.
5. (Optional) Enter **Include terms** such as `Alaska 2027` and **Exclude terms** such as `wikipedia`.
6. Check **Scrape result pages as markdown** if you want snapshots.
7. Click **Build request**.
8. **Expected result:** The **JSON body** textarea is populated with a JSON request.
9. Click **Submit**.
10. **Expected result:** After a few seconds, the **search-out** panel shows a JSON response containing search results. Each result should include a title and a URL.

---

## 2. Map tab

1. Click the **Map** tab.
2. **Expected result:** The Map panel appears (`POST /v1/map`).
3. Enter a **URL** such as `https://www.princess.com`.
4. Set **Limit** to `10`.
5. Ensure **Include subdomains** is checked.
6. Click **Build request**.
7. **Expected result:** The **map-body** JSON body is populated.
8. Click **Submit**.
9. **Expected result:** The **map-out** panel shows a JSON list of discovered links on the site.

---

## 3. Scrape tab

1. Click the **Scrape** tab.
2. **Expected result:** The Scrape panel appears (`POST /v1/scrape`).
3. Enter a **URL** such as `https://www.princess.com`.
4. In **Formats**, verify that `markdown` is selected. Optionally add `screenshot`.
5. Check/uncheck the checkboxes as desired:
   - **Only main content**
   - **Mobile viewport**
   - **Skip TLS verification**
6. Adjust **Timeout** and **Wait for** if needed.
7. (Optional) Add **Include tags** or **Exclude tags**.
8. Click **Build request**.
9. **Expected result:** The **scrape-body** textarea is populated with a JSON body.
10. Click **Submit**.
11. **Expected result:** The **scrape-out** panel shows a JSON response with the scraped content in the selected format(s).

---

## 4. Crawl tab

1. Click the **Crawl** tab.
2. **Expected result:** The Crawl panel appears (`POST /v1/crawl`).
3. Enter a **URL** such as `https://www.princess.com`.
4. Set **Limit** to `5` and **Max depth** to `2`.
5. Check **Scrape each page as markdown**.
6. Click one of the example links or **Build request**.
7. **Expected result:** The **crawl-body** textarea is populated.
8. Click **Submit**.
9. **Expected result:** The **crawl-out** panel shows a JSON response with a `jobId`.
10. Copy the `jobId` into the **job id** input.
11. Click **Check Status**.
12. **Expected result:** The **crawl-out** panel updates with the current job status (e.g. `completed`, `scraping`, `completed` with data).

---

## 5. Extract tab

1. Click the **Extract** tab.
2. **Expected result:** The Extract panel appears (`POST /v1/extract`).
3. Enter a **URL** such as `https://www.princess.com`.
4. (Optional) Click **Random sample URL** to pick another sample page.
5. Enter an **Instruction** such as `Extract the page title and a one-sentence summary.`
6. (Optional) Click **Suggest instruction**.
7. Click **Generate / Refresh schema**.
8. **Expected result:** The **extract-body** JSON is updated to include a generated schema matching the instruction.
9. Click **Submit**.
10. **Expected result:** The **extract-out** panel shows a JSON response with the extracted fields populated.

---

## 6. Interact tab

The Interact tab has sub-tabs. Follow them in order.

### 6.1 Create

1. Click the **Interact** tab.
2. **Expected result:** The Interact panel appears with the **Create** sub-tab active.
3. Click **Create Session**.
4. **Expected result:** A session id appears in the **session id** input. The session status changes to `— session created; navigate to a URL`.
5. Click **Copy** next to the session id.

### 6.2 Navigate

1. Click the **Navigate** sub-tab.
2. Paste or type the session id into **Session id**.
3. Verify the **JSON body** contains a URL and `wait_until` value.
4. Click **Navigate**.
5. **Expected result:** The **interact-out** panel shows a JSON response confirming the page was loaded.

### 6.3 Text

1. Click the **Text** sub-tab.
2. Paste the session id.
3. Click **Get Text**.
4. **Expected result:** The **interact-out** panel shows the visible text of the loaded page.

### 6.4 Screenshot

1. Click the **Screenshot** sub-tab.
2. Paste the session id.
3. Click **Get Screenshot**.
4. **Expected result:** An image appears in the **screenshot-out** panel.

### 6.5 Action

1. Click the **Action** sub-tab.
2. Paste the session id.
3. Click **List interactive elements**.
4. **Expected result:** The **interact-out** panel lists interactive elements on the page.
5. Edit the **JSON body** to perform an action (e.g. `{"action": "click", "selector": "text=Submit"}`).
6. Click **Send Action**.
7. **Expected result:** The **interact-out** panel shows the result of the action.

### 6.6 Plan

1. Click the **Plan** sub-tab.
2. Enter a **Goal** such as `Find the search bar and enter "Alaska cruises"`.
3. Click **Generate plan**.
4. **Expected result:** The **interact-plan-out** panel shows a generated action plan. An **Execute plan** button appears.
5. Click **Execute plan**.
6. **Expected result:** The actions run and the results appear in the **interact-out** panel.

### 6.7 Close

1. Click the **Close** sub-tab.
2. Paste the session id.
3. Click **Close Session**.
4. **Expected result:** The **interact-out** panel shows a success message and the session status returns to `— no session; create one first`.

---

## 7. MCP tab

1. Click the **MCP** tab.
2. **Expected result:** The MCP panel appears (`POST /mcp`).
3. Verify the **JSON-RPC body** is the `initialize` request.
4. Click **Submit**.
5. **Expected result:** A value appears in **MCP session id** and the **mcp-out** panel shows an `initialize` result.
6. Click **2. List tools**.
7. **Expected result:** The JSON body is updated to a `tools/list` request. Click **Submit**.
8. **Expected result:** **mcp-out** shows the list of available MCP tools.
9. Select a **Tool name** from the dropdown, such as `search`.
10. Enter **Parameters** as JSON, e.g. `{ "query": "Royal Caribbean Alaska" }`.
11. Click **Build call**.
12. **Expected result:** The **mcp-body** textarea is updated to a `tools/call` JSON-RPC body.
13. Click **Submit**.
14. **Expected result:** **mcp-out** shows the tool call result.

---

## 8. Planner tab

1. Click the **Planner** tab (it has a purple active style).
2. **Expected result:** The Planner panel appears (`Natural language → MCP plan → execution`).
3. Enter a **Goal** such as:
   `Go to https://www.princess.com, find the search bar, enter 'Alaska cruises', click the Search button, wait for results, then scrape the results page.`
4. Click **Generate plan**.
5. **Expected result:** The **Planned MCP calls** panel (`planner-plan`) shows a sequence of MCP tool calls generated by the LLM. The **Execute plan** button becomes visible.
6. Review the planned calls.
7. Click **Execute plan**.
8. **Expected result:** The **Execution results** panel (`planner-out`) shows the step-by-step output as each MCP call is executed.

---

## General expectations

- All JSON output panels should be valid JSON and show a successful HTTP response.
- Errors should show in the same output panel with a message and/or status code.
- The active tab button should be highlighted (blue for most, purple for Planner).
- Sub-tab buttons in the Interact tab should enable/disable according to the session flow state.
