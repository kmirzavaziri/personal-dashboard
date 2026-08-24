import json
import urllib.request
from urllib.error import URLError


class MCPError(RuntimeError):
    pass


def _text(result: dict) -> str:
    return '\n'.join(part.get('text', '') for part in result.get('content', []))


class MCPClient:
    def __init__(self, url: str | None, token: str | None):
        if not url:
            raise MCPError('DASHBOARD_MCP_URL is not set — cannot reach the dashboard to persist data')
        self.url = url
        self.token = token

    @classmethod
    def from_config(cls, config) -> 'MCPClient':
        return cls(config.dashboard_mcp_url, config.dashboard_mcp_token)

    def call(self, tool: str, **arguments) -> str:
        payload = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                   'params': {'name': tool, 'arguments': {k: v for k, v in arguments.items() if v is not None}}}
        headers = {'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        req = urllib.request.Request(self.url, data=json.dumps(payload).encode(), headers=headers, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                body = json.loads(response.read())
        except URLError as exc:
            raise MCPError(f'MCP request to {self.url} failed: {exc}')
        if body.get('error'):
            raise MCPError(body['error'].get('message', 'unknown MCP error'))
        result = body.get('result') or {}
        text = _text(result)
        if result.get('isError'):
            raise MCPError(text or 'MCP tool error')
        return text

    def call_json(self, tool: str, **arguments):
        return json.loads(self.call(tool, **arguments) or 'null')
