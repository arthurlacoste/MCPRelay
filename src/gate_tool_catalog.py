from __future__ import annotations

from typing import Any, Callable

from fastmcp.tools import Tool

SERVER_NAME = "gate"
_TOOL_OPTIONS = {
    "version",
    "title",
    "description",
    "icons",
    "tags",
    "annotations",
    "exclude_args",
    "output_schema",
    "serializer",
    "meta",
    "task",
    "timeout",
    "auth",
}


class GateToolCatalog:
    def __init__(self) -> None:
        self._tools: dict[str, Any] = {}

    def register(self, func: Callable[..., Any], *, name: str, options: dict[str, Any]) -> None:
        tool_options = {key: value for key, value in options.items() if key in _TOOL_OPTIONS}
        self._tools[name] = Tool.from_function(func, name=name, **tool_options)

    @staticmethod
    def _summary(tool: Any) -> dict[str, Any]:
        return {
            "server": SERVER_NAME,
            "prefix": SERVER_NAME,
            "name": tool.name,
            "title": tool.title,
            "description": tool.description or "",
        }

    def search(self, query: str | None = None, *, limit: int = 8, offset: int = 0) -> dict[str, Any]:
        needle = (query or "").casefold().strip()
        tokens = [token for token in needle.split() if token]
        matches: list[tuple[int, str, dict[str, Any]]] = []
        for tool in self._tools.values():
            tool_name = tool.name.casefold()
            title = (tool.title or "").casefold()
            description = (tool.description or "").casefold()
            haystack = f"{SERVER_NAME} {tool_name} {title} {description}"
            if needle and not any(token in haystack for token in tokens):
                continue
            score = 0
            if needle:
                if needle == tool_name:
                    score += 100
                elif needle in tool_name:
                    score += 60
                score += sum(20 for token in tokens if token in tool_name)
                score += sum(8 for token in tokens if token in title)
                score += sum(2 for token in tokens if token in description)
            matches.append((score, tool.name, self._summary(tool)))
        matches.sort(key=lambda item: (-item[0], item[1]))
        start = max(0, offset)
        size = min(max(1, limit), 100)
        page = [item[2] for item in matches[start:start + size]]
        return {"matches": page, "total": len(matches), "has_more": start + size < len(matches)}

    def read(self, tool_name: str) -> dict[str, Any]:
        tool = self._tools.get(tool_name)
        if tool is None:
            return {"error": "tool_not_found", "server": SERVER_NAME, "name": tool_name}
        return {
            **self._summary(tool),
            "inputSchema": tool.parameters,
            "outputSchema": tool.output_schema,
        }

    async def call(self, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        tool = self._tools.get(tool_name)
        if tool is None:
            return {"error": "tool_not_found", "server": SERVER_NAME, "name": tool_name}
        result = await tool.run(arguments or {})
        return result.model_dump(mode="json", by_alias=True, exclude_none=True)
