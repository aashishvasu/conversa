"""Model-callable random number generation, sampling, and shuffling."""

import random
import secrets
from typing import Literal

from pydantic import Field, model_validator

from .conversa_tool import ConversaTool, ToolArguments, ToolOutput

MAX_COUNT = 1000
MAX_ITEMS = 1000
MAX_RANGE_BOUND = 1_000_000_000_000


class RandomArguments(ToolArguments):
    action: Literal["integers", "sample", "shuffle"]
    start: int = Field(default=1, ge=-MAX_RANGE_BOUND, le=MAX_RANGE_BOUND)
    end: int | None = Field(default=None, ge=-MAX_RANGE_BOUND, le=MAX_RANGE_BOUND)
    count: int = Field(default=1, ge=1, le=MAX_COUNT)
    items: list[str | int | float] | None = Field(default=None, min_length=1, max_length=MAX_ITEMS)
    replacement: bool = False
    seed: int | None = Field(default=None, ge=-(2**63), le=2**63 - 1)

    @model_validator(mode="after")
    def validate_action_fields(self) -> "RandomArguments":
        if self.action == "integers":
            if self.end is None:
                raise ValueError("action 'integers' requires 'end'")
            if self.items is not None:
                raise ValueError("action 'integers' does not accept 'items'")
            if self.replacement:
                raise ValueError("action 'integers' does not accept 'replacement'")
            if self.start > self.end:
                raise ValueError(f"start ({self.start}) must be <= end ({self.end})")

        elif self.action == "sample":
            if self.items is None:
                raise ValueError("action 'sample' requires 'items'")
            if self.end is not None:
                raise ValueError("action 'sample' does not accept 'end'")
            if not self.replacement and self.count > len(self.items):
                raise ValueError(f"cannot sample {self.count} items without replacement from {len(self.items)} items")

        elif self.action == "shuffle":
            if self.items is None:
                raise ValueError("action 'shuffle' requires 'items'")
            if self.end is not None:
                raise ValueError("action 'shuffle' does not accept 'end'")
            if self.count != 1:
                raise ValueError("action 'shuffle' does not accept 'count'")
            if self.replacement:
                raise ValueError("action 'shuffle' does not accept 'replacement'")

        return self


async def execute_random(arguments: RandomArguments) -> ToolOutput:
    if arguments.seed is not None:
        rng = random.Random(arguments.seed)
        seeded = True
    else:
        rng = secrets.SystemRandom()
        seeded = False

    if arguments.action == "integers":
        results = [rng.randint(arguments.start, arguments.end) for _ in range(arguments.count)]
        val = {
            "results": results,
            "count": arguments.count,
            "start": arguments.start,
            "end": arguments.end,
            "seeded": seeded,
        }
        trace = {"action": "integers", "count": arguments.count, "seeded": seeded}
        return ToolOutput(val, trace)

    if arguments.action == "sample":
        items_copy = list(arguments.items)
        if arguments.replacement:
            results = rng.choices(items_copy, k=arguments.count)
        else:
            results = rng.sample(items_copy, k=arguments.count)
        val = {
            "results": results,
            "count": arguments.count,
            "replacement": arguments.replacement,
            "seeded": seeded,
        }
        trace = {"action": "sample", "count": arguments.count, "replacement": arguments.replacement, "seeded": seeded}
        return ToolOutput(val, trace)

    shuffled = list(arguments.items)
    rng.shuffle(shuffled)
    val = {
        "shuffled": shuffled,
        "count": len(shuffled),
        "seeded": seeded,
    }
    trace = {"action": "shuffle", "count": len(shuffled), "seeded": seeded}
    return ToolOutput(val, trace)


RANDOM_TOOL = ConversaTool(
    name="random",
    description="Generate random integers in an inclusive range, sample items with or without replacement, or shuffle a list. Supports optional integer seed for reproducibility.",
    arguments=RandomArguments,
    execute=execute_random,
    artifact_fresh_for=None,
)
