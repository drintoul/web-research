import asyncio
import os

from fastmcp import Client


async def main() -> None:
    url = os.getenv('MCP_TEST_URL', 'http://127.0.0.1:8081/mcp')
    async with Client(url) as client:
        tools = await client.list_tools()
        names = {getattr(t, 'name', '') for t in tools}
        required = {
            'about', 'search', 'map_site', 'scrape', 'crawl', 'crawl_status',
            'extract', 'browser_create_session', 'browser_navigate',
            'browser_action', 'browser_text', 'browser_screenshot',
            'browser_close_session',
        }
        missing = sorted(required - names)
        assert not missing, f'Missing MCP tools: {missing}'

        result = await client.call_tool('about', {})
        text = str(result)
        assert 'Search' in text or 'search' in text, text
        print(f'MCP endpoint: {url}')
        print(f'Tools discovered: {len(names)}')
        print('about tool call: OK')


if __name__ == '__main__':
    asyncio.run(main())
