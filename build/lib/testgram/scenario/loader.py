from __future__ import annotations

from typing import Any

import yaml


class SourceMapping(dict[str, Any]):
    def __init__(self, *args: Any, line: int | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.line = line


class SourceLineLoader(yaml.SafeLoader):
    pass


def construct_source_mapping(
    loader: SourceLineLoader,
    node: yaml.nodes.MappingNode,
) -> SourceMapping:
    loader.flatten_mapping(node)
    return SourceMapping(
        loader.construct_pairs(node),
        line=node.start_mark.line + 1,
    )


SourceLineLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    construct_source_mapping,
)


def source_line(value: Any) -> int | None:
    return value.line if isinstance(value, SourceMapping) else None
